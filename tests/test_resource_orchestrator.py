"""Pure-Python contract tests; no GPU, model or network access required."""
import threading
import time

import pytest

from central.resource_orchestrator import (
    ResourceLimits, ResourceRequest, ResourceOrchestrator, ResourceBusy,
    ResourceCancelled, ResourceOverBudget, ResidentModel, ResidentModelPlanner,
    plan_weight_placement,
)


def spin_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.002)
    return False


def test_reservation_release_and_exclusivity():
    resources = ResourceOrchestrator(ResourceLimits(ram_mb=12000, vram_mb=12000))
    with resources.reserve(ResourceRequest("wan", gpu_slots=1, vram_mb=9500)) as lease:
        assert resources.snapshot()["reserved"]["vram_mb"] == 9500
        assert resources.snapshot()["physical_measurements"] is False
        with pytest.raises(ResourceBusy):
            resources.reserve(ResourceRequest("ollama", gpu_slots=1), timeout=0)
    lease.release()  # Idempotent.
    assert resources.snapshot()["active"] == 0


def test_limits_and_strict_validation():
    with pytest.raises(ResourceOverBudget):
        ResourceOrchestrator().reserve(ResourceRequest("wan", gpu_slots=2))
    for invalid in (
        lambda: ResourceLimits(gpu_slots=0),
        lambda: ResourceLimits(ram_mb=True),
        lambda: ResourceRequest("../escape"),
        lambda: ResourceRequest("wan", vram_mb=1),
        lambda: ResourceRequest("wan", priority=10),
    ):
        with pytest.raises(ValueError):
            invalid()
    assert ResourceOrchestrator().snapshot()["limits"]["vram_mb"] is None


def test_priorities_and_fifo():
    resources = ResourceOrchestrator()
    occupied = resources.reserve(ResourceRequest("busy", gpu_slots=1))
    order = []
    def worker(name, priority):
        with resources.reserve(ResourceRequest(name, gpu_slots=1, priority=priority), timeout=3):
            order.append(name)
    low = threading.Thread(target=worker, args=("low", 1))
    high = threading.Thread(target=worker, args=("high", 9))
    low.start()
    assert spin_until(lambda: resources.snapshot()["waiting"] == 1)
    high.start()
    assert spin_until(lambda: resources.snapshot()["waiting"] == 2)
    occupied.release()
    low.join(3)
    high.join(3)
    assert not low.is_alive() and not high.is_alive()
    assert order == ["high", "low"]


def test_cancelled_waiter_and_timeout_cleanup():
    resources = ResourceOrchestrator()
    owner = resources.reserve(ResourceRequest("owner", gpu_slots=1))
    cancelled = threading.Event()
    seen = []
    def worker():
        try:
            resources.reserve(ResourceRequest("wait", gpu_slots=1), timeout=None,
                              cancelled=cancelled.is_set)
        except ResourceCancelled:
            seen.append(True)
    thread = threading.Thread(target=worker)
    thread.start()
    assert spin_until(lambda: resources.snapshot()["waiting"] == 1)
    cancelled.set()
    thread.join(2)
    assert seen == [True]
    assert resources.snapshot()["waiting"] == 0
    with pytest.raises(ResourceBusy):
        resources.reserve(ResourceRequest("wait", gpu_slots=1), timeout=.01)
    assert resources.snapshot()["waiting"] == 0
    owner.release()


def test_placement_never_claims_unsupported_streaming():
    args = dict(weights_mb=12000, frequently_used_mb=9000,
                ram_budget_mb=2000, vram_budget_mb=8000, gpu_working_mb=2000)
    plan = plan_weight_placement(**args, supports_streaming=True)
    assert (plan.gpu_pinned_mb, plan.ram_pinned_mb, plan.streamed_from_disk_mb) == (6000, 2000, 4000)
    assert plan.supported
    blocked = plan_weight_placement(**args)
    assert not blocked.supported and blocked.reason == "streaming_not_supported"


def test_advisory_eviction_preserves_busy_and_pinned_models():
    planner = ResidentModelPlanner()
    planner.record(ResidentModel("wan", ram_mb=4000, vram_mb=9000, busy=True))
    planner.record(ResidentModel("ollama", ram_mb=500, vram_mb=2000))
    planner.record(ResidentModel("qwen", ram_mb=1000, vram_mb=3500, pinned=True))
    proposed = planner.propose_evictions(vram_mb=4500)
    assert proposed.names == ("ollama",)
    assert proposed.unfulfilled_vram_mb == 2500
    planner.record(ResidentModel("ollama", ram_mb=500, vram_mb=2000, busy=True))
    assert planner.propose_evictions(ram_mb=1000).names == ()


def test_context_manager_releases_on_exception():
    resources = ResourceOrchestrator()
    with pytest.raises(RuntimeError):
        with resources.reserve(ResourceRequest("work", gpu_slots=1)):
            raise RuntimeError("failed")
    assert resources.snapshot()["active"] == 0
