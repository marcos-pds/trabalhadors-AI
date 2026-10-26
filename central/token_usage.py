"""Per-generation token usage capture, scoped to the active async task."""
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from math import ceil

usage_callback = ContextVar('token_usage_callback', default=None)


def set_usage_callback(callback):
    return usage_callback.set(callback)


def reset_usage_callback(token):
    usage_callback.reset(token)


def report_usage(input_tokens, output_tokens, source):
    callback = usage_callback.get()
    if callback is not None:
        callback({
            'input_tokens': max(0, int(input_tokens)),
            'output_tokens': max(0, int(output_tokens)),
            'source': source,
        })


def estimate_tokens(text):
    return ceil(len(text or '') / 4)


def token_usage_schema():
    return (
        "CREATE TABLE token_usage("
        "id TEXT PRIMARY KEY,"
        "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,"
        "step_id TEXT REFERENCES steps(id) ON DELETE SET NULL,"
        "agent_name TEXT NOT NULL,provider_name TEXT NOT NULL,model TEXT NOT NULL,"
        "input_tokens INTEGER NOT NULL CHECK(input_tokens>=0),"
        "output_tokens INTEGER NOT NULL CHECK(output_tokens>=0),"
        "source TEXT NOT NULL CHECK(source IN ('actual','estimated')),"
        "created_at TEXT NOT NULL)",
        'CREATE INDEX token_usage_user_time ON token_usage(user_id,created_at)',
        'CREATE INDEX token_usage_run ON token_usage(run_id)',
    )


def run_usage(db, user_id, run_id):
    rows = db.all(
        '''SELECT agent_name,provider_name,model,input_tokens,output_tokens,source,created_at
           FROM token_usage WHERE user_id=? AND run_id=? ORDER BY created_at,id''',
        (user_id, run_id))
    actual = [row for row in rows if row['source'] == 'actual']
    estimated = [row for row in rows if row['source'] == 'estimated']
    input_tokens = sum(row['input_tokens'] for row in rows)
    output_tokens = sum(row['output_tokens'] for row in rows)
    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': input_tokens + output_tokens,
        'actual_tokens': sum(row['input_tokens'] + row['output_tokens'] for row in actual),
        'estimated_tokens': sum(row['input_tokens'] + row['output_tokens'] for row in estimated),
        'generation_count': len(rows),
        'generations': rows,
        'balance_available': False,
    }


def usage_overview(db, user_id, days=30):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    totals = db.one(
        '''SELECT COUNT(*) AS generations,
                  COALESCE(SUM(input_tokens),0) AS input_tokens,
                  COALESCE(SUM(output_tokens),0) AS output_tokens,
                  COALESCE(SUM(CASE WHEN source='actual' THEN input_tokens+output_tokens ELSE 0 END),0)
                    AS actual_tokens,
                  COALESCE(SUM(CASE WHEN source='estimated' THEN input_tokens+output_tokens ELSE 0 END),0)
                    AS estimated_tokens
           FROM token_usage WHERE user_id=? AND created_at>=?''',
        (user_id, since))
    providers = db.all(
        '''SELECT provider_name,model,COUNT(*) AS generations,
                  SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,
                  SUM(CASE WHEN source='actual' THEN input_tokens+output_tokens ELSE 0 END)
                    AS actual_tokens,
                  SUM(CASE WHEN source='estimated' THEN input_tokens+output_tokens ELSE 0 END)
                    AS estimated_tokens
           FROM token_usage WHERE user_id=? AND created_at>=?
           GROUP BY provider_name,model ORDER BY input_tokens+output_tokens DESC''',
        (user_id, since))
    daily = db.all(
        '''SELECT substr(created_at,1,10) AS date,
                  SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens
           FROM token_usage WHERE user_id=? AND created_at>=?
           GROUP BY substr(created_at,1,10) ORDER BY date''',
        (user_id, since))
    recent = db.all(
        '''SELECT r.id AS run_id,substr(r.prompt,1,180) AS prompt,r.status,r.created_at,
                  COUNT(t.id) AS generations,
                  COALESCE(SUM(t.input_tokens),0) AS input_tokens,
                  COALESCE(SUM(t.output_tokens),0) AS output_tokens,
                  COALESCE(SUM(CASE WHEN t.source='actual'
                                    THEN t.input_tokens+t.output_tokens ELSE 0 END),0) AS actual_tokens,
                  COALESCE(SUM(CASE WHEN t.source='estimated'
                                    THEN t.input_tokens+t.output_tokens ELSE 0 END),0) AS estimated_tokens
           FROM runs r LEFT JOIN token_usage t ON t.run_id=r.id
           WHERE r.user_id=? AND r.created_at>=? AND t.id IS NOT NULL
           GROUP BY r.id ORDER BY r.created_at DESC LIMIT 30''',
        (user_id, since))
    return {
        'days': days,
        'totals': dict(totals, total_tokens=totals['input_tokens'] + totals['output_tokens']),
        'providers': providers,
        'daily': daily,
        'recent_runs': recent,
        'balance_available': False,
        'balance_message': 'Saldo e cota restante dependem do provedor e não são disponibilizados por uma API comum. Consulte o painel da conta do provedor.',
    }
