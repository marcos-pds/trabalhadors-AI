"""Opt-in metadata-only SQLite -> PostgreSQL staging rehearsal.

This is deliberately NOT a database cutover. Production API and workers
continue to use SQLite. No passwords, API keys, prompts, messages, workspace
paths, or execution output are copied. Staging is private and should use a
disposable PostgreSQL database with restricted access.

Source SQLite is opened read-only and backed up into a consistent in-memory
snapshot. PostgreSQL staging writes are atomic and reversible by batch ID.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .postgres_queue import connect, _check_connection

# Fixed, reviewed column allowlist; never SELECT * from private source tables.
COLUMNS = {
    "users": ("id", "created_at"),
    "projects": ("id", "user_id", "name", "description", "created_at"),
    "conversations": ("id", "user_id", "title", "project_id",
                      "created_at", "updated_at"),
    "runs": ("id", "user_id", "conversation_id", "status", "mode",
             "created_at", "updated_at"),
}
TABLES = tuple(COLUMNS)
LOCK_KEY = 718240922
MAX_ROWS = 25000

SCHEMA_SQL = (
    """CREATE TABLE central_staging.snapshots (
        batch_id TEXT PRIMARY KEY,
        row_counts TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
    )""",
    """CREATE TABLE central_staging.users (
        batch_id TEXT NOT NULL REFERENCES central_staging.snapshots(batch_id)
            ON DELETE CASCADE,
        id TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(batch_id,id)
    )""",
    """CREATE TABLE central_staging.projects (
        batch_id TEXT NOT NULL REFERENCES central_staging.snapshots(batch_id)
            ON DELETE CASCADE,
        id TEXT NOT NULL, user_id TEXT NOT NULL,
        name TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(batch_id,id), UNIQUE(batch_id,id,user_id),
        FOREIGN KEY(batch_id,user_id)
            REFERENCES central_staging.users(batch_id,id)
    )""",
    """CREATE TABLE central_staging.conversations (
        batch_id TEXT NOT NULL REFERENCES central_staging.snapshots(batch_id)
            ON DELETE CASCADE,
        id TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL,
        project_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(batch_id,id), UNIQUE(batch_id,id,user_id),
        FOREIGN KEY(batch_id,user_id)
            REFERENCES central_staging.users(batch_id,id),
        FOREIGN KEY(batch_id,project_id,user_id)
            REFERENCES central_staging.projects(batch_id,id,user_id)
    )""",
    """CREATE TABLE central_staging.runs (
        batch_id TEXT NOT NULL REFERENCES central_staging.snapshots(batch_id)
            ON DELETE CASCADE,
        id TEXT NOT NULL, user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL, status TEXT NOT NULL,
        mode TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(batch_id,id),
        FOREIGN KEY(batch_id,user_id)
            REFERENCES central_staging.users(batch_id,id),
        FOREIGN KEY(batch_id,conversation_id,user_id)
            REFERENCES central_staging.conversations(batch_id,id,user_id)
    )""",
)
SCHEMA_HASH = hashlib.sha256("\n".join(SCHEMA_SQL).encode("utf-8")).hexdigest()


def _counts(rows):
    return {name: len(rows[name]) for name in TABLES}


def _digest(rows):
    # Canonical cross-database representation. No sensitive row data logged.
    # SQLite and PostgreSQL may use different collations for mixed-case or
    # Unicode identifiers. Order by UTF-8 bytes in Python on both sides.
    ordered = [[name, sorted(rows[name], key=lambda row: row[0].encode("utf-8"))]
               for name in TABLES]
    serial = json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()


def _read_source(path, max_rows=MAX_ROWS):
    if type(max_rows) is not int or not 1 <= max_rows <= 250000:
        raise ValueError("Invalid staging row limit")
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("Source must be a regular SQLite database file")
    # Read-only: never run Database() bootstrap/migrations against user data.
    connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)
    snapshot = sqlite3.connect(":memory:")
    try:
        connection.backup(snapshot)  # SQLite-consistent point-in-time copy
        snapshot.row_factory = sqlite3.Row
        ok = snapshot.execute("PRAGMA integrity_check").fetchone()
        if not ok or ok[0] != "ok":
            raise ValueError("Source SQLite integrity check failed")
        if snapshot.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Source SQLite foreign key check failed")
        rows = {}
        for name, columns in COLUMNS.items():
            available = {item["name"] for item in
                         snapshot.execute('PRAGMA table_info("' + name + '")')}
            if not set(columns).issubset(available):
                raise ValueError("Source schema is missing staging columns")
            sql = ('SELECT ' + ",".join('"' + column + '"' for column in columns)
                   + ' FROM "' + name + '" ORDER BY id')
            rows[name] = [tuple(record) for record in snapshot.execute(sql)]
            if sum(len(value) for value in rows.values()) > max_rows:
                raise ValueError("Source exceeds staging row limit")
        # SQLite permits cross-tenant references unless additionally checked.
        users = {r[0] for r in rows["users"]}
        projects = {r[0]: r[1] for r in rows["projects"]}
        conversations = {r[0]: r[1] for r in rows["conversations"]}
        if any(r[1] not in users for r in rows["projects"]):
            raise ValueError("Source project owner mismatch")
        if any(r[1] not in users or
               (r[3] is not None and projects.get(r[3]) != r[1])
               for r in rows["conversations"]):
            raise ValueError("Source conversation/project ownership mismatch")
        if any(r[1] not in users or conversations.get(r[2]) != r[1]
               for r in rows["runs"]):
            raise ValueError("Source run ownership mismatch")
        return rows
    finally:
        snapshot.close()
        connection.close()


def inspect_source(path, max_rows=MAX_ROWS):
    """Inspect without changing either database or exposing private columns."""
    rows = _read_source(path, max_rows=max_rows)
    return {"stageable": True, "counts": _counts(rows),
            "scope": "metadata_only_no_secrets"}


def install_staging_schema(conn):
    """Versioned staging schema. Fail on a newer or modified migration."""
    _check_connection(conn)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        conn.execute("CREATE SCHEMA IF NOT EXISTS central_staging")
        conn.execute("""CREATE TABLE IF NOT EXISTS central_staging.schema_migrations(
            version INTEGER PRIMARY KEY, checksum TEXT NOT NULL
        )""")
        row = conn.execute(
            "SELECT checksum FROM central_staging.schema_migrations WHERE version=1"
        ).fetchone()
        if row is None:
            for statement in SCHEMA_SQL:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO central_staging.schema_migrations VALUES(1,%s)",
                (SCHEMA_HASH,),
            )
        elif row[0] != SCHEMA_HASH:
            raise RuntimeError("Staging migration checksum mismatch")
        versions = {r[0] for r in conn.execute(
            "SELECT version FROM central_staging.schema_migrations"
        ).fetchall()}
        if versions != {1}:
            raise RuntimeError("Unknown staging schema version")
    return 1


def _read_target(conn, batch_id):
    rows = {}
    with conn.cursor() as cursor:
        for name, columns in COLUMNS.items():
            sql = ('SELECT ' + ",".join(columns) + ' FROM central_staging.'
                   + name + ' WHERE batch_id=%s ORDER BY id')
            cursor.execute(sql, (batch_id,))
            rows[name] = [tuple(row) for row in cursor.fetchall()]
    return rows


def stage_metadata(conn, source_path, max_rows=MAX_ROWS):
    """Copy one snapshot into empty staging, or rollback all writes on error.

    Never write application tables, queues, or a schema other than staging.
    Refuses to overwrite prior staging: discard it by exact batch ID first.
    """
    _check_connection(conn)
    rows = _read_source(source_path, max_rows=max_rows)
    counts = _counts(rows)
    digest = _digest(rows)
    install_staging_schema(conn)
    batch_id = uuid.uuid4().hex
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        if conn.execute("SELECT 1 FROM central_staging.snapshots LIMIT 1").fetchone():
            raise RuntimeError("Staging already contains a snapshot; discard explicitly")
        conn.execute(
            "INSERT INTO central_staging.snapshots(batch_id,row_counts,sha256) "
            "VALUES(%s,%s,%s)",
            (batch_id, json.dumps(counts, sort_keys=True), digest),
        )
        with conn.cursor() as cursor:
            for name, columns in COLUMNS.items():
                placeholders = ",".join(["%s"] * (len(columns) + 1))
                sql = ("INSERT INTO central_staging." + name + "(batch_id,"
                       + ",".join(columns) + ") VALUES(" + placeholders + ")")
                cursor.executemany(sql, [(batch_id, *row) for row in rows[name]])
        staged = _read_target(conn, batch_id)
        if _counts(staged) != counts or _digest(staged) != digest:
            raise RuntimeError("Staging verification failed; transaction rolled back")
    return {"batch_id": batch_id, "counts": counts,
            "verified": True, "scope": "metadata_only_no_secrets"}


def verify_staged(conn, batch_id, source_path=None):
    """Check target tampering and optionally detect SQLite changes since copy."""
    _check_connection(conn)
    if not isinstance(batch_id, str) or len(batch_id) != 32 or not all(
            char in "0123456789abcdef" for char in batch_id):
        raise ValueError("Invalid batch ID")
    # Consistent target snapshot: avoid false validations if another
    # operator discards or modifies staging during a verification.
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        row = conn.execute(
            "SELECT row_counts,sha256 FROM central_staging.snapshots WHERE batch_id=%s",
            (batch_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Staging batch does not exist")
        current = _read_target(conn, batch_id)
        counts = _counts(current)
        expected_counts = json.loads(row[0])
        verified = counts == expected_counts and _digest(current) == row[1]
    result = {"batch_id": batch_id, "verified": verified, "counts": counts,
              "scope": "metadata_only_no_secrets"}
    if source_path is not None:
        source = _read_source(source_path)
        result["source_unchanged"] = (_counts(source) == expected_counts
                                      and _digest(source) == row[1])
    return result


def discard_staged(conn, batch_id, *, confirmation):
    """Revert staged PostgreSQL copy, never touching the SQLite source."""
    _check_connection(conn)
    if confirmation != "DISCARD-STAGING":
        raise PermissionError("Explicit discard confirmation is required")
    if not isinstance(batch_id, str) or len(batch_id) != 32 or not all(
            char in "0123456789abcdef" for char in batch_id):
        raise ValueError("Invalid batch ID")
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        result = conn.execute(
            "DELETE FROM central_staging.snapshots WHERE batch_id=%s",
            (batch_id,),
        )
        if result.rowcount != 1:
            raise ValueError("Staging batch does not exist")
    return {"discarded": True, "batch_id": batch_id}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Experimental metadata-only SQLite/PostgreSQL staging")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("source")
    stage = commands.add_parser("stage")
    stage.add_argument("source")
    stage.add_argument("--confirm-staging", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("batch_id")
    verify.add_argument("--source")
    discard = commands.add_parser("discard")
    discard.add_argument("batch_id")
    discard.add_argument("--confirm-discard", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "inspect":
        result = inspect_source(args.source)
    else:
        dsn = os.environ.get("CENTRAL_PG_MIGRATION_DSN")
        if not dsn:
            parser.error("CENTRAL_PG_MIGRATION_DSN must target a disposable database")
        if args.command == "stage" and not args.confirm_staging:
            parser.error("Staging requires --confirm-staging")
        if args.command == "discard" and not args.confirm_discard:
            parser.error("Discard requires --confirm-discard")
        with connect(dsn) as conn:
            if args.command == "stage":
                result = stage_metadata(conn, args.source)
            elif args.command == "verify":
                result = verify_staged(conn, args.batch_id, args.source)
            else:
                result = discard_staged(
                    conn, args.batch_id, confirmation="DISCARD-STAGING")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("verified") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
