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



def _reference_wav(seconds=4.0):
    import io
    import wave
    frames = int(24000 * seconds)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(24000)
        file.writeframes(b"\x01\x00" * frames)
    return stream.getvalue()


def test_save_reference_profile_and_reuse_it(monkeypatch):
    """Generated/imported PCM reference is stored by VoiceStudio and its ID is addressable."""
    import json
    profile_created = False

    def handler(request):
        nonlocal profile_created
        if request.url.path == "/profiles":
            assert request.method == "POST"
            assert b' name="kind"' in request.content
            assert b' name="ref_text"' in request.content
            assert b' name="ref_audio"' in request.content
            assert b"Narrador principal" in request.content
            assert b"Eram exatamente" in request.content
            assert b"RIFF" in request.content
            profile_created = True
            return httpx.Response(200, json={"id": "voz123", "name": "Narrador principal"})
        if request.url.path == "/v1/audio/voices":
            return httpx.Response(200, json={"voices": ([{
                "type": "profile", "voice_id": "voz123", "name": "Narrador principal",
            }] if profile_created else [])})
        if request.url.path == "/v1/audio/speech":
            assert json.loads(request.content)["voice"] == "voz123"
            return httpx.Response(200, content=_reference_wav(),
                                  headers={"content-type": "audio/wav"})
        return httpx.Response(404)

    monkeypatch.setenv("CENTRAL_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    _fake_client(monkeypatch, handler)
    with TestClient(app) as client:
        _user(client)
        saved = client.post("/api/voice-studio/profiles", headers=HEADERS,
                            data={"name": "Narrador principal",
                                  "ref_text": "Eram exatamente três e dezessete da madrugada."},
                            files={"ref_audio": ("referencia.wav", _reference_wav(), "audio/wav")})
        assert saved.status_code == 200, saved.text
        assert saved.json()["id"] == "voz123"
        assert saved.json()["stored_in"] == "VoiceStudio"
        assert saved.json()["reference_seconds"] == 4.0
        voices = client.get("/api/voice-studio/voices").json()["voices"]
        assert {"id": "voz123", "name": "Narrador principal"} in voices
        speech = client.post("/api/voice-studio/speech", headers=HEADERS,
                             json={"text": "Esta é a mesma voz.", "voice": "voz123", "seed": 42})
        assert speech.status_code == 200, speech.text


def test_save_reference_rejects_invalid_audio_and_csrf(monkeypatch):
    monkeypatch.setenv("CENTRAL_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    with TestClient(app) as client:
        _user(client)
        data = {"name": "Narrador", "ref_text": "Teste de narração."}
        url = "/api/voice-studio/profiles"
        valid_file = {"ref_audio": ("test.wav", _reference_wav(), "audio/wav")}
        assert client.post(url, data=data, files=valid_file).status_code == 403
        invalid = client.post(url, headers=HEADERS, data=data,
                              files={"ref_audio": ("test.wav", b"not a real wav", "audio/wav")})
        assert invalid.status_code == 415
        short = client.post(url, headers=HEADERS, data=data,
                            files={"ref_audio": ("test.wav", _reference_wav(2), "audio/wav")})
        assert short.status_code == 422
        long = client.post(url, headers=HEADERS, data=data,
                           files={"ref_audio": ("test.wav", _reference_wav(21), "audio/wav")})
        assert long.status_code == 422
        assert client.post(url, headers=HEADERS, data={"name": "Narrador", "ref_text": ""},
                           files=valid_file).status_code == 422



def test_explicit_suspense_pause_is_stitched_not_spoken(monkeypatch):
    import io
    import json
    import wave
    seen = []

    def handler(request):
        assert request.url.path == "/v1/audio/speech"
        payload = json.loads(request.content)
        seen.append(payload["input"])
        assert "[pause" not in payload["input"]
        assert payload["voice"] == "narrador"
        return httpx.Response(200, content=_reference_wav(3.0),
                              headers={"content-type": "audio/wav"})

    monkeypatch.setenv("CENTRAL_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    _fake_client(monkeypatch, handler)
    with TestClient(app) as client:
        _user(client)
        response = client.post("/api/voice-studio/speech", headers=HEADERS,
                               json={"text": "Era madrugada. [pause 700ms] Ouvi três batidas.",
                                     "voice": "narrador"})
        assert response.status_code == 200, response.text
        assert len(seen) == 2
        with wave.open(io.BytesIO(response.content)) as w:
            assert w.getframerate() == 24000
            assert abs(w.getnframes() / w.getframerate() - 6.7) < 0.01


def test_long_narration_is_split_into_short_consistent_voice_requests(monkeypatch):
    import json
    seen = []
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, content=_reference_wav(3.0),
                              headers={"content-type": "audio/wav"})
    monkeypatch.setenv("CENTRAL_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    _fake_client(monkeypatch, handler)
    text = "Era madrugada e as luzes se apagaram. " * 50
    with TestClient(app) as client:
        _user(client)
        response = client.post("/api/voice-studio/speech", headers=HEADERS,
                               json={"text": text, "voice": "narrador", "seed": 42})
        assert response.status_code == 200, response.text
        assert len(seen) >= 2
        assert all(len(s["input"]) <= 650 for s in seen)
        assert all(s["voice"] == "narrador" and s["seed"] == 42 for s in seen)
        assert int(response.headers["x-central-audio-parts"]) == len(seen)


def test_bad_pause_rejected_before_contacting_upstream(monkeypatch):
    monkeypatch.setenv("CENTRAL_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    with TestClient(app) as client:
        _user(client)
        for text in ("Olá [pause 15s] mundo.", "Olá [pause muito] mundo."):
            response = client.post("/api/voice-studio/speech", headers=HEADERS, json={"text": text})
            assert response.status_code == 422, response.text
