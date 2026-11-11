"""Motion Studio's self-hosted Chatterbox Multilingual V3 voice provider."""
from array import array
from io import BytesIO
from pathlib import Path
import json
import math
import os
import re
import subprocess
import tempfile
import uuid
import wave


ROOT = Path(__file__).resolve().parent.parent
PROFILES = 'profiles.json'


class ChatterboxError(RuntimeError):
    pass


def voice_dir(user_id):
    if not isinstance(user_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', user_id):
        raise ChatterboxError('Conta de voz inválida.')
    return Path(os.environ.get('CENTRAL_DATA_DIR', ROOT / 'data')) / 'motion-studio' / 'voices' / 'chatterbox' / user_id


def runtime_python():
    name = 'python.exe' if os.name == 'nt' else 'python'
    return Path(os.environ.get('CENTRAL_CHATTERBOX_PYTHON') or
                Path(os.environ.get('CENTRAL_DATA_DIR', ROOT / 'data')) / 'motion-studio' /
                'chatterbox-runtime' / ('Scripts' if os.name == 'nt' else 'bin') / name)


def ptbr_assets():
    base = Path(os.environ.get('CENTRAL_DATA_DIR', ROOT / 'data')) / 'motion-studio'
    return base / 'ptbr-model', base / 'ptbr-runtime'


def ptbr_ready():
    model, code = ptbr_assets()
    return (code / 'chatterbox' / 'tts.py').is_file() and all(
        (model / name).is_file() and (model / name).stat().st_size == size
        for name, size in {
            't3_pt_br.safetensors': 2143990296,
            's3gen_v3.pt': 1056903694,
            've.pt': 5698626,
            'grapheme_mtl_merged_expanded_v1.json': 69989,
        }.items())


def engine_ready():
    return runtime_python().is_file() and ptbr_ready()


def _profiles(user_id):
    path = voice_dir(user_id) / PROFILES
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def available_voices(user_id):
    return [{'id': item['id'], 'name': item['name']} for item in _profiles(user_id)
            if isinstance(item, dict) and isinstance(item.get('id'), str)
            and re.fullmatch(r'[a-f0-9]{16}', item['id'])
            and isinstance(item.get('name'), str) and (voice_dir(user_id) / (item['id'] + '.wav')).is_file()]


def voice_settings(user_id, profile_id):
    profile = next((item for item in _profiles(user_id)
                    if isinstance(item, dict) and item.get('id') == profile_id), None)
    if not profile:
        return 0.5, 0.5
    return profile.get('exaggeration', 0.5), profile.get('cfg_weight', 0.5)


def import_voice(user_id, name, wav_bytes, *, exaggeration=0.5, cfg_weight=0.5):
    name = name.strip()
    if not 1 <= len(name) <= 80 or not 1000 <= len(wav_bytes) <= 5_000_000:
        raise ChatterboxError('Nome ou referência de voz inválidos.')
    if (type(exaggeration) not in (int, float) or not math.isfinite(exaggeration) or not 0.25 <= exaggeration <= 2.0 or
            type(cfg_weight) not in (int, float) or not math.isfinite(cfg_weight) or not 0 <= cfg_weight <= 1.0):
        raise ChatterboxError('A expressão ou o ritmo da voz está fora dos limites permitidos.')
    try:
        with wave.open(BytesIO(wav_bytes), 'rb') as stream:
            rate, channels, width = stream.getframerate(), stream.getnchannels(), stream.getsampwidth()
            seconds = stream.getnframes() / rate
            if channels != 1 or width != 2 or not 16000 <= rate <= 48000 or not 3 <= seconds <= 30:
                raise ChatterboxError('Use WAV mono PCM16 de 3 a 30 segundos.')
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise ChatterboxError('Referência WAV inválida.') from exc
    directory = voice_dir(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    profile_id = uuid.uuid4().hex[:16]
    path = directory / (profile_id + '.wav')
    path.write_bytes(wav_bytes)
    profiles = _profiles(user_id)
    profiles.append({'id': profile_id, 'name': name,
                     'exaggeration': exaggeration, 'cfg_weight': cfg_weight})
    (directory / PROFILES).write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'id': profile_id, 'name': name}


def synthesize_lines(lines, user_id, *, exaggeration=0.5, cfg_weight=0.5):
    """Generate all episode cues in one isolated Python 3.11 process."""
    if (type(exaggeration) not in (int, float) or not math.isfinite(exaggeration)
            or not 0.25 <= exaggeration <= 2.0
            or type(cfg_weight) not in (int, float) or not math.isfinite(cfg_weight)
            or not 0 <= cfg_weight <= 1.0):
        raise ChatterboxError('A expressão ou o ritmo da voz está fora dos limites permitidos.')
    python = runtime_python()
    if not python.is_file():
        raise ChatterboxError('Instale o motor Chatterbox local da Central antes de gerar falas.')
    if not ptbr_ready():
        raise ChatterboxError('Instale o modelo de voz brasileiro da Central antes de gerar falas.')
    profiles = {item['id'] for item in available_voices(user_id)}
    if any(voice_id not in profiles for _, voice_id in lines):
        raise ChatterboxError('Escolha uma voz Chatterbox da Central para cada personagem.')
    with tempfile.TemporaryDirectory(prefix='motion-chatterbox-') as folder:
        model_dir, code_dir = ptbr_assets()
        request = {'output_dir': folder, 'model_dir': str(model_dir),
                   'exaggeration': exaggeration, 'cfg_weight': cfg_weight,
                   'code_dir': str(code_dir), 'lines': [
            {'text': text, 'reference': str(voice_dir(user_id) / (voice_id + '.wav'))}
            for text, voice_id in lines]}
        try:
            result = subprocess.run([str(python), str(ROOT / 'central' / 'chatterbox_worker.py')],
                                    input=json.dumps(request, ensure_ascii=False), text=True,
                                    capture_output=True, timeout=900, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ChatterboxError('O motor Chatterbox local não respondeu.') from exc
        if result.returncode:
            raise ChatterboxError('Falha na geração com o Chatterbox local: ' + result.stderr[-500:])
        output = []
        for index in range(len(lines)):
            path = Path(folder) / f'{index:02d}.wav'
            if not path.is_file():
                raise ChatterboxError('O Chatterbox não gerou todas as falas.')
            with wave.open(str(path), 'rb') as stream:
                if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
                    raise ChatterboxError('Formato de voz Chatterbox inesperado.')
                rate = stream.getframerate()
                source = array('h')
                source.frombytes(stream.readframes(stream.getnframes()))
            if not source or not 8000 <= rate <= 96000:
                raise ChatterboxError('Áudio Chatterbox vazio ou inválido.')
            if rate == 48000:
                output.append(source.tobytes())
            else:
                samples = array('h')
                for n in range(round(len(source) * 48000 / rate)):
                    pos = n * rate / 48000
                    left = min(len(source) - 1, int(pos))
                    right = min(len(source) - 1, left + 1)
                    samples.append(round(source[left] * (1 - (pos - left)) + source[right] * (pos - left)))
                output.append(samples.tobytes())
        return output
