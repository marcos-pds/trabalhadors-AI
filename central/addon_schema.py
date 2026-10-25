"""Data only: imported resources never register executable tools."""
SCHEMA = (
    """CREATE TABLE ai_resources(
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        organization_id TEXT REFERENCES organizations(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ('skill','vsix','mcp')),
        metadata_json TEXT NOT NULL, payload_enc TEXT NOT NULL,
        sha256 TEXT NOT NULL, origin TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('inactive','active','revoked')),
        byte_size INTEGER NOT NULL, created_at TEXT NOT NULL
    )""",
    """CREATE TABLE skill_bindings(
        resource_id TEXT NOT NULL REFERENCES ai_resources(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        target_kind TEXT NOT NULL CHECK(target_kind IN ('agent','project','run')),
        target_id TEXT NOT NULL,
        PRIMARY KEY(resource_id,user_id,target_kind,target_id)
    )""",
    'CREATE INDEX skill_bindings_target ON skill_bindings(user_id,target_kind,target_id)',
)
