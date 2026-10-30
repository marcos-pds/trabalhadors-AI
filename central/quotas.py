"""Server-controlled personal account quotas (not organization multi-tenancy).

Usage limits are conservative operational guards. Provider token charges may
differ from local estimates; these do not guarantee a billing ceiling.
"""
import os
from datetime import datetime, timedelta, timezone


class QuotaExceeded(ValueError):
    """Operational account capacity exhausted (HTTP 429)."""


def _limit(name, default):
    try:
        return max(1, min(100000, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def limits():
    return {
        'runs_per_24h': _limit('CENTRAL_MAX_RUNS_PER_DAY', 100),
        'active_runs': _limit('CENTRAL_MAX_ACTIVE_RUNS', 4),
    }


def usage(db, user_id):
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return {
        'runs_last_24h': db.one(
            'SELECT COUNT(*) AS n FROM runs WHERE user_id=? AND created_at>=?',
            (user_id,since))['n'],
        'active_runs': db.one(
            """SELECT COUNT(*) AS n FROM runs WHERE user_id=?
               AND status IN ('queued','running','awaiting_approval')""",
            (user_id,))['n'],
    }


def require_capacity(db, user_id, organization_id=None):
    configured = limits()
    used = usage(db,user_id)
    if used['runs_last_24h'] >= configured['runs_per_24h']:
        raise QuotaExceeded(
            'Cota diária de tarefas atingida nesta conta. '
            'Tente novamente após a janela de 24 horas.')
    if used['active_runs'] >= configured['active_runs']:
        raise QuotaExceeded(
            'Limite de tarefas simultâneas atingido. Aguarde ou pare uma tarefa.')
    if organization_id:
        from .organizations import require_org
        org = require_org(db,organization_id,user_id,write=True)
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        scoped = db.one(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(CASE WHEN r.status IN
                       ('queued','running','awaiting_approval') THEN 1 ELSE 0 END),0)
                        AS active
               FROM organization_runs x JOIN runs r ON r.id=x.run_id
               WHERE x.organization_id=? AND r.created_at>=?""",
            (organization_id,since))
        active = db.one(
            """SELECT COUNT(*) AS n FROM organization_runs x
               JOIN runs r ON r.id=x.run_id WHERE x.organization_id=?
               AND r.status IN ('queued','running','awaiting_approval')""",
            (organization_id,))['n']
        if scoped['total'] >= org['daily_run_limit']:
            raise QuotaExceeded('Cota diária da organização atingida.')
        if active >= org['active_run_limit']:
            raise QuotaExceeded('Limite de execuções simultâneas da organização atingido.')
        if org['estimated_budget_usd'] is not None:
            spent = db.one(
                """SELECT COALESCE(SUM(r.total_cost),0) AS cost
                   FROM organization_runs x JOIN runs r ON r.id=x.run_id
                   WHERE x.organization_id=?""",
                (organization_id,))['cost']
            if spent >= org['estimated_budget_usd']:
                raise QuotaExceeded('Limite de orçamento estimado da organização atingido.')
    return configured
