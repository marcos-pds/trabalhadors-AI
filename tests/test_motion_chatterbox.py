from io import BytesIO
import base64
import json
import wave

from fastapi.testclient import TestClient
import pytest

from central import motion_chatterbox as chatterbox
from central.main import app, current_user
from central.motion_speech import synthesize_episode


def reference():
    output = BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(b'\x01\x00' * (24000 * 4))
    return output.getvalue()


def test_references_are_scoped_to_the_owner(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_DATA_DIR', str(tmp_path))
    profile = chatterbox.import_voice('owner', 'Lara', reference())
    assert chatterbox.available_voices('owner') == [profile]
    assert chatterbox.available_voices('other') == []
    with pytest.raises(chatterbox.ChatterboxError):
        chatterbox.import_voice('owner', 'Invalid', b'not a wav')


def test_episode_batches_lines_and_preserves_character_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(chatterbox, 'available_voices', lambda owner: [{'id': 'lara', 'name': 'Lara'}])
    calls = []

    def fake_lines(lines, owner):
        calls.append((lines, owner))
        return [b'\x01\x00' * 4800 for _ in lines]

    monkeypatch.setattr(chatterbox, 'synthesize_lines', fake_lines)
    dialogue = [{'start': 0, 'speaker': 'Lara', 'text': 'Primeira.'},
                {'start': 2, 'speaker': 'Lara', 'text': 'Segunda.'}]
    audio, captions = synthesize_episode(tmp_path, 'test', dialogue, 1,
                                         {'Lara': 'lara'}, 5, 'chatterbox', 'owner')
    assert calls == [([('Primeira.', 'lara'), ('Segunda.', 'lara')], 'owner')]
    assert json.loads(captions.read_text(encoding='utf-8'))['engine'] == 'chatterbox'
    with wave.open(str(audio), 'rb') as stream:
        assert stream.getnframes() == 5 * 48000


def test_missing_runtime_fails_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_DATA_DIR', str(tmp_path))
    with pytest.raises(chatterbox.ChatterboxError, match='Instale o motor'):
        chatterbox.synthesize_lines([], 'owner')


def test_import_route_requires_login_and_scopes_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        assert client.get('/api/motion/voices').status_code == 401
        app.dependency_overrides[current_user] = lambda: {'id': 'owner'}
        try:
            result = client.post('/api/motion/voices/import', json={
                'name': 'Lara', 'audio_data': base64.b64encode(reference()).decode('ascii'),
            }, headers={'x-central-request': '1'})
            assert result.status_code == 200
            assert client.get('/api/motion/voices').json()['voices'] == [result.json()]
            app.dependency_overrides[current_user] = lambda: {'id': 'other'}
            assert client.get('/api/motion/voices').json()['voices'] == []
        finally:
            app.dependency_overrides.pop(current_user, None)
