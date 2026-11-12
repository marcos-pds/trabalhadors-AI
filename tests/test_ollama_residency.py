"""No Ollama installation or GPU needed; only safe read-only /api/ps probes."""
import httpx

from central.ollama_residency import (
    ollama_residency_snapshot, parse_running_models,
)


def test_parse_resident_models_and_vram_bytes():
    value = parse_running_models({"models": [
        {"name": "llama3.2:latest", "size_vram": 3 * 1024**3},
        {"model": "nomic-embed-text", "size_vram": 0},
    ]})
    assert value["status"] == "available"
    assert value["loaded_count"] == 2
    assert value["reported_vram_mib"] == 3072
    assert value["models"][1] == {"name": "nomic-embed-text", "vram_mib": 0}
    assert value["all_vram_sizes_known"] is True


def test_missing_vram_is_unknown_not_free():
    value = parse_running_models({"models": [{"name": "unknown"}]})
    assert value["loaded_count"] == 1
    assert value["all_vram_sizes_known"] is False
    assert value["reported_vram_mib"] is None
    assert value["models"][0]["vram_mib"] is None
    empty = parse_running_models({"models": []})
    assert empty["status"] == "available" and empty["loaded_count"] == 0
    assert empty["reported_vram_mib"] == 0


def test_reject_malformed_and_unsafe_local_response():
    for payload in (
        None, {"models": None}, {"models": "not a list"},
        {"models": [42]}, {"models": [{"name": "bad\nname", "size_vram": 1}]},
        {"models": [{"name": "model", "size_vram": True}]},
        {"models": [{"name": "model", "size_vram": -1}]},
        {"models": [{"name": "model", "size_vram": "1234"}]},
        {"models": [{"name": "a"}] * 65},
    ):
        response = parse_running_models(payload)
        assert response["status"] == "unavailable"
        assert response["loaded_count"] is None
        assert response["reported_vram_mib"] is None


def _transport_factory(handler, captured):
    def factory(**kwargs):
        captured.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)
    return factory


def test_http_probe_is_fixed_loopback_get_no_redirect_and_no_proxy():
    captures = []
    def handler(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/ps"
        assert request.method == "GET"
        return httpx.Response(200, json={"models": [
            {"name": "llama3.2", "size_vram": 1024**3},
        ]})
    result = ollama_residency_snapshot(
        client_factory=_transport_factory(handler, captures))
    assert result["status"] == "available"
    assert result["reported_vram_mib"] == 1024
    assert captures[0]["trust_env"] is False
    assert captures[0]["follow_redirects"] is False


def test_unreachable_malformed_and_large_probe_does_not_claim_empty():
    for code, payload in [
        (301, b"redirect"), (200, b"not json"),
        (200, b"x" * 66000),
    ]:
        result = ollama_residency_snapshot(client_factory=_transport_factory(
            lambda _request: httpx.Response(code, content=payload), []))
        assert result["status"] == "unavailable"
        assert result["loaded_count"] is None
    def unreachable(request):
        raise httpx.ConnectError("test connection refusal", request=request)
    result = ollama_residency_snapshot(
        client_factory=_transport_factory(unreachable, []))
    assert result["status"] == "unavailable"
    assert result["reported_vram_mib"] is None
