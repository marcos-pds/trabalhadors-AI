"""Deterministic, read-only resource telemetry tests; no GPU is required."""
import subprocess
from types import SimpleNamespace

from central import resource_telemetry as telemetry


def test_linux_meminfo_uses_available_not_free():
    report = telemetry._linux_meminfo(
        "MemTotal:        16384000 kB\n"
        "MemFree:           10000 kB\n"
        "MemAvailable:    8192000 kB\n"
    )
    assert report == {
        "status": "available", "source": "proc_meminfo",
        "total_mib": 16000, "available_mib": 8000, "used_mib": 8000,
    }


def test_malformed_memory_is_unavailable():
    for raw in ("MemTotal: 2000 kB\n", "MemTotal: bad kB\nMemAvailable: 1 kB",
                "MemTotal: 100 kB\nMemAvailable: 200 kB"):
        assert telemetry._linux_meminfo(raw)["status"] == "unavailable"


def test_gpu_csv_strictly_parsed():
    sample = "0, NVIDIA GeForce RTX 3060, 12288, 4300, 7988\n"
    device, = telemetry._parse_nvidia_csv(sample)["devices"]
    assert device["total_mib"] == 12288
    assert device["used_mib"] == 4300
    assert device["free_mib"] == 7988
    for invalid in ("", "0, Test GPU, N/A, 0, 0",
                    "0, Test GPU, 100, 200, 0",
                    "0, Test GPU, 100, 0, 100\n0, Duplicate, 100, 0, 100"):
        assert telemetry._parse_nvidia_csv(invalid)["status"] == "unavailable"


def test_gpu_probe_uses_fixed_argv_and_timeout(tmp_path):
    binary = tmp_path / "nvidia-smi"
    binary.write_bytes(b"fake")
    calls = []
    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0,
            stdout="0, NVIDIA GeForce RTX 3060, 12288, 4096, 8192\n")
    response = telemetry.gpu_snapshot(executable=str(binary), runner=runner)
    assert response["status"] == "available"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == str(binary)
    assert args[1:] == [
        "--query-gpu=index,name,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ]
    assert kwargs["timeout"] == 2 and kwargs["check"] is False


def test_gpu_probe_timeout_is_not_reported_as_zero(tmp_path):
    binary = tmp_path / "nvidia-smi"
    binary.write_bytes(b"fake")
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=2)
    sample = telemetry.gpu_snapshot(executable=str(binary), runner=timeout)
    assert sample == {"status": "unavailable", "source": "nvidia_smi", "devices": []}
    assert telemetry.gpu_snapshot(executable="missing")["status"] == "unavailable"


def test_disk_snapshot_is_read_only_and_omits_paths(tmp_path):
    snapshot = telemetry.disk_snapshot(tmp_path)
    assert snapshot["status"] == "available"
    assert snapshot["total_mib"] >= snapshot["available_mib"]
    assert str(tmp_path) not in str(snapshot)
    assert telemetry.disk_snapshot(tmp_path / "missing")["status"] == "unavailable"


def test_host_snapshot_keeps_physical_and_cooperative_values_separate(monkeypatch, tmp_path):
    monkeypatch.setattr(telemetry, "ram_snapshot", lambda: {"status": "unavailable"})
    monkeypatch.setattr(telemetry, "gpu_snapshot", lambda: {"status": "unavailable", "devices": []})
    class Reservations:
        def snapshot(self):
            return {"scope": "process_only", "reserved": {"gpu_slots": 1}}
    sample = telemetry.host_resource_snapshot(tmp_path, reservations=Reservations())
    assert sample["ram"]["status"] == "unavailable"
    assert sample["reservations"]["reserved"]["gpu_slots"] == 1
    assert "not_a_cross_process_lock" in sample["limitations"]
    assert str(tmp_path) not in str(sample)
