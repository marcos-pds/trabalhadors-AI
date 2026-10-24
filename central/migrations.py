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
