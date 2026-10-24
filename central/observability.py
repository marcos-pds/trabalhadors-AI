"""Local-first structured telemetry with bounded, non-sensitive metadata.

Do not log request bodies, prompts, API credentials, response bodies, file
contents, session cookies, or raw provider errors.
"""
import contextvars
import json
import logging
import re
import sys
import time
import uuid

request_context = contextvars.ContextVar('central_request_id', default=None)
_logger = logging.getLogger('central.operations')
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter('%(message)s'))
    _logger.addHandler(_handler)
_logger.setLevel(logging.INFO)
_logger.propagate = False

_SAFE = re.compile(r'^[a-zA-Z0-9_-]{1,100}$')


def correlation_id(supplied=None):
    return supplied if supplied and _SAFE.fullmatch(supplied) else uuid.uuid4().hex


def log_event(event, **details):
    safe = {'timestamp': __import__('datetime').datetime.now(
                __import__('datetime').timezone.utc).isoformat(),
            'event': str(event)[:70],
            'request_id': request_context.get()}
    permitted = ('run_id', 'step_id', 'provider_id', 'status', 'http_status',
                 'duration_ms', 'category', 'outcome', 'event_type',
                 'task_type', 'requires_approval', 'route', 'method',
                 'elapsed_ms', 'cost_estimate')
    for field in permitted:
        value = details.get(field)
        if isinstance(value, (int, float, bool)) or (
                isinstance(value, str) and len(value) <= 140):
            safe[field] = value
    _logger.info(json.dumps(safe, separators=(',', ':'), ensure_ascii=False))


def duration_ms(start):
    return max(0, round((time.monotonic() - start) * 1000, 2))
