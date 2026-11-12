import json
import uuid
from pathlib import Path
import wave

from fastapi.testclient import TestClient

from central.computer_access import set_policy
from central.main import DB, app, MOTION


def register(client):
    response = client.post(
        "/api/register",
        headers={"X-Central-Request": "1"},
        json={
            "email": f"{uuid.uuid4().hex}@example.test",
            "password": "LocalTestPassword123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_studio_wan_episode_queues_eight_scenes_with_exactly_sixty_seconds(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CENTRAL_MOTION_WORKER", "0")
    monkeypatch.setattr("central.comfy_runtime.COMFY_RUNTIME.ensure_started", lambda config: "running")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def synthesize(directory, run_id, dialogue, seed, assignments=None, duration=60, engine='sapi', user_id=None):
        audio = directory / f"narration_{run_id}.wav"
        captions = directory / f"captions_{run_id}.json"
        with wave.open(str(audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(22050)
            stream.writeframes(b"\x00\x00" * 22050)
        captions.write_text(
            json.dumps({"language": "pt-BR", "segments": dialogue}), encoding="utf-8"
        )
        return audio, captions

    monkeypatch.setattr("central.motion_speech.synthesize_episode", synthesize)
    media_root = tmp_path / "media"
    media_root.mkdir()
    installation = tmp_path / "Central-IA" / "motion-studio"
    comfy_root = installation / "ComfyUI"
    python = installation / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fixture runtime")
    for folder in ("diffusion_models", "text_encoders", "vae"):
        (comfy_root / "models" / folder).mkdir(parents=True)
    (comfy_root / "main.py").write_text("fixture", encoding="utf-8")
    for folder, name in (
        ("diffusion_models", "wan2.1_t2v_1.3B_fp16.safetensors"),
        ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
        ("vae", "wan_2.1_vae.safetensors"),
    ):
        (comfy_root / "models" / folder / name).write_bytes(b"fixture")

    prompts = [f"Vertical horror scene {index}, cinematic shadows, no text." for index in range(1, 9)]
    headers = {"X-Central-Request": "1"}
    with TestClient(app) as client:
        user = register(client)
        set_policy(DB, user, "full", str(media_root))
        automatic = client.get("/api/motion/tools")
        assert automatic.status_code == 200, automatic.text
        assert automatic.json()["automatic_start"] is True
        assert automatic.json()["comfy_status"] == "running"
        assert automatic.json()["comfy_root"] == str(comfy_root)

        queued = client.post(
            "/api/motion/wan/episodes",
            headers=headers,
            json={
                "project_id": "horror-pilot",
                "episode": 1,
                "scene_prompts": prompts,
                "seed": 42,
            },
        )
        assert queued.status_code == 200, queued.text
        run = queued.json()
        assert run["state"] == "queued"
        assert len(run["jobs"]) == 9

        stored = DB.one(
            "SELECT root,manifest FROM motion_runs WHERE id=? AND user_id=?",
            (run["id"], user),
        )
        manifest = json.loads(stored["manifest"])
        assert len(manifest["artifacts"]) == 19
        scene_jobs = [job for job in manifest["jobs"] if job["adapter"] == "comfyui_wan"]
        assert sum(job["params"]["frames"] for job in scene_jobs) == 60 * 16
        assert [job["params"]["frames"] for job in scene_jobs] == [121] * 7 + [113]
        assert manifest["jobs"][-1]["adapter"] == "episode_assembly"
        assert manifest["jobs"][-1]["params"] == {"frames": 960, "fps": 16}
        assert manifest["artifacts"][-1]["path"].endswith(".mp4")
        for index, job in enumerate(manifest["jobs"][:-1]):
            workflow_artifact = manifest["artifacts"][index * 2]
            workflow = json.loads(
                (Path(stored["root"]) / workflow_artifact["path"]).read_text(encoding="utf-8")
            )
            assert workflow["7"]["inputs"]["length"] == job["params"]["frames"]
            assert workflow["1"]["inputs"]["text"] == prompts[index]
            assert workflow["7"]["inputs"]["width"] == 288
            assert workflow["7"]["inputs"]["height"] == 512
        assert sum(job["state"] == "queued" for job in run["jobs"]) == 9
        assert run["jobs"][-1]["id"] == "assemble"

        repeated = client.post(
            "/api/motion/wan/episodes",
            headers=headers,
            json={
                "project_id": "horror-pilot",
                "episode": 1,
                "scene_prompts": prompts,
                "seed": 43,
            },
        )
        assert repeated.status_code == 200, repeated.text
        assert len(repeated.json()["jobs"]) == 9
        assert MOTION.cancel(user, repeated.json()["id"])["state"] == "cancelled"

        invalid = client.post(
            "/api/motion/wan/episodes",
            headers=headers,
            json={"project_id": "horror-pilot", "episode": 1, "scene_prompts": prompts[:7]},
        )
        assert invalid.status_code == 422
        secret = client.post(
            "/api/motion/wan/episodes",
            headers=headers,
            json={
                "project_id": "horror-pilot",
                "episode": 1,
                "scene_prompts": [*prompts[:7], "token=example-secret"],
            },
        )
        assert secret.status_code == 422
        assert MOTION.cancel(user, run["id"])["state"] == "cancelled"
