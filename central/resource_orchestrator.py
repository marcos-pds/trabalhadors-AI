"""Advisory model placement and thread-safe local resource reservations.

The coordinator reserves *declared estimates*, not physical memory. It never loads,
unloads, downloads, executes a program, or moves model weights. Keep it behind
trusted runtime adapters; this module is intentionally independent of FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
from typing import Callable

_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,63}\\Z")


class ResourceBusy(RuntimeError):
    """A declared capacity cannot be reserved before the timeout."""


class ResourceCancelled(RuntimeError):
    """A queued reservation was cancelled before it was granted."""


class ResourceOverBudget(ValueError):
    """A request exceeds a configured maximum, regardless of current usage."""


def _integer(value: int, label: str, *, upper: int = 2**53) -> int:
    if type(value) is not int or not 0 <= value <= upper:
        raise ValueError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class ResourceLimits:
    """Configured limits, NOT measured free RAM/VRAM/SSD space.

    None means unknown / unenforced; it must never be presented as infinite
    physical capacity. gpu_slots is a process-local exclusive resource.
    """

    ram_mb: int | None = None
    vram_mb: int | None = None
    scratch_mb: int | None = None
    gpu_slots: int = 1

    def __post_init__(self) -> None:
        for label in ("ram_mb", "vram_mb", "scratch_mb", "gpu_slots"):
            value = getattr(self, label)
            if value is not None:
                _integer(value, label)
        if self.gpu_slots < 1:
            raise ValueError("gpu_slots must be positive")


@dataclass(frozen=True)
class ResourceRequest:
    workload: str
    ram_mb: int = 0
    vram_mb: int = 0
    scratch_mb: int = 0
    gpu_slots: int = 0
    priority: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.workload, str) or not _NAME.fullmatch(self.workload):
            raise ValueError("invalid workload")
        for label in ("ram_mb", "vram_mb", "scratch_mb", "gpu_slots"):
            _integer(getattr(self, label), label)
        if type(self.priority) is not int or not 0 <= self.priority <= 9:
            raise ValueError("invalid priority")
        if self.vram_mb and not self.gpu_slots:
            raise ValueError("vram requires gpu_slots")


@dataclass(frozen=True)
class WeightPlacement:
    """A capacity estimate. No model backend is configured by this plan."""

    gpu_pinned_mb: int
    ram_pinned_mb: int
    streamed_from_disk_mb: int
    supported: bool
    reason: str


def plan_weight_placement(
    *, weights_mb: int, frequently_used_mb: int, ram_budget_mb: int,
    vram_budget_mb: int, gpu_working_mb: int = 0, supports_streaming: bool = False,
) -> WeightPlacement:
    """Prefer pinning recurring weights; stream the rest only if the engine can.

    A policy hint inspired by Kimi K3's trunk/expert split, not a K3 inference
    implementation or a guarantee of model compatibility/performance.
    """
    for label in ("weights_mb", "frequently_used_mb", "ram_budget_mb",
                  "vram_budget_mb", "gpu_working_mb"):
        _integer(locals()[label], label)
    if type(supports_streaming) is not bool or frequently_used_mb > weights_mb:
        raise ValueError("invalid placement parameters")
    available_gpu = max(0, vram_budget_mb - gpu_working_mb)
    gpu = min(frequently_used_mb, available_gpu)
    ram = min(frequently_used_mb - gpu, ram_budget_mb)
    streamed = weights_mb - gpu - ram
    supported = streamed == 0 or supports_streaming
    return WeightPlacement(gpu, ram, streamed, supported,
                           "planned" if supported else "streaming_not_supported")


class ResourceLease:
    """Idempotently released context-manager lease."""

    def __init__(self, manager: ResourceOrchestrator, lease_id: int):
        self._manager = manager
        self._lease_id = lease_id

    def release(self) -> None:
        self._manager._release(self._lease_id)

    def __enter__(self) -> ResourceLease:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class ResourceOrchestrator:
    """Cooperative per-process reservations with priority and FIFO ties.

    Higher priority controls only queued work; running work is never preempted.
    This is not a cross-process GPU mutex or an OS memory limit.
    """

    def __init__(self, limits: ResourceLimits | None = None):
        self.limits = limits or ResourceLimits()
        self._cv = threading.Condition(threading.RLock())
        self._active: dict[int, ResourceRequest] = {}
        self._waiting: dict[int, ResourceRequest] = {}
        self._next_id = 0

    def _usage(self) -> dict[str, int]:
        return {field: sum(getattr(request, field) for request in self._active.values())
                for field in ("ram_mb", "vram_mb", "scratch_mb", "gpu_slots")}

    def _fits(self, request: ResourceRequest) -> bool:
        usage = self._usage()
        return all(getattr(self.limits, field) is None or
                   usage[field] + getattr(request, field) <= getattr(self.limits, field)
                   for field in usage)

    def _possible(self, request: ResourceRequest) -> bool:
        return all(getattr(self.limits, field) is None or
                   getattr(request, field) <= getattr(self.limits, field)
                   for field in ("ram_mb", "vram_mb", "scratch_mb", "gpu_slots"))

    def reserve(
        self, request: ResourceRequest, *, timeout: float | None = 0,
        cancelled: Callable[[], bool] | None = None,
    ) -> ResourceLease:
        if not isinstance(request, ResourceRequest):
            raise TypeError("invalid resource request")
        if timeout is not None and (isinstance(timeout, bool) or
                                    not isinstance(timeout, (int, float)) or
                                    not 0 <= timeout <= 86400):
            raise ValueError("invalid timeout")
        if not self._possible(request):
            raise ResourceOverBudget("request_exceeds_configured_limit")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            self._next_id += 1
            lease_id = self._next_id
            self._waiting[lease_id] = request
            try:
                while True:
                    if cancelled is not None and cancelled():
                        raise ResourceCancelled("resource_request_cancelled")
                    # Highest priority first, FIFO among equal priority requests.
                    first = min(self._waiting, key=lambda lid: (-self._waiting[lid].priority, lid))
                    if first == lease_id and self._fits(request):
                        del self._waiting[lease_id]
                        self._active[lease_id] = request
                        self._cv.notify_all()
                        return ResourceLease(self, lease_id)
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise ResourceBusy("resource_busy")
                    self._cv.wait(min(remaining, 0.1) if remaining is not None else 0.1)
            finally:
                if lease_id in self._waiting:
                    del self._waiting[lease_id]
                    self._cv.notify_all()

    def _release(self, lease_id: int) -> None:
        with self._cv:
            if self._active.pop(lease_id, None) is not None:
                self._cv.notify_all()

    def snapshot(self) -> dict:
        """Read-only usage/limits; do not expose prompts, paths or credentials."""
        with self._cv:
            return {
                "scope": "process_only",
                "physical_measurements": False,
                "limits": {f: getattr(self.limits, f) for f in
                           ("ram_mb", "vram_mb", "scratch_mb", "gpu_slots")},
                "reserved": self._usage(),
                "active": len(self._active),
                "waiting": len(self._waiting),
            }


@dataclass(frozen=True)
class ResidentModel:
    name: str
    ram_mb: int
    vram_mb: int
    pinned: bool = False
    busy: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME.fullmatch(self.name):
            raise ValueError("invalid model name")
        _integer(self.ram_mb, "ram_mb")
        _integer(self.vram_mb, "vram_mb")
        if type(self.pinned) is not bool or type(self.busy) is not bool:
            raise ValueError("invalid model flags")


@dataclass(frozen=True)
class EvictionProposal:
    names: tuple[str, ...]
    unfulfilled_ram_mb: int
    unfulfilled_vram_mb: int


class ResidentModelPlanner:
    """Advisory LRU, never kills engines or unloads model data by itself."""

    def __init__(self):
        self._lock = threading.Lock()
        self._models: dict[str, tuple[ResidentModel, int]] = {}
        self._sequence = 0

    def record(self, model: ResidentModel) -> None:
        with self._lock:
            self._sequence += 1
            self._models[model.name] = (model, self._sequence)

    def propose_evictions(self, *, ram_mb: int = 0, vram_mb: int = 0) -> EvictionProposal:
        _integer(ram_mb, "ram_mb")
        _integer(vram_mb, "vram_mb")
        with self._lock:
            reclaim_ram, reclaim_vram = ram_mb, vram_mb
            names: list[str] = []
            for model, _ in sorted(self._models.values(), key=lambda entry: entry[1]):
                if reclaim_ram == 0 and reclaim_vram == 0:
                    break
                if model.pinned or model.busy:
                    continue
                # Ignore candidates that make no contribution to remaining needs.
                if not (reclaim_ram and model.ram_mb or reclaim_vram and model.vram_mb):
                    continue
                names.append(model.name)
                reclaim_ram = max(0, reclaim_ram - model.ram_mb)
                reclaim_vram = max(0, reclaim_vram - model.vram_mb)
            return EvictionProposal(tuple(names), reclaim_ram, reclaim_vram)
