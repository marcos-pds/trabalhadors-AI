"""Reference-image providers with explicit local/remote boundaries."""
import base64
import io
import os
from pathlib import Path

from .motion_contracts import ContractError, _text

DEFAULT_HF_MODEL = "black-forest-labs/FLUX.1-schnell"


def provider_status():
    workflow = os.environ.get("CENTRAL_MOTION_REFERENCE_WORKFLOW", "")
    token = bool(os.environ.get("CENTRAL_HF_TOKEN"))
    return {
        "local_comfyui": {"available": bool(workflow and Path(workflow).is_file()), "configured": bool(workflow)},
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


def generate_reference(provider, prompt, model=None):
    if provider == "huggingface":
        return generate_huggingface(prompt, model)
    if provider == "local_comfyui":
        if not provider_status()["local_comfyui"]["available"]:
            raise ContractError("local_reference_workflow_required")
        raise ContractError("local_reference_workflow_not_connected")
    raise ContractError("unsupported_reference_provider")
