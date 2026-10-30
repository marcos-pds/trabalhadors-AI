"""No external encoder needed; test the subprocess boundary with real files."""
import hashlib
from pathlib import Path
import subprocess

import pytest

from central.motion_contracts import ContractError
from central import motion_ffmpeg as runner


def manifest(profile="h264", output="result.mp4"):
    kind, path = ("video", "clip.mp4") if profile == "h264" else ("audio", "clip.wav")
    return {
        "schema_version": 1, "project_id": "lab",
        "artifacts": [
            {"id": "source", "kind": kind, "path": path,
             "provenance": {"source": "local"}},
            {"id": "target", "kind": kind, "path": output,
             "provenance": {"source": "planned", "job_id": "encode",
                            "inputs": ["source"]}}],
        "jobs": [{
            "id": "encode", "adapter": "ffmpeg", "stage": "encode",
            "inputs": ["source"], "outputs": ["target"], "params": {"profile": profile}
        }]
    }


@pytest.fixture
def lab(tmp_path, monkeypatch):
    (tmp_path / "clip.mp4").write_bytes(b"fake test source input")
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/mock/ffmpeg")
    return tmp_path


def test_successful_render_is_operator_only_and_exclusive(lab, monkeypatch):
    seen = []
    def execute(args, **opts):
        assert args[0] == "/mock/ffmpeg"
        assert args[1:5] == ["-hide_banner", "-loglevel", "error", "-nostdin"]
        assert opts["shell"] is False
        assert opts["cwd"] != str(lab)
        assert "OPENAI_API_KEY" not in opts["env"]
        assert "-protocol_whitelist" in args and args[args.index("-protocol_whitelist")+1] == "file"
        Path(args[-1]).write_bytes(b"\x00\x00\x00\x18ftypisom")
        seen.append(args)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-leak")
    monkeypatch.setattr(runner.subprocess, "run", execute)
    before = hashlib.sha256((lab / "clip.mp4").read_bytes()).hexdigest()
    result = runner.render_one(manifest(), lab, operator_approved=True)
    assert len(seen) == 1 and result["status"] == "rendered"
    assert result["sha256"] == hashlib.sha256((lab / "result.mp4").read_bytes()).hexdigest()
    assert result["operator_approved"] and result["source_unchanged"]
    assert hashlib.sha256((lab / "clip.mp4").read_bytes()).hexdigest() == before


def test_rejects_missing_approval_and_does_not_run(lab, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("process started without operator")
    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    with pytest.raises(ContractError, match="operator"):
        runner.render_one(manifest(), lab)
    assert not (lab / "result.mp4").exists()


def test_existing_destination_never_overwritten(lab, monkeypatch):
    target = lab / "result.mp4"
    target.write_bytes(b"original")
    with pytest.raises(ContractError):
        runner.render_one(manifest(), lab, operator_approved=True)
    assert target.read_bytes() == b"original"


def test_failed_render_cannot_claim_success(lab, monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda args, **opts: subprocess.CompletedProcess(args, 1))
    with pytest.raises(ContractError, match="valid output"):
        runner.render_one(manifest(), lab, operator_approved=True)
    assert not (lab / "result.mp4").exists()


def test_fake_container_signature_is_rejected(lab, monkeypatch):
    def fake(args, **opts):
        Path(args[-1]).write_bytes(b"not-video\x00\x00\x00\x00")
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runner.subprocess, "run", fake)
    with pytest.raises(ContractError, match="MP4"):
        runner.render_one(manifest(), lab, operator_approved=True)
    assert not (lab / "result.mp4").exists()


def test_timeout_fails_without_output(lab, monkeypatch):
    def fail(args, **opts):
        raise subprocess.TimeoutExpired(args, 1)
    monkeypatch.setattr(runner.subprocess, "run", fail)
    with pytest.raises(ContractError, match="timed out"):
        runner.render_one(manifest(), lab, operator_approved=True, timeout=1)
    assert not (lab / "result.mp4").exists()


def test_wav_profile_and_container_signature(lab, monkeypatch):
    (lab / "clip.wav").write_bytes(b"fake pcm source")
    def fake(args, **opts):
        assert args[args.index("-c:a")+1] == "pcm_s16le"
        Path(args[-1]).write_bytes(b"RIFF\x04\x00\x00\x00WAVEdata")
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runner.subprocess, "run", fake)
    report = runner.render_one(manifest("pcm_s16le", "render.wav"), lab, operator_approved=True)
    assert report["output"] == "render.wav"


@pytest.mark.parametrize("seconds", [0, -1, True, 181, 1.1])
def test_invalid_timeout_is_rejected(lab, seconds):
    with pytest.raises(ContractError):
        runner.render_one(manifest(), lab, operator_approved=True, timeout=seconds)
