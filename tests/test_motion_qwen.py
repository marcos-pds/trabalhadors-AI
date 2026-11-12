from types import SimpleNamespace
from io import BytesIO
import base64
import wave

import pytest
from fastapi.testclient import TestClient

from central import motion_qwen
from central.main import app, current_user
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


def test_brazilian_voice_reference_is_owner_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(motion_qwen, 'base_ready', lambda: True)
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b'\x01\x00' * (24000 * 3))
    profile = motion_qwen.import_voice('owner', 'Caio · Brasil', 'Olá, eu sou o Caio.', buffer.getvalue())
    assert motion_qwen.available_voices('owner')[0] == profile
    assert profile not in motion_qwen.available_voices('other')
    with pytest.raises(motion_qwen.QwenVoiceError):
        motion_qwen.import_voice('owner', 'Caio', '', buffer.getvalue())


def test_qwen_import_route_requires_login_and_scopes_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(motion_qwen, 'base_ready', lambda: True)
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b'\x01\x00' * (24000 * 3))
    with TestClient(app) as client:
        assert client.get('/api/motion/qwen/voices').status_code == 401
        app.dependency_overrides[current_user] = lambda: {'id': 'owner'}
        try:
            result = client.post('/api/motion/qwen/voices/import', json={
                'name': 'Caio · Brasil', 'transcript': 'Olá, eu sou o Caio.',
                'audio_data': 'data:audio/x-wav;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii'),
            }, headers={'x-central-request': '1'})
            assert result.status_code == 200
            assert result.json() in client.get('/api/motion/qwen/voices').json()['voices']
            app.dependency_overrides[current_user] = lambda: {'id': 'other'}
            assert result.json() not in client.get('/api/motion/qwen/voices').json()['voices']
        finally:
            app.dependency_overrides.pop(current_user, None)
