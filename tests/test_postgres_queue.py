"""Real PostgreSQL integration tests. Requires CENTRAL_PG_TEST_DSN.

Run only against a disposable PostgreSQL database. These tests deliberately
do not touch the application's SQLite data or install schema extensions.
"""
import os
import threading

import pytest

from central.postgres_queue import connect, install_schema, PostgresJobQueue

DSN = os.environ.get("CENTRAL_PG_TEST_DSN")


@pytest.fixture()
def pg():
    if not DSN:
        pytest.skip("CENTRAL_PG_TEST_DSN is needed for PostgreSQL integration tests")
    conn = connect(DSN)
    try:
        install_schema(conn)
        # This fixture is intentionally destructive only in its test schema.
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        yield conn
    finally:
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        conn.close()


def test_migration_is_idempotent_and_checksums_are_enforced(pg):
    assert install_schema(pg) == 1
    assert pg.execute(
        "SELECT COUNT(*) FROM central_jobs.schema_migrations"
    ).fetchone()[0] == 1
    with pytest.raises(RuntimeError, match="checksum"):
        with pg.transaction():
            pg.execute(
                "UPDATE central_jobs.schema_migrations SET checksum='tampered' WHERE version=1"
            )
            install_schema(pg)
    assert install_schema(pg) == 1


def test_only_one_worker_can_claim_the_same_run(pg):
    queue = PostgresJobQueue(pg)
    queue.enqueue("job-1", "user-1")
    barrier = threading.Barrier(2)
    results, errors = [], []

    def attempt(name):
        conn = connect(DSN)
        try:
            barrier.wait(timeout=5)
            results.append(PostgresJobQueue(conn).claim(name))
        except Exception as exc:
            errors.append(exc)
        finally:
            conn.close()

    threads = [
        threading.Thread(target=attempt, args=(name,))
        for name in ("worker-a", "worker-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    claimed = [item for item in results if item]
    assert len(claimed) == 1
    assert claimed[0]["run_id"] == "job-1"
    assert queue.finish(
        "job-1", claimed[0]["owner"], "completed",
        lease_token=claimed[0]["lease_token"],
    )


def test_claim_serialization_preserves_per_user_limit(pg):
    queue = PostgresJobQueue(pg)
    queue.enqueue("a", "user-one")
    queue.enqueue("b", "user-one")
    queue.enqueue("c", "user-two")
    first = queue.claim("worker-1", per_user_limit=1)
    second = queue.claim("worker-2", per_user_limit=1)
    assert first["run_id"] == "a"
    assert second["run_id"] == "c"
    assert queue.claim("worker-3", per_user_limit=1) is None
    assert queue.finish("a", "worker-1", "completed",
                        lease_token=first["lease_token"])
    third = queue.claim("worker-3", per_user_limit=1)
    assert third["run_id"] == "b"


def test_expired_lease_fences_stale_token_even_if_worker_id_is_reused(pg):
    queue = PostgresJobQueue(pg, lease_seconds=30)
    queue.enqueue("recovered", "owner")
    first = queue.claim("worker")
    assert first["attempt"] == 1
    assert not queue.heartbeat("recovered", "worker")
    assert not queue.finish("recovered", "worker", "completed")
    pg.execute(
        "UPDATE central_jobs.queue SET lease_until=clock_timestamp()-INTERVAL '1 second' "
        "WHERE run_id='recovered'"
    )
    second = queue.claim("worker")
    assert second["recovered"] and second["attempt"] == 2
    assert first["lease_token"] != second["lease_token"]
    assert not queue.heartbeat("recovered", "worker", first["lease_token"])
    assert not queue.finish("recovered", "worker", "completed",
                            lease_token=first["lease_token"])
    assert queue.heartbeat("recovered", "worker", second["lease_token"])
    assert queue.finish("recovered", "worker", "completed",
                        lease_token=second["lease_token"])
    assert "lease_token" not in queue.details("recovered")


def test_expired_attempt_limit_marks_queue_failed_without_replay(pg):
    queue = PostgresJobQueue(pg, max_attempts=1)
    queue.enqueue("exhausted", "user-a")
    old = queue.claim("dead-worker")
    pg.execute(
        "UPDATE central_jobs.queue SET lease_until=clock_timestamp()-INTERVAL '1 second' "
        "WHERE run_id='exhausted'"
    )
    assert queue.claim("new-worker") is None
    row = queue.details("exhausted")
    assert row["state"] == "failed"
    assert row["attempts"] == 1
    assert row["last_error"] == "lease_attempts_exhausted"
    assert not queue.finish("exhausted", "dead-worker", "completed",
                            lease_token=old["lease_token"])


def test_cancel_resume_and_tenant_assignment_cannot_reuse_tokens(pg):
    queue = PostgresJobQueue(pg)
    queue.enqueue("r", "user-a")
    with pytest.raises(PermissionError):
        queue.enqueue("r", "user-b")
    first = queue.claim("worker")
    assert queue.cancel("r")
    assert not queue.heartbeat("r", "worker", first["lease_token"])
    queue.enqueue("r", "user-a")
    second = queue.claim("worker")
    assert second["lease_token"] != first["lease_token"]
    assert queue.finish("r", "worker", "completed",
                        lease_token=second["lease_token"])
