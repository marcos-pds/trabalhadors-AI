"""Persistent provider health, rate-limited half-open recovery and routing metrics.

Only real provider calls are recorded. No synthetic probes or invented uptime.
"""
import time
from datetime import datetime, timezone

TRANSIENT = {'unavailable', 'rate_limit', 'timeout', 'network', 'response'}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class ProviderHealth:
    def __init__(self, db, clock=None):
        self.db = db
        self.clock = clock or time.time

    def detail(self, provider_id, model):
        row = self.db.one('SELECT * FROM provider_health WHERE provider_id=? AND model=?', (provider_id, model))
        samples = self.db.all('''SELECT success, latency_ms FROM provider_attempts
            WHERE provider_id=? AND model=? ORDER BY id DESC LIMIT 20''', (provider_id, model))
        n = len(samples)
        success_count = sum(x['success'] for x in samples)
        measured = [x['latency_ms'] for x in samples if x['latency_ms'] is not None]
        now = self.clock()
        until = (row or {}).get('suspended_until')
        probe = (row or {}).get('probe_started_at')
        if until and until > now:
            state = 'suspended'
        elif until and until <= now:
            state = 'recovering'
        elif probe and probe + 120 > now:
            state = 'recovering'
        elif not n:
            state = 'untested'
        elif success_count == n:
            state = 'healthy'
        else:
            state = 'degraded'
        return {
            'state': state,
            'samples': n,
            'success_rate': round(100 * success_count / n, 1) if n else None,
            'avg_latency_ms': round(sum(measured) / len(measured)) if measured else None,
            'consecutive_failures': (row or {}).get('consecutive_failures', 0),
            'suspended_until': until,
            'remaining_seconds': max(0, int(until - now + 0.999)) if until else 0,
            'last_error_category': (row or {}).get('last_error_category'),
            'last_http_status': (row or {}).get('last_http_status'),
            'last_checked_at': (row or {}).get('last_checked_at'),
        }

    def rank(self, providers, preferred=None, preferred_model=None):
        """Give strong preference to assigned models, except unhealthy/suspended ones.

        Requires >=5 observations for historical success rate to outweigh priority.
        Cooldown-expired candidates remain eligible for a single half-open probe.
        """
        def score(provider):
            model = preferred_model if provider['id'] == preferred and preferred_model else provider['model']
            d = self.detail(provider['id'], model)
            unavailable = d['state'] == 'suspended'
            samples = d['samples']
            reliability_penalty = (100 - d['success_rate']) * 0.6 if samples >= 5 else 0
            latency_penalty = min((d['avg_latency_ms'] or 0) / 1000, 15)
            preferred_bonus = -50 if provider['id'] == preferred else 0
            recovery_penalty = 30 if d['state'] == 'recovering' else 0
            return (int(unavailable), provider['priority'] * 3 + reliability_penalty + latency_penalty + preferred_bonus + recovery_penalty)
        return sorted(providers, key=score)

    def acquire(self, provider_id, model):
        """Return (allowed, is_half_open). Lease ensures one recovery probe at a time."""
        now = self.clock()
        row = self.db.one('SELECT suspended_until,probe_started_at FROM provider_health WHERE provider_id=? AND model=?', (provider_id, model))
        if not row or not row['suspended_until']:
            return True, False
        if row['suspended_until'] > now:
            return False, False
        # Atomic compare-and-set under DB's connection lock, safe for parallel jobs.
        changed = self.db.execute('''UPDATE provider_health SET probe_started_at=?
          WHERE provider_id=? AND model=? AND suspended_until <= ?
          AND (probe_started_at IS NULL OR probe_started_at <= ?)''',
          (now, provider_id, model, now, now - 120))
        return bool(changed), bool(changed)

    def release_probe(self, provider_id, model):
        self.db.execute('UPDATE provider_health SET probe_started_at=NULL WHERE provider_id=? AND model=?', (provider_id, model))

    def record(self, provider_id, model, *, success, latency_ms, error=None, run_id=None, step_id=None):
        """Record each completed real attempt and update persistent breaker state."""
        with self.db.lock:
            return self._record(provider_id, model, success=success, latency_ms=latency_ms,
                                error=error, run_id=run_id, step_id=step_id)

    def _record(self, provider_id, model, *, success, latency_ms, error=None, run_id=None, step_id=None):
        now = self.clock()
        category = getattr(error, 'category', 'internal') if error else None
        http_status = getattr(error, 'http_status', None) if error else None
        row = self.db.one('SELECT * FROM provider_health WHERE provider_id=? AND model=?', (provider_id, model)) or {}
        consecutive = 0 if success else row.get('consecutive_failures', 0) + 1
        previous_until = row.get('suspended_until')
        was_probe = previous_until is not None and previous_until <= now
        open_breaker = bool(not success and category in TRANSIENT and
                            (category == 'rate_limit' or consecutive >= 2 or was_probe))
        open_count = 0 if success else row.get('open_count', 0)
        until = None if success else previous_until
        if open_breaker:
            open_count += 1
            base = 120 if category == 'rate_limit' else 60
            until = now + min(1800, base * (2 ** min(open_count - 1, 5)))
        elif until is not None and until <= now:
            until = None
        self.db.execute('''INSERT INTO provider_attempts
          (provider_id,model,success,category,http_status,latency_ms,run_id,step_id,created_at)
          VALUES(?,?,?,?,?,?,?,?,?)''',
          (provider_id, model, int(success), category, http_status, max(0, int(latency_ms)), run_id, step_id, timestamp()))
        self.db.execute('''INSERT INTO provider_health
          (provider_id,model,consecutive_failures,open_count,suspended_until,probe_started_at,
           last_error_category,last_http_status,last_checked_at)
          VALUES(?,?,?,?,?,NULL,?,?,?)
          ON CONFLICT(provider_id,model) DO UPDATE SET
           consecutive_failures=excluded.consecutive_failures,
           open_count=excluded.open_count,suspended_until=excluded.suspended_until,
           probe_started_at=NULL,last_error_category=excluded.last_error_category,
           last_http_status=excluded.last_http_status,last_checked_at=excluded.last_checked_at''',
          (provider_id, model, consecutive, open_count, until, category, http_status, timestamp()))
        return {
            'opened': open_breaker,
            'recovered': bool(success and previous_until is not None),
            'until': until if open_breaker else None,
        }

    def attempts(self, provider_id, model, limit=30):
        return self.db.all('''SELECT success,category,http_status,latency_ms,created_at
            FROM provider_attempts WHERE provider_id=? AND model=? ORDER BY id DESC LIMIT ?''',
            (provider_id, model, min(max(int(limit), 1), 100)))
