"""Regression: new features must have additive checked migrations in fresh DBs.

No migration is applied out-of-band, and old migrations keep immutable checksums.
"""
import pytest
from central.database import Database
from central.migrations import MIGRATIONS


def test_resource_worker_and_isolation_tables_are_created_by_database(tmp_path):
    db = Database(tmp_path / "migration-check.sqlite3")
    try:
        expected = ("resource_revisions", "worker_controls",
                    "isolated_workspace_runs", "isolated_workspace_steps")
        for table in expected:
            record = db.one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,))
            assert record is not None, table
        versions = [row['version'] for row in db.all(
            "SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == list(range(1, 23))
        assert db.one("PRAGMA integrity_check")['integrity_check'] == "ok"
    finally:
        db.close()


def test_migrations_are_idempotent_across_restarts(tmp_path):
    path = tmp_path / "migration-check.sqlite3"
    db = Database(path)
    first = db.all("SELECT version,checksum FROM schema_migrations ORDER BY version")
    db.close()
    again = Database(path)
    try:
        assert first == again.all("SELECT version,checksum FROM schema_migrations ORDER BY version")
        assert len(first) == len(MIGRATIONS)
    finally:
        again.close()


def test_legacy_unassigned_step_only_allowed_at_internal_control_boundary(tmp_path):
    from central.database import utcnow
    from central.worker_controls import check_control, request_control
    from fastapi import HTTPException
    db = Database(tmp_path / "legacy.sqlite3")
    try:
        now = utcnow()
        db.execute("INSERT INTO users VALUES(?,?,?,?)", ("u", "u@example.invalid", "hash", now))
        db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?)",
                   ("c", "u", "Tests", None, now, now))
        db.execute(
            "INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("r", "u", "c", "Test", "running", "manual", "[]", "[]", now, now))
        db.execute("INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?)",
                   ("s", "r", None, "agent", "Legacy", "[]", "running", now, now))
        assert check_control(db, "u", "r", "s") is None
        with pytest.raises(HTTPException) as error:
            request_control(db, "u", "r", "s", "pause")
        assert error.value.status_code == 404
        with pytest.raises(HTTPException):
            check_control(db, "foreign", "r", "s")
    finally:
        db.close()
