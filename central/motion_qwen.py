"""Bundled Qwen VoiceDesign profiles for Motion Studio scenes."""
from array import array
import json
import os
from pathlib import Path
import subprocess
import tempfile
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


def engine_ready():
    python, model = assets()
    return python.is_file() and (model / 'model.safetensors').is_file() and (model / 'speech_tokenizer' / 'model.safetensors').is_file()


def available_voices():
    return [{'id': key, 'name': label} for key, (label, _) in PROFILES.items()] if engine_ready() else []


def synthesize_line(text, profile):
    if profile not in PROFILES or not engine_ready():
        raise QwenVoiceError('A voz Qwen selecionada não está disponível na Central.')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 300:
        raise QwenVoiceError('A fala é inválida.')
    python, model = assets()
    with tempfile.TemporaryDirectory(prefix='motion-qwen-') as folder:
        output = Path(folder) / 'speech.wav'
        payload = {'model': str(model), 'output': str(output), 'text': text.strip(),
                   'instruction': PROFILES[profile][1], 'seed': int(profile[:8], 16)}
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
