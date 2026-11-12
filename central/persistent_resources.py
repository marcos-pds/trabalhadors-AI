"""Durable cooperative resource leases shared by Central processes using one data dir.

A lease is a reservation estimate, never a GPU-driver lock. No process is killed,
no Ollama/Comfy model is unloaded and no user paths/credentials are returned.
SQLite serializes claims with BEGIN IMMEDIATE; heartbeat/fencing rejects stale owners.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4

from .resource_orchestrator import (
    ResourceBusy, ResourceCancelled, ResourceLimits, ResourceOverBudget,
    ResourceRequest,
)


class ResourceLeaseLost(InterruptedError):
    """A lease was replaced, expired, or could not be renewed safely."""

    def __init__(self):
        super().__init__("resource_lease_lost")


class PersistentResourceLease:
    """A fenced, automatically renewed lease. Call assert_owned at checkpoints."""

    def __init__(self, manager, token: str, generation: int):
        self._manager = manager
        self._token = token
        self._generation = generation
        self._stopped = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat, daemon=True,
                                        name="central-resource-heartbeat")
        self._thread.start()

    def _heartbeat(self):
        while not self._stopped.wait(self._manager.heartbeat_seconds):
            try:
                if not self._manager._renew(self._token, self._generation):
                    self._lost.set()
                    return
            except (sqlite3.Error, OSError):
                # Fail closed. Never silently continue after missed renewals.
                self._lost.set()
                return

    def assert_owned(self):
        if self._stopped.is_set() or self._lost.is_set():
            raise ResourceLeaseLost()
        if not self._manager._owned(self._token, self._generation):
            self._lost.set()
            raise ResourceLeaseLost()

    def release(self):
        if self._stopped.is_set():
            return
        self._stopped.set()
        self._thread.join(timeout=2)
        self._manager._release(self._token, self._generation)

    def __enter__(self):
        self.assert_owned()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


class PersistentResourceOrchestrator:
    """SQLite-backed priority/FIFO resource coordinator for local Central workers.

    Every cooperating process must use the same database path. Non-participants
    (external Ollama, manually started ComfyUI, other data dirs) are NOT managed.
    """

    _fields = ("ram_mb", "vram_mb", "scratch_mb", "gpu_slots")

    def __init__(self, path: Path | str, limits: ResourceLimits | None = None,
                 *, ttl_seconds: float = 45, heartbeat_seconds: float | None = None,
                 poll_seconds: float = .15):
        self.limits = limits or ResourceLimits()
        if not isinstance(path, (str, Path)):
            raise ValueError("invalid lease database")
        self.path = Path(path).absolute()
        if (not self.path.parent.is_dir() or self.path.parent.is_symlink() or
                self.path.is_symlink() or (self.path.exists() and not self.path.is_file())):
            raise ValueError("invalid lease database")
        if (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float))
                or not 3 <= ttl_seconds <= 3600):
            raise ValueError("invalid TTL")
        self.ttl_seconds = float(ttl_seconds)
        self.heartbeat_seconds = (float(heartbeat_seconds) if heartbeat_seconds is not None
                                  else max(.5, self.ttl_seconds / 4))
        if not 0 < self.heartbeat_seconds < self.ttl_seconds / 2:
            raise ValueError("invalid heartbeat interval")
        if not .02 <= poll_seconds <= 2:
            raise ValueError("invalid poll interval")
        self.poll_seconds = poll_seconds
        self._init_db()

    def _open(self):
        conn = sqlite3.connect(str(self.path), timeout=2, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    def _init_db(self):
        with self._open() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS resource_epochs (
                  key INTEGER PRIMARY KEY CHECK(key=1), value INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO resource_epochs(key,value) VALUES(1,0);
                CREATE TABLE IF NOT EXISTS resource_leases (
                  token TEXT PRIMARY KEY, generation INTEGER UNIQUE NOT NULL,
                  workload TEXT NOT NULL,
                  ram_mb INTEGER NOT NULL, vram_mb INTEGER NOT NULL,
                  scratch_mb INTEGER NOT NULL, gpu_slots INTEGER NOT NULL,
                  acquired_at REAL NOT NULL, heartbeat_at REAL NOT NULL,
                  expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resource_lease_expiry
                  ON resource_leases(expires_at);
                CREATE TABLE IF NOT EXISTS resource_waiters (
                  ticket INTEGER PRIMARY KEY AUTOINCREMENT,
                  token TEXT UNIQUE NOT NULL, priority INTEGER NOT NULL,
                  created_at REAL NOT NULL, seen_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resource_waiters
                  ON resource_waiters(priority DESC, ticket);
            """)

    def _possible(self, request: ResourceRequest):
        return all(getattr(self.limits, field) is None or
                   getattr(request, field) <= getattr(self.limits, field)
                   for field in self._fields)

    def _clean(self, conn, now):
        conn.execute("DELETE FROM resource_leases WHERE expires_at <= ?", (now,))
        # A waiting worker renews its ticket on each poll; abandoned tickets
        # cannot stop the queue indefinitely.
        conn.execute("DELETE FROM resource_waiters WHERE seen_at < ?", (now - 30,))

    def reserve(self, request: ResourceRequest, *, timeout: float | None = 0,
                cancelled=None) -> PersistentResourceLease:
        if not isinstance(request, ResourceRequest):
            raise TypeError("invalid resource request")
        if timeout is not None and (isinstance(timeout, bool)
                or not isinstance(timeout, (int, float)) or not 0 <= timeout <= 86400):
            raise ValueError("invalid timeout")
        if not self._possible(request):
            raise ResourceOverBudget("request_exceeds_configured_limit")
        token = uuid4().hex
        deadline = None if timeout is None else time.monotonic() + timeout
        # Acquire a durable ticket. SQLite's AUTOINCREMENT preserves FIFO across processes.
        with self._open() as conn:
            conn.execute("INSERT INTO resource_waiters(token,priority,created_at,seen_at) "
                         "VALUES(?,?,?,?)", (token, request.priority, time.time(), time.time()))
        acquired = False
        generation = None
        try:
            while True:
                if cancelled is not None and cancelled():
                    raise ResourceCancelled("resource_request_cancelled")
                now = time.time()
                with self._open() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        self._clean(conn, now)
                        conn.execute("UPDATE resource_waiters SET seen_at=? WHERE token=?",
                                     (now, token))
                        first = conn.execute("SELECT token FROM resource_waiters "
                                             "ORDER BY priority DESC,ticket LIMIT 1").fetchone()
                        if first and first[0] == token:
                            usage = conn.execute(
                                "SELECT COALESCE(SUM(ram_mb),0),COALESCE(SUM(vram_mb),0),"
                                "COALESCE(SUM(scratch_mb),0),COALESCE(SUM(gpu_slots),0) "
                                "FROM resource_leases WHERE expires_at > ?", (now,)
                            ).fetchone()
                            fits = all(getattr(self.limits, field) is None or
                                       usage[i] + getattr(request, field) <=
                                       getattr(self.limits, field)
                                       for i, field in enumerate(self._fields))
                            if fits:
                                conn.execute("UPDATE resource_epochs SET value=value+1 WHERE key=1")
                                generation = conn.execute(
                                    "SELECT value FROM resource_epochs WHERE key=1").fetchone()[0]
                                conn.execute(
                                    "INSERT INTO resource_leases VALUES(?,?,?,?,?,?,?,?,?,?)",
                                    (token, generation, request.workload, request.ram_mb,
                                     request.vram_mb, request.scratch_mb, request.gpu_slots,
                                     now, now, now + self.ttl_seconds))
                                conn.execute("DELETE FROM resource_waiters WHERE token=?",
                                             (token,))
                                acquired = True
                        conn.commit()
                    except BaseException:
                        conn.rollback()
                        raise
                if acquired:
                    # Release if heartbeat thread startup unexpectedly fails.
                    try:
                        return PersistentResourceLease(self, token, generation)
                    except BaseException:
                        self._release(token, generation)
                        raise
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise ResourceBusy("resource_busy")
                time.sleep(self.poll_seconds if remaining is None
                           else min(self.poll_seconds, remaining))
        finally:
            if not acquired:
                with self._open() as conn:
                    conn.execute("DELETE FROM resource_waiters WHERE token=?", (token,))

    def _renew(self, token: str, generation: int):
        now = time.time()
        with self._open() as conn:
            updated = conn.execute(
                "UPDATE resource_leases SET heartbeat_at=?,expires_at=? "
                "WHERE token=? AND generation=? AND expires_at>?",
                (now, now + self.ttl_seconds, token, generation, now)).rowcount
        return updated == 1

    def _owned(self, token: str, generation: int):
        with self._open() as conn:
            row = conn.execute(
                "SELECT 1 FROM resource_leases WHERE token=? AND generation=? "
                "AND expires_at > ?", (token, generation, time.time())).fetchone()
        return row is not None

    def _release(self, token: str, generation: int):
        with self._open() as conn:
            conn.execute("DELETE FROM resource_leases WHERE token=? AND generation=?",
                         (token, generation))

    def snapshot(self):
        now = time.time()
        with self._open() as conn:
            usage = conn.execute(
                "SELECT COALESCE(SUM(ram_mb),0),COALESCE(SUM(vram_mb),0),"
                "COALESCE(SUM(scratch_mb),0),COALESCE(SUM(gpu_slots),0),COUNT(*) "
                "FROM resource_leases WHERE expires_at > ?", (now,)).fetchone()
            waiting = conn.execute(
                "SELECT COUNT(*) FROM resource_waiters WHERE seen_at >= ?",
                (now - 30,)).fetchone()[0]
        return {
            "scope": "shared_data_directory",
            "physical_measurements": False,
            "limits": {key: getattr(self.limits, key) for key in self._fields},
            "reserved": dict(zip(self._fields, usage[:4])),
            "active": usage[4],
            "waiting": waiting,
            "interprocess": True,
        }
