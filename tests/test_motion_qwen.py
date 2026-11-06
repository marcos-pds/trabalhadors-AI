from types import SimpleNamespace
import wave

import pytest

from central import motion_qwen
from central.motion_speech import SpeechError, synthesize_scene


def test_qwen_profiles_require_local_model(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_DATA_DIR', str(tmp_path))
    assert motion_qwen.available_voices() == []
    with pytest.raises(motion_qwen.QwenVoiceError):
        motion_qwen.synthesize_line('Olá', 'ca10000000000001')


def test_qwen_scene_keeps_audio_and_caption_timed(tmp_path, monkeypatch):
    monkeypatch.setattr(motion_qwen, 'engine_ready', lambda: True)
    monkeypatch.setattr(motion_qwen, 'assets', lambda: (tmp_path / 'python', tmp_path / 'model'))
    (tmp_path / 'python').write_bytes(b'python')

    def run(command, **kwargs):
        import json
        payload = json.loads(kwargs['input'])
        assert payload['instruction'].startswith('Young Brazilian man')
        with wave.open(payload['output'], 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(b'\x01\x00' * 4800)
        return SimpleNamespace(returncode=0, stderr='')

    monkeypatch.setattr(motion_qwen.subprocess, 'run', run)
    audio, captions = synthesize_scene(tmp_path, 'caio', 'Nossa!', 'Caio',
                                       'ca10000000000001', 49, 16, 'owner')
    with wave.open(str(audio), 'rb') as stream:
        assert stream.getnframes() == 147000
    assert '"engine":"qwen"' in captions.read_text(encoding='utf-8')
    assert '"speaker":"Caio"' in captions.read_text(encoding='utf-8')


def test_qwen_rejects_unknown_voice(tmp_path):
    with pytest.raises(SpeechError, match='Escolha uma voz'):
        synthesize_scene(tmp_path, 'x', 'Oi', 'Caio', 'not-a-voice', 49, 16, 'owner')
