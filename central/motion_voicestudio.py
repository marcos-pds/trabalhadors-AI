"""Loopback-only VoiceStudio speech provider for Motion Studio."""
from array import array
from io import BytesIO
import os
import wave

import httpx


BASE_URL = 'http://127.0.0.1:3900'


class VoiceStudioError(RuntimeError):
    pass


def _headers():
    key = os.environ.get('OMNIVOICE_API_KEY')
    return {'Authorization': f'Bearer {key}'} if key else {}


def available_voices():
    try:
        response = httpx.get(f'{BASE_URL}/v1/audio/voices', headers=_headers(), timeout=8)
        response.raise_for_status()
        payload = response.json()
        entries = payload.get('voices', []) if isinstance(payload, dict) else payload
        return [{'id': str(item.get('voice_id') or item.get('id')),
                 'name': str(item.get('name') or item.get('voice_id') or item.get('id'))}
                for item in entries if isinstance(item, dict) and item.get('type') == 'profile'
                and (item.get('voice_id') or item.get('id'))]
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise VoiceStudioError('VoiceStudio não está pronto na porta local 3900.') from exc


def engine_ready():
    try:
        response = httpx.get(f'{BASE_URL}/engines/tts', headers=_headers(), timeout=8)
        response.raise_for_status()
        available = any(item.get('id') == 'voxcpm2' and item.get('available')
                        for item in response.json().get('backends', []))
        if not available:
            return False
        models = httpx.get(f'{BASE_URL}/models', headers=_headers(), timeout=8)
        models.raise_for_status()
        return any(item.get('repo_id') == 'openbmb/VoxCPM2' and item.get('installed')
                   for item in models.json().get('models', []))
    except (httpx.HTTPError, ValueError, TypeError):
        return False


def synthesize_line(text, voice_id, *, instructions=None):
    voices = {voice['id'] for voice in available_voices()}
    if voice_id not in voices:
        raise VoiceStudioError('O perfil de voz selecionado não existe no VoiceStudio.')
    body = {'model': 'voxcpm2', 'voice': voice_id, 'input': text,
            'language': 'Portuguese', 'response_format': 'wav'}
    if instructions:
        body['instructions'] = instructions
    try:
        response = httpx.post(f'{BASE_URL}/v1/audio/speech', headers=_headers(),
                              json=body, timeout=600)
        response.raise_for_status()
        with wave.open(BytesIO(response.content), 'rb') as stream:
            if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
                raise VoiceStudioError('VoiceStudio retornou áudio em formato inesperado.')
            rate = stream.getframerate()
            source = array('h')
            source.frombytes(stream.readframes(stream.getnframes()))
        if not 8000 <= rate <= 96000 or not source:
            raise VoiceStudioError('VoiceStudio retornou áudio vazio ou inválido.')
        target_rate = 48000
        if rate == target_rate:
            return source.tobytes()
        output = array('h')
        for index in range(round(len(source) * target_rate / rate)):
            position = index * rate / target_rate
            left = min(len(source)-1, int(position))
            right = min(len(source)-1, left+1)
            weight = position-left
            output.append(round(source[left]*(1-weight) + source[right]*weight))
        return output.tobytes()
    except (httpx.HTTPError, wave.Error, EOFError) as exc:
        raise VoiceStudioError('Falha ao gerar fala com o VoiceStudio local.') from exc
