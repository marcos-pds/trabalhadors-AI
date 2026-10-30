"""Claim waiter's fallback rules must be correct without Redis installed."""
import pytest

from central.postgres_claim_waiter import ExperimentalPostgresClaimWaiter


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, duration):
        self.value += duration


class FakeQueue:
    def __init__(self, claim_on=3):
        self.calls = 0
        self.claim_on = claim_on

    def claim(self, owner, *, per_user_limit=2):
        self.calls += 1
        if self.calls == self.claim_on:
            return {"run_id": "trusted-pg-row", "owner": owner, "lease_token": "token"}
        return None


class BrokenSubscription:
    def wait(self, timeout):
        return False


class BrokenSignals:
    from contextlib import contextmanager

    @contextmanager
    def subscriber(self):
        yield BrokenSubscription()


def test_durable_polling_claims_even_without_any_redis_signal():
    time = FakeClock()
    queue = FakeQueue(claim_on=3)
    waiter = ExperimentalPostgresClaimWaiter(
        queue, signals=BrokenSignals(), poll_seconds=0.5,
        clock=time.now, sleeper=time.sleep,
    )
    claim = waiter.wait_for_claim("worker", max_wait_seconds=5)
    assert claim["run_id"] == "trusted-pg-row"
    assert queue.calls == 3
    assert time.value == pytest.approx(1.0)


def test_timeout_never_claims_extra_work():
    time = FakeClock()
    queue = FakeQueue(claim_on=100)
    waiter = ExperimentalPostgresClaimWaiter(
        queue, poll_seconds=0.5, clock=time.now, sleeper=time.sleep,
    )
    assert waiter.wait_for_claim("worker", max_wait_seconds=1.0) is None
    assert queue.calls == 3
    assert time.value == pytest.approx(1.0)


@pytest.mark.parametrize("interval", [0, -1, True, float("inf"), float("nan"), 31])
def test_reject_invalid_poll_interval(interval):
    with pytest.raises(ValueError):
        ExperimentalPostgresClaimWaiter(FakeQueue(), poll_seconds=interval)


@pytest.mark.parametrize("wait", [-1, True, float("inf"), float("nan"), 301])
def test_reject_unbounded_wait(wait):
    waiter = ExperimentalPostgresClaimWaiter(FakeQueue())
    with pytest.raises(ValueError):
        waiter.wait_for_claim("worker", max_wait_seconds=wait)
