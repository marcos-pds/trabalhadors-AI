"""Optional Redis *hints* for the experimental PostgreSQL queue.

Redis carries no run IDs, user IDs, secrets, authorization, leases or durable
state. A message is only a suggestion to re-check the authoritative database.
Every worker must still poll the database periodically: Redis Pub/Sub drops
messages when subscribers are offline or connections are interrupted.
"""
from contextlib import contextmanager
from urllib.parse import urlsplit

CHANNEL = "central:experimental-queue:ready:v1"
MESSAGE = "ready"


def _validate_url(url):
    if not isinstance(url, str) or not url.strip():
        raise ValueError("An explicit Redis URL is required")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid Redis URL") from exc
    if (parsed.scheme not in ("redis", "rediss") or not hostname
            or parsed.fragment or parsed.query
            or (parsed.path and parsed.path != "/" and
                (not parsed.path.startswith("/") or
                 not parsed.path[1:].isdigit()))):
        raise ValueError("Invalid Redis URL")
    if port is not None and port < 1:
        raise ValueError("Invalid Redis port")
    # Plaintext Redis must never be used over a remote network.
    if parsed.scheme == "redis" and hostname not in (
            "127.0.0.1", "::1", "localhost"):
        raise ValueError("Remote Redis connections require rediss:// (TLS)")
    return url


class _UnavailableListener:
    def wait(self, timeout=0.5):
        if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 60:
            raise ValueError("timeout must be 0..60 seconds")
        return False


class _RedisListener(_UnavailableListener):
    def __init__(self, pubsub, redis_module):
        self._pubsub = pubsub
        self._redis = redis_module

    def wait(self, timeout=0.5):
        super().wait(timeout)
        try:
            message = self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=timeout
            )
            return bool(message and message.get("type") == "message"
                        and message.get("data") == MESSAGE)
        except (self._redis.exceptions.RedisError, OSError):
            # Caller must resume periodic database polls on connection loss.
            return False


class RedisQueueSignals:
    """Best-effort wakeups. Instantiate only with operator-supplied URL."""

    def __init__(self, url):
        _validate_url(url)
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError(
                "Install requirements-redis.txt to enable Redis signals"
            ) from exc
        self._redis = redis
        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=1.0,
            health_check_interval=15,
        )

    def publish(self):
        """Never allow a Redis outage to prevent a committed queue enqueue."""
        try:
            self._client.publish(CHANNEL, MESSAGE)
            return True
        except (self._redis.exceptions.RedisError, OSError):
            return False

    @contextmanager
    def subscriber(self):
        """A live subscription receives hints, not permissions to run tasks.

        Unavailable Redis yields a no-op listener; callers must poll their DB.
        Subscribers created after a message was published cannot recover it.
        """
        pubsub = self._client.pubsub(ignore_subscribe_messages=True)
        try:
            pubsub.subscribe(CHANNEL)
        except (self._redis.exceptions.RedisError, OSError):
            pubsub.close()
            yield _UnavailableListener()
            return
        try:
            yield _RedisListener(pubsub, self._redis)
        finally:
            pubsub.close()

    def close(self):
        self._client.close()
