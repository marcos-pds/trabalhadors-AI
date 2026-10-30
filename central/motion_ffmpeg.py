"""Opt-in FFmpeg render of ONE validated motion-contract job.

Not a model tool, API endpoint or sandbox. Operators must run this explicitly
on trusted local media in a private project directory. No network or installs.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .motion_contracts import ContractError, plan_jobs, scoped_path, validate_manifest

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_SECONDS = 180


def _env(temp):
    # Exclude API keys, credentials, provider variables and user HOME configs.
    allowed = ("PATH", "SystemRoot", "WINDIR")
    result = {key: os.environ[key] for key in allowed if key in os.environ}
    result.update({"HOME": str(temp), "TMP": str(temp), "TEMP": str(temp)})
    return result


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_one(manifest, project_root, *, operator_approved=False, timeout=120):
    """Create one .mp4 or .wav; fail closed without modifying original source.

    No command is executed unless the operator has explicitly approved the
    fixed ffmpeg adapter; arbitrary binaries/adapters and shell are forbidden.
    """
    if operator_approved is not True:
        raise ContractError("explicit operator approval required")
    if type(timeout) is not int or not 1 <= timeout <= MAX_SECONDS:
        raise ContractError("invalid render time limit")
    root = Path(project_root).resolve(strict=True)
    payload = validate_manifest(manifest, root)
    if len(payload["jobs"]) != 1 or payload["jobs"][0]["adapter"] != "ffmpeg":
        raise ContractError("only one ffmpeg job is supported")
    job = payload["jobs"][0]
    if len(job["inputs"]) != 1 or len(job["outputs"]) != 1:
        raise ContractError("single input and output required")
    artifacts = {item["id"]: item for item in payload["artifacts"]}
    source = scoped_path(root, artifacts[job["inputs"][0]]["path"])
    target = scoped_path(root, artifacts[job["outputs"][0]]["path"], output=True)
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ContractError("output parent must already exist")
    size = source.stat().st_size
    if not 0 < size <= MAX_INPUT_BYTES:
        raise ContractError("source exceeds local pilot limits")
    executable = shutil.which("ffmpeg")
    plan = plan_jobs(payload, root)
    if not executable or len(plan) != 1 or plan[0].status != "planned":
        raise ContractError("ffmpeg not available; no process was started")
    profile = job["params"]["profile"]
    suffix = ".mp4" if profile == "h264" else ".wav"
    if target.suffix.lower() != suffix:
        raise ContractError("output profile mismatch")
    with tempfile.TemporaryDirectory(prefix=".motion-operator-", dir=root) as folder:
        work = Path(folder)
        copied = work / ("input" + source.suffix.lower())
        stage = work / ("rendered" + suffix)
        # No symlink/hardlink is copied, only bytes, with a bounded input size.
        with source.open("rb") as inp, copied.open("xb") as out:
            shutil.copyfileobj(inp, out, 65536)
        if copied.stat().st_size != size or _digest(source) != _digest(copied):
            raise ContractError("input changed during preparation")
        command = [
            executable, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-n", "-protocol_whitelist", "file", "-i", str(copied),
            "-fs", str(MAX_OUTPUT_BYTES),
        ]
        if profile == "h264":
            command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"])
        else:
            command.extend(["-vn", "-c:a", "pcm_s16le"])
        command.append(str(stage))
        try:
            result = subprocess.run(
                command, cwd=str(work), env=_env(work), shell=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ContractError("render process failed or timed out") from None
        if result.returncode != 0 or not stage.is_file() or stage.is_symlink():
            raise ContractError("ffmpeg did not produce a valid output")
        output_size = stage.stat().st_size
        if not 12 <= output_size <= MAX_OUTPUT_BYTES:
            raise ContractError("rendered file exceeds limits or is empty")
        with stage.open("rb") as handle:
            signature = handle.read(12)
        if profile == "h264" and signature[4:8] != b"ftyp":
            raise ContractError("render is not an MP4 container")
        if profile == "pcm_s16le" and not (signature[:4] == b"RIFF" and signature[8:12] == b"WAVE"):
            raise ContractError("render is not a WAV container")
        # Refuse changed destination and linked ancestor at the commit boundary.
        scoped_path(root, artifacts[job["outputs"][0]]["path"], output=True)
        try:
            os.link(stage, target)  # Atomic no-clobber, same project filesystem.
        except OSError as exc:
            raise ContractError("output destination changed or cannot be created") from None
        return {
            "status": "rendered", "adapter": "ffmpeg", "job_id": job["id"],
            "output": artifacts[job["outputs"][0]]["path"],
            "bytes": output_size, "sha256": _digest(target),
            "operator_approved": True, "source_unchanged": _digest(source) == _digest(copied),
            "rendering_verified": "container_signature_only_not_visual_qa",
        }
