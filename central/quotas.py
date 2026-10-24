"""Server-controlled personal account quotas (not organization multi-tenancy).

Usage limits are conservative operational guards. Provider token charges may
differ from local estimates; these do not guarantee a billing ceiling.
"""
import os
from datetime import datetime, timedelta, timezone


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


def require_capacity(db, user_id):
    configured = limits()
    used = usage(db,user_id)
    if used['runs_last_24h'] >= configured['runs_per_24h']:
        raise ValueError(
            'Cota diária de tarefas atingida nesta conta. '
            'Tente novamente após a janela de 24 horas.')
    if used['active_runs'] >= configured['active_runs']:
        raise ValueError(
            'Limite de tarefas simultâneas atingido. Aguarde ou pare uma tarefa.')
    return configured
