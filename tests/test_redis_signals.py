"""Optional Redis signalling: hints never replace PostgreSQL authorization.

Full integration requires disposable CENTRAL_PG_TEST_DSN and Redis at
CENTRAL_REDIS_TEST_URL. A missing service skips, not silently passes in CI.
"""
import os
import pytest

from central.redis_signals import _validate_url, RedisQueueSignals
from central.postgres_queue import connect, install_schema, PostgresJobQueue

REDIS_URL = os.environ.get("CENTRAL_REDIS_TEST_URL")
POSTGRES_DSN = os.environ.get("CENTRAL_PG_TEST_DSN")


@pytest.mark.parametrize("url", [
    "", "http://localhost:6379", "redis://remote.example.com:6379/0",
    "redis://localhost:badport", "redis://localhost:6379/?ssl_cert_reqs=none",
    "rediss://localhost:6379/0#fragment", "redis://localhost:0",
])
def test_reject_unsafe_or_invalid_redis_url(url):
    with pytest.raises(ValueError):
        _validate_url(url)


@pytest.mark.parametrize("url", [
    "redis://localhost:6379/0",
    "redis://127.0.0.1:6379/1",
    "rediss://remote.example.com:6380/0",
])
def test_allow_approved_redis_url_forms(url):
    assert _validate_url(url) == url


def test_redis_disconnect_cannot_block_database_polling():
    pytest.importorskip("redis")
    bus = RedisQueueSignals("redis://127.0.0.1:1/0")
    try:
        assert not bus.publish()
        with bus.subscriber() as subscriber:
            assert not subscriber.wait(timeout=0)
    finally:
        bus.close()


@pytest.mark.skipif(not REDIS_URL, reason="CENTRAL_REDIS_TEST_URL is required")
def test_real_redis_pubsub_hints_are_recoverable_only_while_subscribed():
    bus = RedisQueueSignals(REDIS_URL)
    try:
        with bus.subscriber() as subscriber:
            assert bus.publish()
            assert subscriber.wait(timeout=3)
            assert not subscriber.wait(timeout=0.01)
        # Redis Pub/Sub is not a backlog. A late subscription cannot replay it.
        with bus.subscriber() as subscriber:
            assert not subscriber.wait(timeout=0.01)
    finally:
        bus.close()


@pytest.mark.skipif(not REDIS_URL or not POSTGRES_DSN,
                    reason="Real PostgreSQL and Redis test URLs are required")
def test_signal_observes_postgres_enqueue_only_after_database_commit():
    bus = RedisQueueSignals(REDIS_URL)
    conn = connect(POSTGRES_DSN)
    try:
        install_schema(conn)
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        queue = PostgresJobQueue(conn, signals=bus)
        with bus.subscriber() as subscriber:
            assert queue.enqueue("hint-run", "owner-a")
            assert subscriber.wait(timeout=3)
            # Redis doesn't carry IDs: authoritative data lives in PostgreSQL.
            assert queue.details("hint-run")["state"] == "queued"
        claim = queue.claim("worker-a")
        assert claim["run_id"] == "hint-run"
        assert queue.finish("hint-run", "worker-a", "completed",
                            lease_token=claim["lease_token"])
        with conn.transaction():
            with pytest.raises(ValueError, match="outer transaction"):
                queue.enqueue("reject-nested", "owner-a")
        assert queue.details("reject-nested") is None
    finally:
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        conn.close()
        bus.close()


@pytest.mark.skipif(not POSTGRES_DSN, reason="Real PostgreSQL DSN is required")
def test_redis_outage_does_not_roll_back_postgres_enqueue():
    conn = connect(POSTGRES_DSN)
    bus = RedisQueueSignals("redis://127.0.0.1:1/0")
    try:
        install_schema(conn)
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        queue = PostgresJobQueue(conn, signals=bus)
        assert queue.enqueue("outage-safe", "owner-a")
        assert queue.details("outage-safe")["state"] == "queued"
    finally:
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        bus.close()
        conn.close()


@pytest.mark.skipif(not REDIS_URL or not POSTGRES_DSN,
                    reason="Real PostgreSQL and Redis test URLs are required")
def test_experimental_waiter_claims_after_redis_hint():
    import threading
    import time
    from central.postgres_claim_waiter import ExperimentalPostgresClaimWaiter

    bus = RedisQueueSignals(REDIS_URL)
    conn = connect(POSTGRES_DSN)
    errors = []
    try:
        install_schema(conn)
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        queue = PostgresJobQueue(conn)
        def enqueue_later():
            other = connect(POSTGRES_DSN)
            try:
                time.sleep(0.2)
                assert PostgresJobQueue(other, signals=bus).enqueue(
                    "woken-job", "owner"
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                other.close()

        producer = threading.Thread(target=enqueue_later)
        producer.start()
        waiter = ExperimentalPostgresClaimWaiter(
            queue, signals=bus, poll_seconds=1.5
        )
        claim = waiter.wait_for_claim("consumer", max_wait_seconds=3)
        producer.join(timeout=5)
        assert not producer.is_alive() and not errors
        assert claim and claim["run_id"] == "woken-job"
        assert queue.finish(
            "woken-job", "consumer", "completed",
            lease_token=claim["lease_token"],
        )
    finally:
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        conn.close()
        bus.close()


@pytest.mark.skipif(not REDIS_URL or not POSTGRES_DSN,
                    reason="Real PostgreSQL and Redis test URLs are required")
def test_experimental_waiter_recovers_when_notification_never_arrives():
    import threading
    import time
    from central.postgres_claim_waiter import ExperimentalPostgresClaimWaiter

    bus = RedisQueueSignals(REDIS_URL)
    conn = connect(POSTGRES_DSN)
    errors = []
    try:
        install_schema(conn)
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        queue = PostgresJobQueue(conn)
        def silent_enqueue():
            other = connect(POSTGRES_DSN)
            try:
                time.sleep(0.15)
                # Missing publish is intentional: Pub/Sub is not durable.
                PostgresJobQueue(other).enqueue("missed-signal", "owner")
            except Exception as exc:
                errors.append(exc)
            finally:
                other.close()

        producer = threading.Thread(target=silent_enqueue)
        producer.start()
        waiter = ExperimentalPostgresClaimWaiter(
            queue, signals=bus, poll_seconds=0.2
        )
        claim = waiter.wait_for_claim("consumer", max_wait_seconds=2)
        producer.join(timeout=5)
        assert not producer.is_alive() and not errors
        assert claim and claim["run_id"] == "missed-signal"
        assert queue.finish(
            "missed-signal", "consumer", "completed",
            lease_token=claim["lease_token"],
        )
    finally:
        conn.execute("TRUNCATE TABLE central_jobs.queue")
        conn.close()
        bus.close()
