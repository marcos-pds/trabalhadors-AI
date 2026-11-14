"""Local VoiceStudio adapter. No VoiceStudio code is vendored into Central."""
import io
import os
import wave
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field


MAX_AUDIO_BYTES = 30 * 1024 * 1024
MAX_REFERENCE_BYTES = 12 * 1024 * 1024


class SpeechInput(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    model: str = Field(default="omnivoice", min_length=1, max_length=100)
    voice: str = Field(default="default", min_length=1, max_length=160)
    language: str = Field(default="pt", min_length=2, max_length=12)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    steps: int = Field(default=32, ge=8, le=64)
    instructions: str = Field(default="", max_length=700)
    seed: int | None = Field(default=None, ge=0)


def _settings():
    # The URL and secret are admin-controlled; never accept a caller-supplied URL.
    base = os.getenv("CENTRAL_VOICESTUDIO_URL", "http://127.0.0.1:3900").strip().rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise HTTPException(503, "CENTRAL_VOICESTUDIO_URL inválida.")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1", "voicestudio"):
        raise HTTPException(503, "Para VoiceStudio remoto use HTTPS e uma chave de API.")
    return base, os.getenv("CENTRAL_VOICESTUDIO_API_KEY", "").strip()


def _headers(key):
    return {"Authorization": "Bearer " + key} if key else {}


def _client(timeout):
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


def attach_voice_studio(app, current_user, require_csrf):
    """Attach authenticated routes using Central's existing session and CSRF checks."""
    router = APIRouter(prefix="/api/voice-studio", tags=["VoiceStudio"])

    @router.get("/status")
    async def studio_status(user=Depends(current_user)):
        base, key = _settings()
        try:
            async with _client(httpx.Timeout(6.0, connect=3.0)) as client:
                response = await client.get(base + "/health", headers=_headers(key))
                response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError):
            return {"ready": False, "engine": "omnivoice"}
        return {"ready": True, "engine": "omnivoice"}

    @router.get("/voices")
    async def studio_voices(user=Depends(current_user)):
        base, key = _settings()
        try:
            async with _client(httpx.Timeout(12.0, connect=4.0)) as client:
                response = await client.get(base + "/v1/audio/voices", headers=_headers(key))
                response.raise_for_status()
                data = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            raise HTTPException(503, "Não foi possível consultar as vozes do VoiceStudio.")
        voices = [{"id": "default", "name": "Padrão"}]
        for item in data.get("voices", []):
            if not isinstance(item, dict) or item.get("type") != "profile":
                continue
            identifier = item.get("voice_id")
            name = item.get("name")
            if isinstance(identifier, str) and identifier and isinstance(name, str):
                voices.append({"id": identifier, "name": name[:120]})
        return {"voices": voices}

    @router.post("/speech")
    async def studio_speech(data: SpeechInput, request: Request, user=Depends(current_user)):
        require_csrf(request)
        base, key = _settings()
        payload = {
            "model": data.model, "input": data.text, "voice": data.voice,
            "language": data.language, "speed": data.speed, "num_step": data.steps,
            "response_format": "wav",
        }
        if data.instructions.strip():
            payload["instructions"] = data.instructions.strip()
        if data.seed is not None:
            payload["seed"] = data.seed
        chunks = []
        size = 0
        try:
            async with _client(httpx.Timeout(630.0, connect=8.0)) as client:
                async with client.stream("POST", base + "/v1/audio/speech",
                                         json=payload, headers=_headers(key)) as upstream:
                    if upstream.status_code == 429:
                        raise HTTPException(429, "VoiceStudio ocupado. Tente novamente após a geração atual.")
                    if upstream.status_code in (401, 403):
                        raise HTTPException(503, "Credencial do VoiceStudio inválida ou ausente.")
                    if upstream.status_code >= 400:
                        raise HTTPException(502, "Falha na síntese. Confira motor, modelo e perfil de voz no VoiceStudio.")
                    if not upstream.headers.get("content-type", "").lower().startswith(("audio/", "application/octet-stream")):
                        raise HTTPException(502, "VoiceStudio não retornou áudio.")
                    async for chunk in upstream.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_AUDIO_BYTES:
                            raise HTTPException(413, "O áudio excedeu o limite de 30 MB.")
                        chunks.append(chunk)
        except httpx.TimeoutException:
            raise HTTPException(504, "Tempo limite de síntese excedido. Tente um trecho menor.")
        except httpx.RequestError:
            raise HTTPException(503, "VoiceStudio indisponível. Inicie o serviço local na porta 3900.")
        audio = b"".join(chunks)
        if not audio:
            raise HTTPException(502, "VoiceStudio retornou áudio vazio.")
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store",
                         "X-Content-Type-Options": "nosniff"})


    @router.post("/profiles")
    async def studio_save_profile(
        request: Request,
        name: str = Form(..., min_length=1, max_length=80),
        ref_text: str = Form(..., min_length=1, max_length=1000),
        ref_audio: UploadFile = File(...),
        user=Depends(current_user),
    ):
        """Save a reusable reference voice in VoiceStudio's persistent profile store.

        Audio never enters Central's database or repository. Profiles are shared
        with other users of the same configured VoiceStudio instance.
        """
        require_csrf(request)
        if not name.strip() or not ref_text.strip():
            raise HTTPException(422, "Informe o nome e a transcrição exata da amostra.")
        if not (ref_audio.filename or "").lower().endswith(".wav"):
            raise HTTPException(415, "Envie um arquivo WAV para criar o perfil.")
        audio = await ref_audio.read(MAX_REFERENCE_BYTES + 1)
        if len(audio) > MAX_REFERENCE_BYTES:
            raise HTTPException(413, "A amostra excedeu o limite de 12 MB.")
        if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
            raise HTTPException(415, "O arquivo não contém áudio WAV válido.")
        try:
            with wave.open(io.BytesIO(audio), "rb") as source:
                seconds = source.getnframes() / source.getframerate()
                if source.getnchannels() not in (1, 2):
                    raise ValueError("Número de canais não suportado.")
        except (wave.Error, ValueError, ZeroDivisionError, EOFError):
            raise HTTPException(415, "Utilize WAV PCM válido, de preferência 24 kHz.")
        if not 3 <= seconds <= 20:
            raise HTTPException(422, "Use 3 a 20 segundos de fala clara e contínua.")
        base, key = _settings()
        try:
            async with _client(httpx.Timeout(90.0, connect=8.0)) as client:
                upstream = await client.post(
                    base + "/profiles",
                    headers=_headers(key),
                    data={
                        "name": name.strip(),
                        "ref_text": ref_text.strip(),
                        "kind": "clone",
                        "language": "Auto",
                        "seed": "42",
                    },
                    files={"ref_audio": ("referencia.wav", audio, "audio/wav")},
                )
                if upstream.status_code in (401, 403):
                    raise HTTPException(503, "O VoiceStudio recusou a autenticação.")
                if upstream.status_code >= 400:
                    raise HTTPException(502, "O VoiceStudio recusou o perfil. Confira o WAV e a transcrição.")
                record = upstream.json()
        except httpx.TimeoutException:
            raise HTTPException(504, "Tempo limite ao salvar o perfil.")
        except httpx.RequestError:
            raise HTTPException(503, "VoiceStudio indisponível ao salvar o perfil.")
        except ValueError:
            raise HTTPException(502, "Resposta inválida ao salvar o perfil.")
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise HTTPException(502, "O VoiceStudio não confirmou o perfil.")
        return {
            "id": record["id"],
            "name": record.get("name", name.strip()),
            "stored_in": "VoiceStudio",
            "reference_seconds": round(seconds, 2),
        }

    app.include_router(router)
