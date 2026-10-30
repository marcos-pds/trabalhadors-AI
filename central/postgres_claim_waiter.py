"""Experimental PostgreSQL claim waiter with optional Redis wakeup hints.

This is not a production worker and deliberately never runs user code.
Redis messages cannot grant claims: PostgresJobQueue.claim() decides every time.
Periodic polling is mandatory because Pub/Sub messages are not durable.
"""
import math
import time
from contextlib import nullcontext


class ExperimentalPostgresClaimWaiter:
    def __init__(self, queue, *, signals=None, poll_seconds=0.5,
                 clock=None, sleeper=None):
        if (type(poll_seconds) not in (int, float)
                or not math.isfinite(poll_seconds)
                or not 0.05 <= poll_seconds <= 30):
            raise ValueError("poll_seconds must be between 0.05 and 30")
        self.queue = queue
        self.signals = signals
        self.poll_seconds = float(poll_seconds)
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep

    def wait_for_claim(self, owner, *, max_wait_seconds=5, per_user_limit=2):
        """Return an authoritative claim or None after a bounded wait.

        This only waits for and claims an experimental PostgreSQL queue row.
        No workspace or external tool execution is authorized by this method.
        """
        if (type(max_wait_seconds) not in (int, float)
                or not math.isfinite(max_wait_seconds)
                or not 0 <= max_wait_seconds <= 300):
            raise ValueError("max_wait_seconds must be between 0 and 300")
        deadline = self.clock() + max_wait_seconds
        subscription = (self.signals.subscriber() if self.signals is not None
                        else nullcontext(None))
        with subscription as listener:
            while True:
                claimed = self.queue.claim(owner, per_user_limit=per_user_limit)
                if claimed is not None:
                    return claimed
                remaining = deadline - self.clock()
                if remaining <= 0:
                    return None
                interval = min(remaining, self.poll_seconds)
                started = self.clock()
                notified = listener.wait(interval) if listener is not None else False
                if not notified:
                    # Degraded Redis listener may return immediately. Bound
                    # subsequent DB polls, rather than spinning on outage.
                    rest = interval - (self.clock() - started)
                    if rest > 0:
                        self.sleeper(rest)
                # Re-check PostgreSQL on wakeup AND after every poll interval.
