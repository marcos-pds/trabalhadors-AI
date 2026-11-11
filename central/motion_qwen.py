"""Bundled Qwen VoiceDesign profiles for Motion Studio scenes."""
from array import array
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
import wave

ROOT = Path(__file__).resolve().parent.parent
PROFILES = {
    'ca10000000000001': ('Caio · expressivo', 'Young Brazilian man from São Paulo. Clear natural Brazilian Portuguese, warm, curious, lively and conversational.'),
    '1a2a000000000002': ('Lara · expressiva', 'Young Brazilian woman from São Paulo. Clear natural Brazilian Portuguese, warm, confident, lively and conversational.'),
    'a110000000000003': ('Narradora · expressiva', 'Adult Brazilian woman. Clear natural Brazilian Portuguese, expressive storytelling, warm and conversational.'),
}


class QwenVoiceError(RuntimeError):
    pass


def assets():
    base = Path(os.environ.get('CENTRAL_DATA_DIR', ROOT / 'data')) / 'motion-studio'
    return (base / 'qwen-runtime' / ('Scripts' if os.name == 'nt' else 'bin') /
            ('python.exe' if os.name == 'nt' else 'python'), base / 'qwen-model')


def base_model():
    return Path(os.environ.get('CENTRAL_DATA_DIR', ROOT / 'data')) / 'motion-studio' / 'qwen-base-model'


def voice_dir(user_id):
    if not isinstance(user_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', user_id):
        raise QwenVoiceError('Conta de voz inválida.')
    return Path(os.environ.get('CENTRAL_DATA_DIR', ROOT / 'data')) / 'motion-studio' / 'voices' / 'qwen' / user_id


def _profiles(user_id):
    path = voice_dir(user_id) / 'profiles.json'
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def base_ready():
    python, _ = assets()
    model = base_model()
    return python.is_file() and (model / 'model.safetensors').is_file() and (model / 'speech_tokenizer' / 'model.safetensors').is_file()


def engine_ready():
    python, model = assets()
    return python.is_file() and (model / 'model.safetensors').is_file() and (model / 'speech_tokenizer' / 'model.safetensors').is_file()


def available_voices(user_id=None):
    voices = []
    if user_id is not None and base_ready():
        voices.extend({'id': item['id'], 'name': item['name']} for item in _profiles(user_id)
                      if isinstance(item, dict) and isinstance(item.get('id'), str)
                      and re.fullmatch(r'[a-f0-9]{16}', item['id'])
                      and isinstance(item.get('name'), str)
                      and isinstance(item.get('transcript'), str)
                      and (voice_dir(user_id) / (item['id'] + '.wav')).is_file())
    if engine_ready():
        voices.extend({'id': key, 'name': label} for key, (label, _) in PROFILES.items())
    return voices


def import_voice(user_id, name, transcript, wav_bytes):
    if not base_ready():
        raise QwenVoiceError('Instale o modelo Qwen Base local antes de importar uma voz.')
    name, transcript = name.strip(), transcript.strip()
    if not 1 <= len(name) <= 80 or not 1 <= len(transcript) <= 300 or not 1000 <= len(wav_bytes) <= 5_000_000:
        raise QwenVoiceError('Nome, transcrição ou áudio inválido.')
    try:
        with wave.open(BytesIO(wav_bytes), 'rb') as stream:
            rate, channels, width = stream.getframerate(), stream.getnchannels(), stream.getsampwidth()
            seconds = stream.getnframes() / rate
            if channels != 1 or width != 2 or not 16000 <= rate <= 48000 or not 3 <= seconds <= 30:
                raise QwenVoiceError('Use WAV mono PCM16 de 3 a 30 segundos.')
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise QwenVoiceError('Referência WAV inválida.') from exc
    directory = voice_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    profile_id = uuid.uuid4().hex[:16]
    (directory / (profile_id + '.wav')).write_bytes(wav_bytes)
    profiles = _profiles(user_id)
    profiles.append({'id': profile_id, 'name': name, 'transcript': transcript})
    (directory / 'profiles.json').write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'id': profile_id, 'name': name}


def synthesize_line(text, profile, user_id=None):
    clone = next((item for item in _profiles(user_id)
                  if isinstance(item, dict) and item.get('id') == profile), None) if user_id is not None else None
    if profile not in PROFILES and (not clone or not base_ready()):
        raise QwenVoiceError('A voz Qwen selecionada não está disponível na Central.')
    if profile in PROFILES and not engine_ready():
        raise QwenVoiceError('A voz Qwen selecionada não está disponível na Central.')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 300:
        raise QwenVoiceError('A fala é inválida.')
    python, model = assets()
    with tempfile.TemporaryDirectory(prefix='motion-qwen-') as folder:
        output = Path(folder) / 'speech.wav'
        payload = {'model': str(base_model() if clone else model), 'output': str(output), 'text': text.strip(),
                   'seed': int(profile[:8], 16)}
        if clone:
            payload.update(reference=str(voice_dir(user_id) / (profile + '.wav')),
                           transcript=clone['transcript'])
        else:
            payload['instruction'] = PROFILES[profile][1]
        try:
            result = subprocess.run([str(python), str(ROOT / 'central' / 'qwen_worker.py')],
                                    input=json.dumps(payload, ensure_ascii=False), text=True,
                                    capture_output=True, timeout=600, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QwenVoiceError('O motor Qwen local não respondeu.') from exc
        if result.returncode or not output.is_file():
            raise QwenVoiceError('Falha na geração da voz Qwen: ' + result.stderr[-300:])
        with wave.open(str(output), 'rb') as stream:
            if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or not 8000 <= stream.getframerate() <= 96000:
                raise QwenVoiceError('O formato do áudio Qwen é inválido.')
            rate = stream.getframerate()
            source = array('h')
            source.frombytes(stream.readframes(stream.getnframes()))
        if not source:
            raise QwenVoiceError('A voz Qwen retornou áudio vazio.')
        if rate == 48000:
            return source.tobytes()
        samples = array('h')
        for index in range(round(len(source) * 48000 / rate)):
            position = index * rate / 48000
            left = min(len(source) - 1, int(position))
            right = min(len(source) - 1, left + 1)
            samples.append(round(source[left] * (1 - position + left) + source[right] * (position - left)))
        return samples.tobytes()
