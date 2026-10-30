"""Bounded autonomous work budgets, configurable without changing permissions."""
import os


def _limit(name, default, low, high):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


MAX_ROUNDS = _limit('CENTRAL_WORKER_MAX_ROUNDS', 48, 12, 96)
MAX_ACTIONS = _limit('CENTRAL_WORKER_MAX_ACTIONS', 42, 18, 90)
PLANNING_ROUNDS = _limit('CENTRAL_WORKER_PLANNING_ROUNDS', 12, 6, 24)
MAX_RESUMES = _limit('CENTRAL_WORKER_MAX_RESUMES', 24, 8, 48)
MAX_STALLED_ROUNDS = 6
