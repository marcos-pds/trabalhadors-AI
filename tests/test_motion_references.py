import pytest
from types import SimpleNamespace

from central import motion_references as references
from central.motion_contracts import ContractError, MotionConfig


def test_reference_provider_status_is_explicit(monkeypatch, tmp_path):
    checkpoint = tmp_path / "models" / "checkpoints" / references.LOCAL_MODEL
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"model")
    monkeypatch.setenv("CENTRAL_HF_TOKEN", "configured-only")
    status = references.provider_status(MotionConfig(comfy_root=str(tmp_path),
        comfy_endpoint="http://127.0.0.1:8188"))
    assert status["local_comfyui"]["available"] is True
    assert status["huggingface"]["available"] is True


def test_local_reference_uses_fixed_model_and_returns_one_png(tmp_path, monkeypatch):
    checkpoint = tmp_path / "models" / "checkpoints" / references.LOCAL_MODEL
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"model")
    output = tmp_path / "output"
    output.mkdir()
    seen = []

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            assert url == "http://127.0.0.1:8188/prompt"
            seen.append(json["prompt"])
            name = seen[-1]["7"]["inputs"]["filename_prefix"] + "_00001_.png"
            (output / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 128)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"prompt_id": "owned"})
        def get(self, url):
            assert url.endswith("/history/owned")
            name = seen[-1]["7"]["inputs"]["filename_prefix"] + "_00001_.png"
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "owned": {"status": {"status_str": "success"}, "outputs": {
                    "7": {"images": [{"filename": name, "type": "output", "subfolder": ""}]}}}})

    monkeypatch.setattr(references.httpx, "Client", Client)
    result = references.generate_reference("local_comfyui", "Caio in a lab", config=MotionConfig(
        comfy_root=str(tmp_path), comfy_endpoint="http://127.0.0.1:8188"))
    assert result["image_data"].startswith("data:image/png;base64,")
    assert seen[0]["1"]["inputs"]["ckpt_name"] == references.LOCAL_MODEL
    assert seen[0]["2"]["inputs"]["text"] == "Caio in a lab"


def test_remote_reference_generation_requires_explicit_token(monkeypatch):
    monkeypatch.delenv("CENTRAL_HF_TOKEN", raising=False)
    with pytest.raises(ContractError, match="huggingface_reference_token_required"):
        references.generate_reference("huggingface", "A consistent character sheet")


def test_unknown_reference_provider_is_rejected():
    with pytest.raises(ContractError, match="unsupported_reference_provider"):
        references.generate_reference("unknown", "A scene")


def test_remote_provider_rejects_image_conditioning():
    with pytest.raises(ContractError, match="reference_image_provider_unsupported"):
        references.generate_reference("huggingface", "A scene", reference_image_data="data:image/png;base64,AA==")


def test_local_reference_rejects_corrupt_anchor(tmp_path):
    checkpoint = tmp_path / "models" / "checkpoints" / references.LOCAL_MODEL
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"model")
    with pytest.raises(ContractError, match="local_reference_image_invalid"):
        references.generate_local("Caio in the lab", MotionConfig(
            comfy_root=str(tmp_path), comfy_endpoint="http://127.0.0.1:8188"),
            "data:image/png;base64,AAAA")


def test_identity_adapter_uses_reference_without_locking_scene_latent(tmp_path, monkeypatch):
    import base64
    checkpoint = tmp_path / "models" / "checkpoints" / references.LOCAL_MODEL
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"model")
    (tmp_path / "output").mkdir()
    monkeypatch.setattr(references, "identity_adapter_available", lambda config: True)
    seen = []

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            seen.append(json["prompt"])
            name = seen[-1]["7"]["inputs"]["filename_prefix"] + "_00001_.png"
            (tmp_path / "output" / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 128)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"prompt_id": "owned"})
        def get(self, url):
            name = seen[-1]["7"]["inputs"]["filename_prefix"] + "_00001_.png"
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "owned": {"status": {"status_str": "success"}, "outputs": {
                    "7": {"images": [{"filename": name, "type": "output", "subfolder": ""}]}}}})

    monkeypatch.setattr(references.httpx, "Client", Client)
    anchor = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 128).decode()
    references.generate_local("Caio on a rainy street", MotionConfig(
        comfy_root=str(tmp_path), comfy_endpoint="http://127.0.0.1:8188"), anchor)
    workflow = seen[0]
    assert workflow["5"]["inputs"]["latent_image"] == ["4", 0]
    assert workflow["5"]["inputs"]["model"] == ["11", 0]
    assert workflow["11"]["class_type"] == "IPAdapterAdvanced"
    assert workflow["11"]["inputs"]["weight"] == 0.85
    assert workflow["11"]["inputs"]["image"] == ["13", 0]
    assert workflow["13"]["class_type"] == "ImageCrop"
