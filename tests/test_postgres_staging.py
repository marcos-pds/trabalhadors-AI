"""Migration rehearsal with real PostgreSQL and a disposable SQLite source.

Only `central_staging` tables are touched. Never use a production DSN:
this fixture deletes prior staging snapshots, including copied metadata.
"""
import json
import os
import pytest

from central.database import Database, utcnow
from central.postgres_queue import connect
from central import postgres_staging as staging

DSN = os.environ.get("CENTRAL_PG_TEST_DSN")


@pytest.fixture()
def source(tmp_path):
    path = tmp_path / "central.sqlite3"
    db = Database(path)
    for who in ("u1", "u2"):
        db.execute("INSERT INTO users VALUES(?,?,?,?)",
                   (who, who + "@example.test", "TOP_SECRET_PASSWORD_HASH", utcnow()))
    db.execute(
        "INSERT INTO projects(id,user_id,name,description,created_at)"
        " VALUES(?,?,?,?,?)",
        ("p1", "u1", "Project of first user", "Private project notes", utcnow()),
    )
    db.execute(
        "INSERT INTO conversations(id,user_id,title,project_id,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?)",
        ("c1", "u1", "Private conversation title", "p1", utcnow(), utcnow()),
    )
    db.execute(
        "INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,"
        "agent_ids,plan,output,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("r1", "u1", "c1", "TOP_SECRET_PROMPT", "completed", "auto",
         "[]", "[]", "TOP_SECRET_OUTPUT", utcnow(), utcnow()),
    )
    try:
        yield db, path
    finally:
        db.close()


@pytest.fixture()
def pg():
    if not DSN:
        pytest.skip("Disposable CENTRAL_PG_TEST_DSN is required")
    conn = connect(DSN)
    staging.install_staging_schema(conn)
    # Safe only in CI/disposable database: previous experimental metadata is
    # deliberately cleared to isolate tests.
    conn.execute("DELETE FROM central_staging.snapshots")
    try:
        yield conn
    finally:
        conn.execute("DELETE FROM central_staging.snapshots")
        conn.close()


def test_sqlite_dry_run_requires_no_postgres_and_never_leaks_secrets(source):
    db, path = source
    report = staging.inspect_source(path)
    assert report["stageable"]
    assert report["counts"] == {
        "users": 2, "projects": 1, "conversations": 1, "runs": 1,
    }
    assert "TOP_SECRET_" not in json.dumps(report)
    assert "@" not in json.dumps(report)
    assert db.one("SELECT prompt FROM runs WHERE id='r1'")["prompt"] == "TOP_SECRET_PROMPT"


def test_stage_is_atomic_verified_and_discardable(pg, source):
    db, path = source
    batch = staging.stage_metadata(pg, path)
    assert batch["verified"]
    assert batch["counts"]["runs"] == 1
    verified = staging.verify_staged(pg, batch["batch_id"], source_path=path)
    assert verified["verified"] and verified["source_unchanged"]
    assert verified["counts"] == batch["counts"]
    columns = {r[0] for r in pg.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='central_staging' AND table_name='runs'"
    )}
    assert not {"prompt", "output", "agent_ids", "plan", "api_key_enc"} & columns
    assert "password_hash" not in {r[0] for r in pg.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='central_staging' AND table_name='users'"
    )}
    assert pg.execute("SELECT COUNT(*) FROM central_staging.runs").fetchone()[0] == 1
    # Refuse accidental second staging while a prior copy is retained.
    with pytest.raises(RuntimeError, match="already contains"):
        staging.stage_metadata(pg, path)
    with pytest.raises(PermissionError):
        staging.discard_staged(pg, batch["batch_id"], confirmation="no")
    assert staging.verify_staged(pg, batch["batch_id"])["verified"]
    assert staging.discard_staged(
        pg, batch["batch_id"], confirmation="DISCARD-STAGING")["discarded"]
    assert pg.execute("SELECT COUNT(*) FROM central_staging.runs").fetchone()[0] == 0
    with pytest.raises(ValueError, match="does not exist"):
        staging.verify_staged(pg, batch["batch_id"])
    # Staging never modified the local SQLite source.
    assert db.one("SELECT output FROM runs WHERE id='r1'")["output"] == "TOP_SECRET_OUTPUT"


