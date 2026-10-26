"""Checksummed, ordered SQLite migrations after legacy schema bootstrap.

The current application intentionally rejects non-SQLite URLs: this migration
ledger is not a PostgreSQL adapter or a distributed queue implementation.
"""
import hashlib
from .database import utcnow
from .semantic_memory import SCHEMA as MEMORY_SCHEMA
from .invitations import SCHEMA as INVITATIONS_SCHEMA
from .git_integrations import SCHEMA as GIT_SCHEMA
from .knowledge import SCHEMA as KNOWLEDGE_SCHEMA
from .git_change_plans import SCHEMA as GIT_PLAN_SCHEMA
from .addon_schema import SCHEMA as ADDON_SCHEMA
from .token_usage import token_usage_schema

MIGRATIONS = (
    (1, 'retrieval_and_operations_indexes', (
        'CREATE INDEX IF NOT EXISTS idx_messages_retrieval ON messages(user_id,conversation_id,role)',
        'CREATE INDEX IF NOT EXISTS idx_provider_attempts_time ON provider_attempts(provider_id,created_at)',
        'CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id,seq)',
    )),
    (2, 'semantic_memory', tuple(part.strip() for part in MEMORY_SCHEMA.split(';') if part.strip())),
    (3, 'single_use_invitations', (INVITATIONS_SCHEMA,)),
    (4, 'personal_git_connections', (GIT_SCHEMA,)),
    (5, 'project_knowledge_documents', tuple(part.strip() for part in KNOWLEDGE_SCHEMA.split(';') if part.strip())),
    (6, 'approved_git_drafts', (GIT_PLAN_SCHEMA,)),
    (7, 'worker_liveness', (
        "CREATE TABLE IF NOT EXISTS worker_liveness("
        "worker_id TEXT PRIMARY KEY,mode TEXT NOT NULL CHECK(mode IN ('worker','embedded')),"
        "started_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,"
        "active_jobs INTEGER NOT NULL DEFAULT 0 CHECK(active_jobs>=0))",
        "CREATE INDEX IF NOT EXISTS idx_worker_liveness_seen ON worker_liveness(last_seen_at)",
    )),
    (8, 'job_queue_lease_token', (
        'ALTER TABLE job_queue ADD COLUMN lease_token TEXT',
    )),
    (9, 'inert_resources_and_skill_bindings', ADDON_SCHEMA),
    (10, 'resource_run_participation', (
        "CREATE TABLE resource_run_usage("
        "id TEXT PRIMARY KEY,resource_id TEXT REFERENCES ai_resources(id) ON DELETE SET NULL,"
        "run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,"
        "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,"
        "kind TEXT NOT NULL CHECK(kind IN ('skill','vsix','mcp')),"
        "sha256 TEXT NOT NULL,used_at TEXT NOT NULL,"
        "UNIQUE(resource_id,run_id,agent_id,sha256))",
        'CREATE INDEX resource_run_usage_owner_time ON resource_run_usage(user_id,used_at)',
    )),
    (11, 'vscode_install_history', (
        "CREATE TABLE vscode_install_events("
        "id TEXT PRIMARY KEY,resource_id TEXT REFERENCES ai_resources(id) ON DELETE SET NULL,"
        "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "target_id TEXT NOT NULL,extension_id TEXT NOT NULL,version TEXT NOT NULL,"
        "action TEXT NOT NULL CHECK(action IN ('installed','uninstalled')),"
        "result TEXT NOT NULL CHECK(result IN ('succeeded','failed')),created_at TEXT NOT NULL)",
        'CREATE INDEX vscode_install_events_user_time ON vscode_install_events(user_id,created_at)',
    )),
    (12, 'chatgpt_plan_provider', (
        "CREATE TABLE chatgpt_plan_connections(id TEXT PRIMARY KEY,user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,client_id TEXT NOT NULL,subject TEXT NOT NULL,email TEXT NOT NULL,scopes TEXT NOT NULL,credentials_enc TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
        "CREATE TABLE chatgpt_plan_pending(state_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,nonce TEXT NOT NULL,verifier TEXT NOT NULL,redirect_uri TEXT NOT NULL,client_id TEXT,expires_at TEXT NOT NULL)",
        "CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
        "ALTER TABLE providers ADD COLUMN chatgpt_connection_id TEXT REFERENCES chatgpt_plan_connections(id) ON DELETE SET NULL",
        "CREATE INDEX chatgpt_plan_provider_user ON providers(user_id,chatgpt_connection_id)",
    )),
    (13, 'token_usage_tracking', token_usage_schema()),
    (14, 'project_browser_session_mode', (
        "CREATE TABLE project_browser_settings("
        "project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,"
        "mode TEXT NOT NULL CHECK(mode IN ('run_isolated','project_persistent')),"
        "updated_at TEXT NOT NULL)",
    )),
)


def migrate(db):
    with db.lock:
        db.conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations('
                        'version INTEGER PRIMARY KEY,name TEXT NOT NULL,'
                        'checksum TEXT NOT NULL,applied_at TEXT NOT NULL)')
        known = {version for version, _, _ in MIGRATIONS}
        installed = db.all('SELECT version,checksum FROM schema_migrations ORDER BY version')
        if any(row['version'] not in known for row in installed):
            raise RuntimeError('Database schema is newer than this application')
        for version, name, statements in MIGRATIONS:
            checksum = hashlib.sha256('\n'.join(statements).encode()).hexdigest()
            row = db.one('SELECT checksum FROM schema_migrations WHERE version=?', (version,))
            if row:
                if row['checksum'] != checksum:
                    raise RuntimeError('Applied migration checksum mismatch')
                continue
            db.conn.execute('BEGIN IMMEDIATE')
            try:
                # Recheck after acquiring the cross-process write lock.
                row = db.one('SELECT checksum FROM schema_migrations WHERE version=?', (version,))
                if row and row['checksum'] != checksum:
                    raise RuntimeError('Applied migration checksum mismatch')
                if not row:
                    for sql in statements:
                        db.conn.execute(sql)
                    db.conn.execute('INSERT INTO schema_migrations VALUES(?,?,?,?)',
                                    (version, name, checksum, utcnow()))
                db.conn.execute('COMMIT')
            except BaseException:
                db.conn.execute('ROLLBACK')
                raise
