"""User-scoped operational analytics and audit without exposing secrets."""
from datetime import datetime, timedelta, timezone
from .database import utcnow
from .observability import request_context, log_event


def audit(db, user_id, action, target_type, target_id=None, outcome='accepted'):
    # The audit record contains stable IDs and enum-like actions, no prompts,
    # file paths, command contents, keys or arbitrary provider error text.
    db.execute(
        'INSERT INTO ops_audit(user_id,action,outcome,target_type,target_id,'
        'request_id,created_at) VALUES(?,?,?,?,?,?,?)',
        (user_id, action, outcome, target_type, target_id,
         request_context.get(), utcnow()))
    log_event('audit', outcome=outcome, category=action,
              run_id=target_id if target_type == 'run' else None)


def audit_history(db, user_id, limit=50):
    return db.all(
        'SELECT id,action,outcome,target_type,target_id,request_id,created_at '
        'FROM ops_audit WHERE user_id=? ORDER BY id DESC LIMIT ?',
        (user_id, min(max(int(limit), 1), 100)))


def overview(db, user_id):
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    counts = db.all(
        'SELECT status, COUNT(*) AS n FROM runs WHERE user_id=? GROUP BY status',
        (user_id,))
    statuses = {row['status']: row['n'] for row in counts}
    recent = db.one(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                  SUM(CASE WHEN status='paused_limit' THEN 1 ELSE 0 END) AS paused,
                  COALESCE(SUM(total_cost),0) AS estimated_cost
           FROM runs WHERE user_id=? AND created_at>=?""",
        (user_id, since))
    durations = db.one(
        """SELECT AVG((julianday(updated_at)-julianday(created_at))*86400000)
                  AS average_ms
           FROM runs WHERE user_id=? AND status IN ('completed','failed','cancelled')
           AND created_at>=?""", (user_id, since))
    provider_rows = db.all(
        """SELECT p.id AS provider_id,p.name,p.model,p.enabled,
                  COUNT(a.id) AS attempts,
                  COALESCE(SUM(CASE WHEN a.success=1 THEN 1 ELSE 0 END),0)
                    AS successes,
                  ROUND(AVG(a.latency_ms),1) AS avg_latency_ms
           FROM providers p LEFT JOIN provider_attempts a
             ON a.provider_id=p.id AND a.created_at>=?
           WHERE p.user_id=?
           GROUP BY p.id,p.name,p.model,p.enabled
           ORDER BY attempts DESC,p.name LIMIT 60""",
        (since, user_id))
    provider_failures = db.all(
        """SELECT p.id AS provider_id,a.category,COUNT(*) AS n
           FROM provider_attempts a JOIN providers p ON a.provider_id=p.id
           WHERE p.user_id=? AND a.created_at>=? AND a.success=0
           GROUP BY p.id,a.category ORDER BY n DESC LIMIT 30""",
        (user_id, since))
    provider_health = db.all(
        """SELECT p.id, p.name, h.model, h.consecutive_failures,
                  h.suspended_until, h.last_error_category
           FROM providers p JOIN provider_health h ON h.provider_id=p.id
           WHERE p.user_id=? AND p.enabled=1
                 AND (h.consecutive_failures>=2 OR h.suspended_until IS NOT NULL)
           LIMIT 25""",
        (user_id,))
    steps = db.one(
        """SELECT COUNT(*) AS attempts
           FROM steps WHERE run_id IN
             (SELECT id FROM runs WHERE user_id=? AND created_at>=?)""",
        (user_id,since))
    alerts = []
    if int(recent['failed'] or 0) >= 3:
        alerts.append({'code':'frequent_run_failures','severity':'warning',
                       'message':'Três ou mais tarefas falharam nas últimas 24 horas.',
                       'count':int(recent['failed'])})
    if int(statuses.get('paused_limit', 0)):
        alerts.append({'code':'paused_runs','severity':'info',
                       'message':'Existem tarefas pausadas por limite aguardando continuação.',
                       'count':int(statuses['paused_limit'])})
    for p in provider_health:
        alerts.append({'code':'provider_degraded','severity':'warning',
                       'provider_id':p['id'], 'provider_name':p['name'],
                       'message':'Provedor com falhas consecutivas ou recuperação pendente.',
                       'count':int(p['consecutive_failures'] or 0)})
    return {
        'period_hours':24,
        'run_statuses':statuses,
        'last_24h':{
            'total':int(recent['total'] or 0),
            'completed':int(recent['completed'] or 0),
            'failed':int(recent['failed'] or 0),
            'paused':int(recent['paused'] or 0),
            'estimated_cost_usd':round(float(recent['estimated_cost'] or 0),6),
            'mean_terminal_duration_ms':round(max(0,float(durations['average_ms'])),1)
                if durations['average_ms'] is not None else None,
            'step_attempts':int(steps['attempts'] or 0)},
        'providers':[dict(p,success_rate=round(100*p['successes']/p['attempts'],1)
                           if p['attempts'] else None) for p in provider_rows],
        'provider_failure_categories':provider_failures,
        'alerts':alerts[:30],
        'cost_notice':'Custos estimados a partir de preços cadastrados, não fatura real.',
    }
