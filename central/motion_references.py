"""Reference-image providers with explicit local/remote boundaries."""
import base64
import io
import os
import secrets
import time
from pathlib import Path

import httpx

from .motion_contracts import ContractError, _text

DEFAULT_HF_MODEL = "black-forest-labs/FLUX.1-schnell"
LOCAL_MODEL = "sd_xl_base_1.0.safetensors"
IP_ADAPTER_MODEL = "ip-adapter-plus_sdxl_vit-h.safetensors"
CLIP_VISION_MODEL = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"


def identity_adapter_available(config):
    if not config or not config.comfy_root:
        return False
    root = Path(config.comfy_root)
    adapter = root / "models/ipadapter" / IP_ADAPTER_MODEL
    vision = root / "models/clip_vision" / CLIP_VISION_MODEL
    return ((root / "custom_nodes/ComfyUI_IPAdapter_plus/IPAdapterPlus.py").is_file() and
            adapter.is_file() and adapter.stat().st_size >= 800_000_000 and
            vision.is_file() and vision.stat().st_size >= 2_500_000_000)


def provider_status(config=None):
    local_model = bool(config and config.comfy_root and config.comfy_endpoint and
                       (Path(config.comfy_root) / "models" / "checkpoints" / LOCAL_MODEL).is_file())
    token = bool(os.environ.get("CENTRAL_HF_TOKEN"))
    return {
        "local_comfyui": {"available": local_model, "configured": local_model,
                           "model": LOCAL_MODEL, "identity_adapter": identity_adapter_available(config)},
        "huggingface": {"available": token, "configured": token, "model": os.environ.get("CENTRAL_HF_REFERENCE_MODEL", DEFAULT_HF_MODEL)},
    }


def generate_huggingface(prompt, model=None):
    token = os.environ.get("CENTRAL_HF_TOKEN")
    if not token:
        raise ContractError("huggingface_reference_token_required")
    prompt = _text(prompt, 4096)
    try:
        from huggingface_hub import InferenceClient
        image = InferenceClient(token=token).text_to_image(prompt, model=model or os.environ.get("CENTRAL_HF_REFERENCE_MODEL", DEFAULT_HF_MODEL))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
    except Exception as exc:
        raise ContractError("huggingface_reference_generation_failed") from exc
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"provider": "huggingface", "mime_type": "image/png", "image_data": "data:image/png;base64," + encoded}


def generate_local(prompt, config, reference_image_data=None):
    if not provider_status(config)["local_comfyui"]["available"]:
        raise ContractError("local_reference_model_required")
    prompt = _text(prompt, 4096)
    seed = secrets.randbits(32)
    prefix = "central_reference_" + secrets.token_hex(12)
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": LOCAL_MODEL}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": prompt}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1],
              "text": "different character, changed clothes, extra hands, distorted face, text, watermark"}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 576, "height": 1024, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0],
              "negative": ["3", 0], "latent_image": ["4", 0], "seed": seed, "steps": 22,
              "cfg": 6.5, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": prefix}},
    }
    input_file = None
    if reference_image_data is not None:
        if not isinstance(reference_image_data, str) or len(reference_image_data) > 8_400_000:
            raise ContractError("local_reference_image_invalid")
        header, sep, encoded = reference_image_data.partition(",")
        formats = {"data:image/png;base64": (".png", b"\x89PNG\r\n\x1a\n"),
                   "data:image/jpeg;base64": (".jpg", b"\xff\xd8\xff"),
                   "data:image/webp;base64": (".webp", b"RIFF")}
        if not sep or header not in formats:
            raise ContractError("local_reference_image_invalid")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            raise ContractError("local_reference_image_invalid") from None
        suffix, signature = formats[header]
        if not 128 <= len(image) <= 6 * 1024 * 1024 or not image.startswith(signature):
            raise ContractError("local_reference_image_invalid")
        name = prefix + suffix
        input_file = Path(config.comfy_root) / "input" / name
        input_file.parent.mkdir(parents=True, exist_ok=True)
        with input_file.open("xb") as stream:
            stream.write(image)
        workflow["8"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        if identity_adapter_available(config):
            workflow["12"] = {"class_type": "ImageScale", "inputs": {"image": ["8", 0],
                              "upscale_method": "lanczos", "width": 576, "height": 1024, "crop": "center"}}
            workflow["13"] = {"class_type": "ImageCrop", "inputs": {
                "image": ["12", 0], "width": 384, "height": 400, "x": 96, "y": 250}}
            workflow["9"] = {"class_type": "IPAdapterModelLoader", "inputs": {"ipadapter_file": IP_ADAPTER_MODEL}}
            workflow["10"] = {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": CLIP_VISION_MODEL}}
            workflow["11"] = {"class_type": "IPAdapterAdvanced", "inputs": {
                "model": ["1", 0], "ipadapter": ["9", 0], "image": ["13", 0],
                "clip_vision": ["10", 0], "weight": 0.85, "weight_type": "ease out",
                "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
                "embeds_scaling": "V only"}}
            workflow["5"]["inputs"].update(model=["11", 0])
        else:
            workflow["9"] = {"class_type": "ImageScale", "inputs": {"image": ["8", 0],
                             "upscale_method": "lanczos", "width": 576, "height": 1024, "crop": "center"}}
            workflow["10"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["9", 0], "vae": ["1", 2]}}
            workflow["5"]["inputs"].update(latent_image=["10", 0], denoise=0.28)
    endpoint = config.comfy_endpoint.rstrip("/")
    try:
        with httpx.Client(timeout=30) as client:
            queued = client.post(endpoint + "/prompt", json={"prompt": workflow})
            queued.raise_for_status()
            receipt = queued.json()
        prompt_id = receipt.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ContractError("local_reference_queue_failed")
        for _ in range(180):
            with httpx.Client(timeout=20) as client:
                response = client.get(endpoint + "/history/" + prompt_id)
                response.raise_for_status()
                record = response.json().get(prompt_id)
            if record:
                if record.get("status", {}).get("status_str") != "success":
                    raise ContractError("local_reference_generation_failed")
                images = record.get("outputs", {}).get("7", {}).get("images", [])
                if len(images) != 1 or images[0].get("type") != "output":
                    raise ContractError("local_reference_output_invalid")
                name = images[0].get("filename")
                if (not isinstance(name, str) or not name.startswith(prefix + "_") or
                        Path(name).name != name or not name.endswith(".png") or
                        images[0].get("subfolder") not in ("", None)):
                    raise ContractError("local_reference_output_invalid")
                file = Path(config.comfy_root) / "output" / name
                if not file.is_file() or not 128 <= file.stat().st_size <= 6 * 1024 * 1024:
                    raise ContractError("local_reference_output_invalid")
                data = file.read_bytes()
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ContractError("local_reference_output_invalid")
                return {"provider": "local_comfyui", "mime_type": "image/png",
                        "image_data": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}
            time.sleep(2)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise ContractError("local_reference_generation_failed") from exc
    finally:
        if input_file is not None:
            input_file.unlink(missing_ok=True)
    raise ContractError("local_reference_timeout")


def generate_reference(provider, prompt, model=None, config=None, reference_image_data=None):
    if provider == "huggingface":
        if reference_image_data is not None:
            raise ContractError("reference_image_provider_unsupported")
        return generate_huggingface(prompt, model)
    if provider == "local_comfyui":
        return generate_local(prompt, config, reference_image_data)
    raise ContractError("unsupported_reference_provider")
