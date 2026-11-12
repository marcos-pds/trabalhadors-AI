"""Read-only Ollama model residency via its local, documented GET /api/ps.

This is NOT a scheduler lock, a permission to unload or an assertion that GPU
memory is free. No model commands, arbitrary URLs, credentials or user prompts.
"""
from __future__ import annotations

import json

import httpx

_OLLAMA_PS = "http://127.0.0.1:11434/api/ps"
_MAX_BODY = 65536
_MAX_MODELS = 64
_MIB = 1024 * 1024


def _unavailable(reason: str) -> dict:
    return {
        "status": "unavailable",
        "source": "ollama_api_ps",
        "reason": reason,
        "models": [],
        "loaded_count": None,
        "reported_vram_mib": None,
        "all_vram_sizes_known": False,
    }


def parse_running_models(payload: object) -> dict:
    """Conservative validation: omitted VRAM estimates are unknown, never zero."""
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return _unavailable("invalid_response")
    raw_models = payload["models"]
    if len(raw_models) > _MAX_MODELS:
        return _unavailable("invalid_response")
    parsed = []
    known = True
    total_bytes = 0
    for item in raw_models:
        if not isinstance(item, dict):
            return _unavailable("invalid_response")
        name = item.get("name") or item.get("model")
        if (not isinstance(name, str) or not name or len(name) > 128 or
                not name.isprintable()):
            return _unavailable("invalid_response")
        raw_vram = item.get("size_vram")
        if raw_vram is None:
            known = False
            vram_mib = None
        elif type(raw_vram) is int and 0 <= raw_vram <= 2**60:
            total_bytes += raw_vram
            vram_mib = raw_vram // _MIB
        else:
            return _unavailable("invalid_response")
        parsed.append({"name": name, "vram_mib": vram_mib})
    return {
        "status": "available",
        "source": "ollama_api_ps",
        "models": parsed,
        "loaded_count": len(parsed),
        "reported_vram_mib": total_bytes // _MIB if known else None,
        "all_vram_sizes_known": known,
    }


def ollama_residency_snapshot(*, client_factory=None) -> dict:
    """Probe local loopback only; never use endpoint strings from the browser.

    Network failures and malformed responses are reported as unavailable,
    not as an empty model list. trust_env=False prevents proxy redirection.
    A bounded response avoids untrusted local-server memory exhaustion.
    """
    factory = client_factory or httpx.Client
    try:
        with factory(timeout=httpx.Timeout(2.0, connect=0.6),
                     trust_env=False, follow_redirects=False) as client:
            with client.stream("GET", _OLLAMA_PS) as response:
                if response.status_code != 200:
                    return _unavailable("http_error")
                chunks = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_BODY:
                        return _unavailable("response_too_large")
                    chunks.append(chunk)
        return parse_running_models(json.loads(b"".join(chunks)))
    except (httpx.HTTPError, OSError, ValueError, UnicodeDecodeError):
        return _unavailable("connection_or_parse_error")