def test_verify_detects_modified_pg_data_and_changed_sqlite_source(pg, source):
    db, path = source
    batch = staging.stage_metadata(pg, path)
    batch_id = batch["batch_id"]
    pg.execute(
        "UPDATE central_staging.projects SET name='tampered' WHERE batch_id=%s",
        (batch_id,),
    )
    assert staging.verify_staged(pg, batch_id)["verified"] is False
    pg.execute(
        "UPDATE central_staging.projects SET name='Project of first user' "
        "WHERE batch_id=%s", (batch_id,),
    )
    assert staging.verify_staged(pg, batch_id)["verified"] is True
    db.execute("UPDATE projects SET name='source changed' WHERE id='p1'")
    result = staging.verify_staged(pg, batch_id, source_path=path)
    assert result["verified"] and result["source_unchanged"] is False


def test_cross_tenant_source_is_rejected_without_postgres_write(pg, source):
    db, path = source
    db.execute(
        "INSERT INTO conversations(id,user_id,title,project_id,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?)",
        ("cross-tenant", "u2", "Wrong project", "p1", utcnow(), utcnow()),
    )
    with pytest.raises(ValueError, match="ownership"):
        staging.stage_metadata(pg, path)
    assert pg.execute(
        "SELECT COUNT(*) FROM central_staging.snapshots"
    ).fetchone()[0] == 0


def test_target_insert_failure_rolls_back_every_staged_row(pg, source, monkeypatch):
    _, path = source
    before = staging._read_target

    def fail_validation(conn, batch_id):
        rows = before(conn, batch_id)
        rows["runs"] = []
        return rows

    monkeypatch.setattr(staging, "_read_target", fail_validation)
    with pytest.raises(RuntimeError, match="verification failed"):
        staging.stage_metadata(pg, path)
    assert pg.execute(
        "SELECT COUNT(*) FROM central_staging.snapshots"
    ).fetchone()[0] == 0
    for name in staging.TABLES:
        assert pg.execute(
            "SELECT COUNT(*) FROM central_staging." + name
        ).fetchone()[0] == 0


def test_metadata_snapshot_enforces_row_limit_and_schema_checksum(pg, source):
    _, path = source
    with pytest.raises(ValueError, match="row limit"):
        staging.inspect_source(path, max_rows=1)
    assert staging.install_staging_schema(pg) == 1
    with pytest.raises(RuntimeError, match="checksum"):
        with pg.transaction():
            pg.execute(
                "UPDATE central_staging.schema_migrations SET checksum='bad' "
                "WHERE version=1"
            )
            staging.install_staging_schema(pg)
    assert staging.install_staging_schema(pg) == 1


def test_metadata_stage_rejects_invalid_batch_or_missing_confirmation(pg, source):
    _, path = source
    batch = staging.stage_metadata(pg, path)
    with pytest.raises(ValueError, match="batch ID"):
        staging.verify_staged(pg, "';DROP TABLE users")
    with pytest.raises(ValueError, match="batch ID"):
        staging.discard_staged(pg, "not-a-batch", confirmation="DISCARD-STAGING")
    assert staging.verify_staged(pg, batch["batch_id"])["verified"]


def test_cli_inspect_does_not_require_pg_credentials(source, capsys, monkeypatch):
    _, path = source
    monkeypatch.delenv("CENTRAL_PG_MIGRATION_DSN", raising=False)
    assert staging.main(["inspect", str(path)]) == 0
    text = capsys.readouterr().out
    assert "TOP_SECRET_" not in text
    assert "metadata_only_no_secrets" in text
    with pytest.raises(SystemExit):
        staging.main(["stage", str(path)])


def test_utf8_id_order_does_not_depend_on_database_collation(pg, source):
    db, path = source
    for project_id in ("Z-upper", "a-lower", "Á-accent", "A-upper"):
        db.execute(
            "INSERT INTO projects(id,user_id,name,description,created_at)"
            " VALUES(?,?,?,?,?)",
            (project_id, "u1", project_id, "Unicode test metadata", utcnow()),
        )
    staged = staging.stage_metadata(pg, path)
    assert staged["counts"]["projects"] == 5
    assert staging.verify_staged(pg, staged["batch_id"], source_path=path)[
        "source_unchanged"
    ]
