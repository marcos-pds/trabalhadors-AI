"""No GPU needed: assert SQL fencing, crash recovery and cross-process exclusion."""
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from central.persistent_resources import (
    PersistentResourceOrchestrator, ResourceLeaseLost,
)
from central.resource_orchestrator import (
    ResourceBusy, ResourceCancelled, ResourceOverBudget, ResourceLimits,
    ResourceRequest,
)


def manager(tmp_path, **kwargs):
    return PersistentResourceOrchestrator(tmp_path / 'gpu-leases.sqlite3',
                                          ttl_seconds=3, heartbeat_seconds=.5,
                                          poll_seconds=.03, **kwargs)


def test_separate_instances_share_one_slot_and_cleanup(tmp_path):
    first, second = manager(tmp_path), manager(tmp_path)
    with first.reserve(ResourceRequest('wan', gpu_slots=1)):
        snap = second.snapshot()
        assert snap['scope'] == 'shared_data_directory'
        assert snap['reserved']['gpu_slots'] == 1
        assert snap['active'] == 1
        with pytest.raises(ResourceBusy):
            second.reserve(ResourceRequest('ollama', gpu_slots=1), timeout=.12)
        assert second.snapshot()['waiting'] == 0
    assert second.snapshot()['reserved']['gpu_slots'] == 0
    with second.reserve(ResourceRequest('ollama', gpu_slots=1)):
        assert first.snapshot()['active'] == 1


def test_capacity_estimates_are_atomic(tmp_path):
    first = manager(tmp_path, limits=ResourceLimits(
        ram_mb=1000, vram_mb=8000, scratch_mb=1200, gpu_slots=1))
    other = manager(tmp_path, limits=first.limits)
    with first.reserve(ResourceRequest('wan', gpu_slots=1, vram_mb=7000,
                                       ram_mb=400, scratch_mb=200)):
        with pytest.raises(ResourceBusy):
            other.reserve(ResourceRequest('other', ram_mb=700), timeout=.1)
    with pytest.raises(ResourceOverBudget):
        first.reserve(ResourceRequest('huge', gpu_slots=1, vram_mb=9000))


def test_expired_owner_cannot_renew_or_release_new_epoch(tmp_path):
    first, second = manager(tmp_path), manager(tmp_path)
    old = first.reserve(ResourceRequest('wan', gpu_slots=1))
    try:
        with sqlite3.connect(str(first.path)) as connection:
            connection.execute('UPDATE resource_leases SET expires_at=?',
                               (time.time()-1,))
        with pytest.raises(ResourceLeaseLost):
            old.assert_owned()
        with second.reserve(ResourceRequest('new', gpu_slots=1)) as fresh:
            assert fresh._generation > old._generation
            old.release()
            assert second.snapshot()['active'] == 1
            fresh.assert_owned()
    finally:
        old.release()
    assert first.snapshot()['active'] == 0


def test_heartbeat_keeps_alive_and_releases(tmp_path):
    engine = manager(tmp_path)
    with engine.reserve(ResourceRequest('long_run', gpu_slots=1)) as lease:
        time.sleep(1.2)
        lease.assert_owned()
        assert engine.snapshot()['active'] == 1
    assert engine.snapshot()['active'] == 0


def test_cancellation_cleans_waiter_and_priorities_cross_instances(tmp_path):
    first, second, third = manager(tmp_path), manager(tmp_path), manager(tmp_path)
    held = first.reserve(ResourceRequest('blocking', gpu_slots=1))
    cancelled = threading.Event()
    outcome = []
    def waiting():
        try:
            second.reserve(ResourceRequest('pending', gpu_slots=1),
                           timeout=None, cancelled=cancelled.is_set)
        except ResourceCancelled:
            outcome.append('cancelled')
    thread = threading.Thread(target=waiting)
    thread.start()
    deadline = time.monotonic()+4
    while third.snapshot()['waiting'] != 1 and time.monotonic() < deadline:
        time.sleep(.02)
    assert third.snapshot()['waiting'] == 1
    cancelled.set()
    thread.join(4)
    assert outcome == ['cancelled']
    assert third.snapshot()['waiting'] == 0
    held.release()


def test_multiple_processes_coordinate_via_shared_database(tmp_path):
    db = tmp_path / 'resource-gpu.sqlite3'
    code = (
        "import sys,time;"
        "from central.persistent_resources import PersistentResourceOrchestrator as O;"
        "from central.resource_orchestrator import ResourceRequest as R;"
        "o=O(sys.argv[1],ttl_seconds=3,heartbeat_seconds=.5);"
        "lease=o.reserve(R('child',gpu_slots=1));"
        "print('READY',flush=True);"
        "time.sleep(1.5);lease.release()"
    )
    child = subprocess.Popen([sys.executable, '-c', code, str(db)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'READY'
        parent = PersistentResourceOrchestrator(db, ttl_seconds=3,
                                                heartbeat_seconds=.5)
        with pytest.raises(ResourceBusy):
            parent.reserve(ResourceRequest('parent', gpu_slots=1), timeout=.15)
        assert parent.snapshot()['active'] == 1
        assert child.wait(timeout=5) == 0
        with parent.reserve(ResourceRequest('parent', gpu_slots=1)):
            assert parent.snapshot()['active'] == 1
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)
