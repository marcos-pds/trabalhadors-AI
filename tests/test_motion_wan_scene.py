import json
import uuid
from pathlib import Path

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


def test_studio_wan_scene_queues_vertical_workflow_inside_authorized_folder(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CENTRAL_MOTION_WORKER", "0")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("central.comfy_runtime.COMFY_RUNTIME.ensure_started", lambda config: "running")
    media_root = tmp_path / "media"
    media_root.mkdir()
    comfy_root = tmp_path / "comfy"
    (comfy_root / "models" / "diffusion_models").mkdir(parents=True)
    (comfy_root / "models" / "text_encoders").mkdir()
    (comfy_root / "models" / "vae").mkdir()
    (comfy_root / "main.py").write_text("fixture", encoding="utf-8")
    for folder, name in (
        ("diffusion_models", "wan2.1_t2v_1.3B_fp16.safetensors"),
        ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
        ("vae", "wan_2.1_vae.safetensors"),
    ):
        (comfy_root / "models" / folder / name).write_bytes(b"fixture")

    headers = {"X-Central-Request": "1"}
    payload = {
        "project_id": "23horror-pilot",
        "episode": 1,
        "scene": 2,
        "prompt": "A glass figure crossing a moonlit abandoned hallway.",
        "seed": 42,
        "frames": 81,
        "fps": 16,
    }
    with TestClient(app) as client:
        user = register(client)
        set_policy(DB, user, "full", str(media_root))
        unconfigured = client.post(
            "/api/motion/wan/scenes", headers=headers, json=payload
        )
        assert unconfigured.status_code == 503

        configured = client.post(
            "/api/motion/tools",
            headers=headers,
            json={
                "comfy_endpoint": "http://127.0.0.1:8188",
                "comfy_root": str(comfy_root),
                "executables": {},
            },
        )
        assert configured.status_code == 200, configured.text

        queued = client.post("/api/motion/wan/scenes", headers=headers, json=payload)
        assert queued.status_code == 200, queued.text
        run = queued.json()
        assert run["state"] == "queued"

        stored = DB.one(
            "SELECT root,manifest FROM motion_runs WHERE id=? AND user_id=?",
            (run["id"], user),
        )
        manifest = json.loads(stored["manifest"])
        workflow = json.loads(
            (Path(stored["root"]) / manifest["artifacts"][0]["path"]).read_text(
                encoding="utf-8"
            )
        )
        assert workflow["7"]["inputs"] == {
            "width": 288,
            "height": 512,
            "length": 81,
            "batch_size": 1,
        }
        assert workflow["1"]["inputs"]["text"] == payload["prompt"]
        assert manifest["artifacts"][1]["path"].startswith(
            "episodes/23horror-pilot/episode_01/scene_02_"
        )

        invalid = client.post(
            "/api/motion/wan/scenes",
            headers=headers,
            json={**payload, "frames": 82},
        )
        assert invalid.status_code == 422
        secret_prompt = client.post(
            "/api/motion/wan/scenes",
            headers=headers,
            json={**payload, "prompt": "api_key=example-secret"},
        )
        assert secret_prompt.status_code == 422

        missing_csrf = client.post("/api/motion/wan/scenes", json=payload)
        assert missing_csrf.status_code == 403
        assert MOTION.cancel(user, run["id"])["state"] == "cancelled"
