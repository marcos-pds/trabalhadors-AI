"""Contract tests: never download models or require an actual VoiceStudio installation."""
import httpx
from fastapi.testclient import TestClient

from central.main import app
from central import voice_studio


HEADERS = {"X-Central-Request": "1"}


def _user(client):
    import uuid
    response = client.post("/api/register", json={
        "email": f"voice-{uuid.uuid4().hex}@example.com", "password": "strongpasswordxyz",
    }, headers=HEADERS)
    assert response.status_code == 200, response.text


def _fake_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(voice_studio, "_client",
                        lambda timeout: httpx.AsyncClient(timeout=timeout, transport=transport))


def test_voice_routes_require_login_and_csrf():
    with TestClient(app) as client:
        assert client.get("/api/voice-studio/status").status_code in (401, 403)
        assert client.get("/api/voice-studio/voices").status_code in (401, 403)
        assert client.post("/api/voice-studio/speech", json={"text": "Olá"}).status_code in (401, 403)
        _user(client)
        assert client.post("/api/voice-studio/speech", json={"text": "Olá"}).status_code == 403
        assert client.post("/api/voice-studio/speech", json={"text": ""}, headers=HEADERS).status_code == 422


def test_voice_status_profiles_and_speech(monkeypatch):
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/v1/audio/voices":
            return httpx.Response(200, json={"voices": [
                {"type": "profile", "voice_id": "narrador", "name": "Narrador BR"},
                {"type": "openai_alias", "voice_id": "alloy", "name": "Alloy"},
            ]})
        if request.url.path == "/v1/audio/speech":
            import json
            payload = json.loads(request.content)
            assert payload["language"] == "pt"
            assert payload["model"] == "omnivoice"
            assert payload["num_step"] == 32
            assert payload["voice"] == "narrador"
            return httpx.Response(200, content=b"RIFF" + bytes(40),
                                  headers={"Content-Type": "audio/wav"})
        return httpx.Response(404)

    monkeypatch.setenv("CENTRAL_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    monkeypatch.delenv("CENTRAL_VOICESTUDIO_API_KEY", raising=False)
    _fake_client(monkeypatch, handler)

    with TestClient(app) as client:
        _user(client)
        assert client.get("/api/voice-studio/status").json()["ready"]
        assert client.get("/api/voice-studio/voices").json()["voices"] == [
            {"id": "default", "name": "Padrão"}, {"id": "narrador", "name": "Narrador BR"},
        ]
        response = client.post("/api/voice-studio/speech", headers=HEADERS,
                               json={"text": "Olá mundo", "voice": "narrador"})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("audio/wav")
        assert response.content.startswith(b"RIFF")
        assert response.headers["cache-control"] == "no-store"


def test_voice_down_and_invalid_url(monkeypatch):
    def handler(request):
        return httpx.Response(503, json={"detail": "engine unavailable"})
    _fake_client(monkeypatch, handler)
    monkeypatch.setenv("CENTRAL_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    with TestClient(app) as client:
        _user(client)
        assert client.get("/api/voice-studio/status").json()["ready"] is False
        response = client.post("/api/voice-studio/speech", headers=HEADERS,
                               json={"text": "teste"})
        assert response.status_code == 502
        assert "síntese" in response.json()["detail"]
        monkeypatch.setenv("CENTRAL_VOICESTUDIO_URL", "http://example.com:3900")
        assert client.get("/api/voice-studio/status").status_code == 503
