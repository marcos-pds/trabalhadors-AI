"""Additive durable Motion Studio queue schema."""
SCHEMA = (
    "CREATE TABLE motion_runs(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),"
    "request_id TEXT NOT NULL,root TEXT NOT NULL,grant_root TEXT NOT NULL,manifest TEXT NOT NULL,"
    "digest TEXT NOT NULL,inputs TEXT NOT NULL,state TEXT NOT NULL,"
    "cancel_requested INTEGER NOT NULL DEFAULT 0,lease_owner TEXT,heartbeat REAL,"
    "error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(user_id,request_id))",
    "CREATE TABLE motion_jobs(run_id TEXT NOT NULL REFERENCES motion_runs(id) ON DELETE CASCADE,"
    "id TEXT NOT NULL,adapter TEXT NOT NULL,state TEXT NOT NULL,artifact TEXT,error TEXT,"
    "started_at TEXT,finished_at TEXT,PRIMARY KEY(run_id,id))",
    "CREATE INDEX motion_queue_state ON motion_runs(state,created_at)",
)

SETTINGS_SCHEMA = (
    "CREATE TABLE motion_tool_settings(user_id TEXT PRIMARY KEY REFERENCES users(id),config TEXT NOT NULL,updated_at TEXT NOT NULL)",
    "ALTER TABLE motion_runs ADD COLUMN runtimes TEXT NOT NULL DEFAULT '{}'",
)
