import pytest

from central import motion_references as references
from central.motion_contracts import ContractError


def test_reference_provider_status_is_explicit(monkeypatch, tmp_path):
    workflow = tmp_path / "reference-workflow.json"
    workflow.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CENTRAL_MOTION_REFERENCE_WORKFLOW", str(workflow))
    monkeypatch.setenv("CENTRAL_HF_TOKEN", "configured-only")
    status = references.provider_status()
    assert status["local_comfyui"]["available"] is True
    assert status["huggingface"]["available"] is True


def test_remote_reference_generation_requires_explicit_token(monkeypatch):
    monkeypatch.delenv("CENTRAL_HF_TOKEN", raising=False)
    with pytest.raises(ContractError, match="huggingface_reference_token_required"):
        references.generate_reference("huggingface", "A consistent character sheet")


def test_unknown_reference_provider_is_rejected():
    with pytest.raises(ContractError, match="unsupported_reference_provider"):
        references.generate_reference("unknown", "A scene")
