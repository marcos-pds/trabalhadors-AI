"""Experimental PostgreSQL queue substrate; NOT connected to the application.

The deployed API and workers still use the SQLite Database/JobQueue. This
module establishes a separately namespaced PostgreSQL implementation for
transactional and multi-connection tests before any production cutover.

It does not migrate business runs, authorize execution, or fence external tools.
Callers must supply authenticated run/user IDs; never expose enqueue to clients.
"""
import hashlib
import uuid

SCHEMA = "central_jobs"

_MIGRATIONS = (
    (1, "isolated_queue", (
        """CREATE TABLE central_jobs.queue (
            run_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued'
                CHECK(state IN ('queued','claimed','completed','paused','failed','cancelled')),
            lease_owner TEXT, lease_token TEXT, lease_until TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
            available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            queued_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            last_error TEXT
        )""",
        """CREATE INDEX queue_claim_idx
           ON central_jobs.queue(state,available_at,lease_until,queued_at)""",
        """CREATE INDEX queue_user_idx ON central_jobs.queue(user_id,state,lease_until)""",
        """CREATE TABLE central_jobs.claim_gate (
            id INTEGER PRIMARY KEY CHECK(id=1)
        )""",
        """INSERT INTO central_jobs.claim_gate(id) VALUES(1)""",
    )),
)


def connect(dsn):
    """Explicit, opt-in psycopg connection. Never read secrets from a default."""
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("A nonempty PostgreSQL DSN is required")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install requirements-postgres.txt to use PostgreSQL") from exc
    return psycopg.connect(dsn, autocommit=True, connect_timeout=5)


def _check_connection(conn):
    if not getattr(conn, "autocommit", False):
        raise ValueError("PostgreSQL queue requires an autocommit connection")


def install_schema(conn):
    """Install only central_jobs schema; serialize and verify version checksums."""
    _check_connection(conn)
    with conn.transaction():
        # Installation is serialized, including the first creation of the schema.
        conn.execute("SELECT pg_advisory_xact_lock(718240921)")
        conn.execute("CREATE SCHEMA IF NOT EXISTS central_jobs")
        conn.execute("""CREATE TABLE IF NOT EXISTS central_jobs.schema_migrations(
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )""")
        for version, name, statements in _MIGRATIONS:
            checksum = hashlib.sha256("\n".join(statements).encode("utf-8")).hexdigest()
            from psycopg.rows import dict_row
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT checksum FROM central_jobs.schema_migrations WHERE version=%s",
                    (version,),
                )
                row = cur.fetchone()
            if row:
                if row["checksum"] != checksum:
                    raise RuntimeError("PostgreSQL migration checksum mismatch")
                continue
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                """INSERT INTO central_jobs.schema_migrations(version,name,checksum)
                   VALUES(%s,%s,%s)""",
                (version, name, checksum),
            )
        known = tuple(version for version, _, _ in _MIGRATIONS)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT version FROM central_jobs.schema_migrations")
            installed = {row["version"] for row in cur.fetchall()}
        if not installed.issubset(known):
            raise RuntimeError("PostgreSQL schema is newer than this application")
    return len(_MIGRATIONS)


def _identity(value, label):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value:
        raise ValueError("Invalid " + label)
    return value


