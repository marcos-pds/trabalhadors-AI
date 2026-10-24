import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS providers (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, kind TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL,
 api_key_enc TEXT, priority INTEGER NOT NULL DEFAULT 5, enabled INTEGER NOT NULL DEFAULT 1,
 input_price REAL, output_price REAL, last_error TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_user ON providers(user_id);
CREATE TABLE IF NOT EXISTS provider_health (
 provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
 model TEXT NOT NULL, consecutive_failures INTEGER NOT NULL DEFAULT 0,
 open_count INTEGER NOT NULL DEFAULT 0, suspended_until REAL, probe_started_at REAL,
 last_error_category TEXT, last_http_status INTEGER, last_checked_at TEXT,
 PRIMARY KEY(provider_id,model)
);
CREATE TABLE IF NOT EXISTS provider_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
 model TEXT NOT NULL, success INTEGER NOT NULL, category TEXT, http_status INTEGER,
 latency_ms INTEGER NOT NULL, run_id TEXT, step_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_attempts ON provider_attempts(provider_id,model,id DESC);
CREATE TABLE IF NOT EXISTS agents (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, specialty TEXT NOT NULL, instructions TEXT NOT NULL,
 provider_id TEXT, model TEXT, avatar TEXT NOT NULL DEFAULT '✦', enabled INTEGER NOT NULL DEFAULT 1,
 max_concurrency INTEGER NOT NULL DEFAULT 2, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, project_id TEXT REFERENCES projects(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL, role TEXT NOT NULL, agent_name TEXT, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_convo ON messages(conversation_id,created_at);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 conversation_id TEXT NOT NULL REFERENCES conversations(id), prompt TEXT NOT NULL,
 status TEXT NOT NULL, mode TEXT NOT NULL, agent_ids TEXT NOT NULL, plan TEXT NOT NULL,
 output TEXT, error TEXT, total_cost REAL NOT NULL DEFAULT 0,
 budget_limit REAL, idempotency_key TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(user_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS steps (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 agent_id TEXT, kind TEXT NOT NULL DEFAULT 'agent', name TEXT NOT NULL, deps TEXT NOT NULL,
 instructions TEXT, status TEXT NOT NULL, output TEXT, provider_id TEXT, model TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id);
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 event TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id,seq);
CREATE TABLE IF NOT EXISTS computer_access_settings (
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 mode TEXT NOT NULL DEFAULT 'blocked' CHECK(mode IN ('blocked','ask','full')),
 folder TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS computer_access_approvals (
 id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 action TEXT NOT NULL, relative_path TEXT NOT NULL,
 folder TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 expires_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_computer_access_approvals_user
 ON computer_access_approvals(user_id,status,created_at);
CREATE TABLE IF NOT EXISTS workflows (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', definition TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            # Idempotent migration for databases created before project memory existed.
            cols = {row['name'] for row in self.conn.execute('PRAGMA table_info(projects)')}
            if 'memory_notes' not in cols:
                self.conn.execute("ALTER TABLE projects ADD COLUMN memory_notes TEXT NOT NULL DEFAULT ''")
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(user_id,project_id,updated_at)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id,conversation_id)')

    def execute(self, query, args=()):
        with self.lock:
            cur = self.conn.execute(query, args)
            return cur.rowcount

    def one(self, query, args=()):
        with self.lock:
            row = self.conn.execute(query, args).fetchone()
            return dict(row) if row else None

    def all(self, query, args=()):
        with self.lock:
            return [dict(x) for x in self.conn.execute(query, args).fetchall()]

    def event(self, run_id, kind, payload):
        with self.lock:
            cur = self.conn.execute(
                'INSERT INTO events(run_id,event,payload,created_at) VALUES(?,?,?,?)',
                (run_id, kind, json.dumps(payload, ensure_ascii=False), utcnow())
            )
            return cur.lastrowid

    def close(self):
        self.conn.close()
