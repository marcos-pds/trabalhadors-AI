"""Conservative process-liveness metrics for workers sharing one SQLite file.

Liveness signals are informational: they do NOT grant leases or prove
readiness of remote infrastructure. SQLite storage is not shared across hosts.
"""
from datetime import datetime, timedelta, timezone
from .database import utcnow


def beat(db, worker_id, mode, active_jobs=0):
    if mode not in ('worker', 'embedded'):
        raise ValueError('Worker mode must be worker or embedded')
    if not isinstance(worker_id,str) or not 1<=len(worker_id)<=100:
        raise ValueError('Invalid worker ID')
    if type(active_jobs) is not int or not 0<=active_jobs<=100:
        raise ValueError('Active jobs must be 0..100')
    stamp=utcnow()
    db.execute(
        """INSERT INTO worker_liveness(worker_id,mode,started_at,last_seen_at,active_jobs)
           VALUES(?,?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET
           last_seen_at=excluded.last_seen_at,
           active_jobs=excluded.active_jobs""",
        (worker_id,mode,stamp,stamp,active_jobs))


def forget(db, worker_id):
    db.execute('DELETE FROM worker_liveness WHERE worker_id=?', (worker_id,))


def snapshot(db, max_age_seconds=20):
    """Only aggregate metrics, never list worker IDs to ordinary users."""
    if type(max_age_seconds) is not int or not 5<=max_age_seconds<=300:
        raise ValueError('Invalid liveness window')
    threshold=(datetime.now(timezone.utc)
               -timedelta(seconds=max_age_seconds)).isoformat()
    live=db.one(
        """SELECT COUNT(*) AS n,COALESCE(SUM(active_jobs),0) AS active_jobs
           FROM worker_liveness WHERE last_seen_at>=?""",
        (threshold,))
    stale=db.one(
        'SELECT COUNT(*) AS n FROM worker_liveness WHERE last_seen_at<?',
        (threshold,))
    return {
        'active_workers':int(live['n']),
        'active_jobs_reported':int(live['active_jobs']),
        'stale_workers':int(stale['n']),
        'liveness_window_seconds':max_age_seconds,
        'scope':'shared_sqlite_file',
        'distributed':False,
    }


def cleanup_stale(db, stale_hours=24):
    """Clean only older information; never change business runs or leases."""
    if type(stale_hours) is not int or not 1<=stale_hours<=168:
        raise ValueError('Invalid worker retention')
    threshold=(datetime.now(timezone.utc)-timedelta(hours=stale_hours)).isoformat()
    return db.execute('DELETE FROM worker_liveness WHERE last_seen_at<?', (threshold,))
