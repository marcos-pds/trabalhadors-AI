"""Read-only host RAM, GPU memory and data-volume disk telemetry.

Never downloads models, writes settings, starts backends or terminates processes.
Measurements are instantaneous, external-process allocations are included in GPU
used memory, and they are independent from cooperative reservation estimates.
"""
from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys


_MIB = 1024 * 1024
_MAX_GPUS = 16


def _memory_numbers(total: int, available: int, source: str) -> dict:
    if total <= 0 or not 0 <= available <= total:
        return {"status": "unavailable", "source": source}
    return {
        "status": "available",
        "source": source,
        "total_mib": total // _MIB,
        "available_mib": available // _MIB,
        "used_mib": (total - available) // _MIB,
    }


def _linux_meminfo(contents: str) -> dict:
    """Parse /proc/meminfo; values are KiB, not bytes."""
    fields = {}
    for line in contents.splitlines():
        name, separator, value = line.partition(":")
        if not separator or name not in ("MemTotal", "MemAvailable"):
            continue
        parts = value.split()
        if len(parts) != 2 or parts[1] != "kB" or not parts[0].isdigit():
            return {"status": "unavailable", "source": "proc_meminfo"}
        fields[name] = int(parts[0]) * 1024
    if set(fields) != {"MemTotal", "MemAvailable"}:
        return {"status": "unavailable", "source": "proc_meminfo"}
    return _memory_numbers(fields["MemTotal"], fields["MemAvailable"], "proc_meminfo")


def ram_snapshot() -> dict:
    """Windows GlobalMemoryStatusEx or Linux MemAvailable; no guessed data."""
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        try:
            success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            if success:
                return _memory_numbers(status.ullTotalPhys, status.ullAvailPhys,
                                       "windows_memory_status")
        except (AttributeError, OSError, ValueError):
            pass
        return {"status": "unavailable", "source": "windows_memory_status"}
    if sys.platform.startswith("linux"):
        try:
            return _linux_meminfo(Path("/proc/meminfo").read_text(encoding="ascii"))
        except (OSError, ValueError, UnicodeError):
            return {"status": "unavailable", "source": "proc_meminfo"}
    return {"status": "unavailable", "source": "unsupported_platform"}


def _parse_nvidia_csv(output: str) -> dict:
    """Strict output from nvidia-smi --query-gpu; reject partial/odd samples."""
    devices = []
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines or len(lines) > _MAX_GPUS:
        return {"status": "unavailable", "source": "nvidia_smi", "devices": []}
    try:
        seen = set()
        for line in lines:
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 5:
                raise ValueError("unexpected GPU record")
            index, name, total, used, free = parts
            idx = int(index)
            total, used, free = int(total), int(used), int(free)
            if (idx < 0 or idx in seen or not 0 <= used <= total or
                    not 0 <= free <= total or not name or len(name) > 120 or total <= 0):
                raise ValueError("invalid GPU sample")
            seen.add(idx)
            devices.append({
                "index": idx,
                "name": name,
                "total_mib": total,
                "used_mib": used,
                "free_mib": free,
            })
    except (ValueError, TypeError):
        return {"status": "unavailable", "source": "nvidia_smi", "devices": []}
    return {"status": "available", "source": "nvidia_smi", "devices": devices}


def gpu_snapshot(*, runner=None, executable=None) -> dict:
    """Best-effort 2-second NVIDIA probe; unknown is not zero VRAM.

    Caller-supplied runner/executable exist for deterministic tests only.
    """
    if executable is None:
        executable = shutil.which("nvidia-smi")
        if not executable and os.name == "nt":
            # NVIDIA's Windows installer commonly omits NVSMI from PATH.
            # Probe fixed system locations, never arbitrary browser-provided paths.
            roots = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                     Path(os.environ.get("WINDIR", r"C:\Windows")))
            candidates = (roots[0] / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
                          roots[1] / "System32" / "nvidia-smi.exe")
            executable = next((str(p) for p in candidates if p.is_file() and
                               not p.is_symlink()), None)
    if not executable:
        return {"status": "unavailable", "source": "nvidia_smi", "devices": []}
    try:
        binary = Path(executable)
        if not binary.is_absolute() or not binary.is_file() or binary.is_symlink():
            return {"status": "unavailable", "source": "nvidia_smi", "devices": []}
        launch = runner or subprocess.run
        result = launch(
            [str(binary), "--query-gpu=index,name,memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            timeout=2, check=False,
        )
        if result.returncode != 0 or len(result.stdout) > 8192:
            raise ValueError("GPU probe failed")
        return _parse_nvidia_csv(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "source": "nvidia_smi", "devices": []}


def disk_snapshot(data_dir: Path | str) -> dict:
    """Capacity for the disk volume containing the Central's configured data."""
    try:
        # Do not create directories on a read-only telemetry request.
        path = Path(data_dir)
        if not path.is_absolute() or not path.exists() or not path.is_dir():
            raise ValueError("invalid telemetry root")
        used = shutil.disk_usage(path)
        return _memory_numbers(used.total, used.free, "data_volume")
    except (OSError, ValueError):
        return {"status": "unavailable", "source": "data_volume"}


def host_resource_snapshot(data_dir: Path | str, *, reservations=None) -> dict:
    """Safe response for authenticated local diagnostics; no paths or tokens."""
    cooperative = reservations.snapshot() if reservations is not None else None
    return {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "scope": "host_snapshot",
        "ram": ram_snapshot(),
        "gpu": gpu_snapshot(),
        "disk": disk_snapshot(data_dir),
        "reservations": cooperative,
        "limitations": [
            "instantaneous_measurement",
            "gpu_used_includes_external_processes",
            "reservations_are_estimates",
            ("not_an_os_gpu_lock" if cooperative and cooperative.get("interprocess")
             else "not_a_cross_process_lock"),
        ],
    }