class PostgresJobQueue:
    """Isolated queue prototype; transactions remain authoritative in PostgreSQL.

    A singleton claim gate serializes claim decisions. It preserves fairness
    limits under concurrent workers at the cost of claim throughput; do not
    imply this is ready for distributed production loads.
    """

    def __init__(self, conn, *, lease_seconds=90, max_attempts=5):
        _check_connection(conn)
        if type(lease_seconds) is not int or not 20 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be 20..3600")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be 1..20")
        self.conn = conn
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def enqueue(self, run_id, user_id):
        """Explicit queue-only enqueue; does not check a SQLite business run."""
        run_id = _identity(run_id, "run_id")
        user_id = _identity(user_id, "user_id")
        with self.conn.transaction():
            # User association must never be overwritten by re-enqueue.
            from psycopg.rows import dict_row
            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT user_id FROM central_jobs.queue WHERE run_id=%s FOR UPDATE",
                    (run_id,),
                )
                existing = cur.fetchone()
            if existing and existing["user_id"] != user_id:
                raise PermissionError("Cannot reassign a queued run to another user")
            self.conn.execute(
                """INSERT INTO central_jobs.queue(run_id,user_id)
                   VALUES(%s,%s)
                   ON CONFLICT(run_id) DO UPDATE SET
                   state=CASE WHEN queue.state='claimed'
                              THEN 'claimed' ELSE 'queued' END,
                   available_at=CASE WHEN queue.state='claimed'
                                     THEN queue.available_at ELSE clock_timestamp() END,
                   attempts=CASE WHEN queue.state IN
                     ('completed','paused','failed','cancelled')
                     THEN 0 ELSE queue.attempts END,
                   last_error=CASE WHEN queue.state IN
                     ('completed','paused','failed','cancelled')
                     THEN NULL ELSE queue.last_error END,
                   lease_token=CASE WHEN queue.state='claimed'
                                    THEN queue.lease_token ELSE NULL END,
                   lease_owner=CASE WHEN queue.state='claimed'
                                    THEN queue.lease_owner ELSE NULL END,
                   lease_until=CASE WHEN queue.state='claimed'
                                    THEN queue.lease_until ELSE NULL END,
                   updated_at=clock_timestamp()""",
                (run_id, user_id),
            )
        return True

    def claim(self, owner, *, per_user_limit=2):
        _identity(owner, "worker")
        if type(per_user_limit) is not int or per_user_limit < 1:
            raise ValueError("per_user_limit must be positive")
        from psycopg.rows import dict_row
        with self.conn.transaction():
            # Claim decisions are serialized, so the fair-use count cannot race
            # across two separate runnable rows for the same user.
            self.conn.execute(
                "SELECT id FROM central_jobs.claim_gate WHERE id=1 FOR UPDATE"
            )
            for _ in range(24):
                with self.conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """SELECT q.run_id,q.user_id,q.state,q.attempts
                           FROM central_jobs.queue q
                           WHERE ((q.state='queued' AND q.available_at<=clock_timestamp())
                             OR (q.state='claimed' AND q.lease_until<=clock_timestamp()))
                             AND (SELECT COUNT(*) FROM central_jobs.queue a
                                  WHERE a.user_id=q.user_id AND a.state='claimed'
                                    AND a.lease_until>clock_timestamp()) < %s
                           ORDER BY q.available_at,q.queued_at,q.run_id
                           LIMIT 1 FOR UPDATE OF q""",
                        (per_user_limit,),
                    )
                    candidate = cur.fetchone()
                if candidate is None:
                    return None
                if candidate["state"] == "claimed" and candidate["attempts"] >= self.max_attempts:
                    self.conn.execute(
                        """UPDATE central_jobs.queue
                           SET state='failed',lease_owner=NULL,lease_token=NULL,
                               lease_until=NULL,last_error='lease_attempts_exhausted',
                               updated_at=clock_timestamp()
                           WHERE run_id=%s""",
                        (candidate["run_id"],),
                    )
                    continue
                token = uuid.uuid4().hex
                self.conn.execute(
                    """UPDATE central_jobs.queue
                       SET state='claimed',lease_owner=%s,lease_token=%s,
                           lease_until=clock_timestamp()+make_interval(secs => %s),
                           attempts=attempts+1,updated_at=clock_timestamp()
                       WHERE run_id=%s""",
                    (owner, token, self.lease_seconds, candidate["run_id"]),
                )
                return {
                    "run_id": candidate["run_id"],
                    "owner": owner,
                    "lease_token": token,
                    "attempt": candidate["attempts"] + 1,
                    "recovered": candidate["state"] == "claimed",
                }
        return None

    def heartbeat(self, run_id, owner, lease_token=None):
        if not isinstance(lease_token, str) or not lease_token:
            return False
        with self.conn.transaction():
            cursor = self.conn.execute(
                """UPDATE central_jobs.queue
                   SET lease_until=clock_timestamp()+make_interval(secs => %s),
                       updated_at=clock_timestamp()
                   WHERE run_id=%s AND state='claimed'
                     AND lease_owner=%s AND lease_token=%s
                     AND lease_until>clock_timestamp()""",
                (self.lease_seconds, run_id, owner, lease_token),
            )
            return cursor.rowcount == 1

    def finish(self, run_id, owner, state, error=None, lease_token=None):
        if state not in ("completed", "paused", "failed", "cancelled", "queued"):
            raise ValueError("Invalid queue terminal state")
        if not isinstance(lease_token, str) or not lease_token:
            return False
        with self.conn.transaction():
            cursor = self.conn.execute(
                """UPDATE central_jobs.queue
                   SET state=%s,lease_owner=NULL,lease_token=NULL,lease_until=NULL,
                       last_error=%s,updated_at=clock_timestamp()
                   WHERE run_id=%s AND state='claimed'
                     AND lease_owner=%s AND lease_token=%s
                     AND lease_until>clock_timestamp()""",
                (state, str(error)[:240] if error else None, run_id, owner, lease_token),
            )
            return cursor.rowcount == 1

    def cancel(self, run_id):
        with self.conn.transaction():
            cursor = self.conn.execute(
                """UPDATE central_jobs.queue
                   SET state='cancelled',lease_owner=NULL,lease_token=NULL,
                       lease_until=NULL,updated_at=clock_timestamp()
                   WHERE run_id=%s""",
                (run_id,),
            )
            return cursor.rowcount == 1

    def details(self, run_id):
        # Never expose lease ownership secrets to the caller.
        from psycopg.rows import dict_row
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT run_id,state,attempts,queued_at,updated_at,
                          lease_until,available_at,last_error
                   FROM central_jobs.queue WHERE run_id=%s""",
                (run_id,),
            )
            return cur.fetchone()
