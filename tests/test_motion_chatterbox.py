from io import BytesIO
import base64
import json
import wave
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from central import motion_chatterbox as chatterbox
from central.main import app, attach_scene_speech, current_user
from central.motion_speech import SpeechError, synthesize_episode, synthesize_scene


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


def test_scene_speech_uses_selected_voice_and_exact_frame_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(chatterbox, 'available_voices', lambda owner: [{'id': 'lara', 'name': 'Lara'}] if owner == 'owner' else [])
    calls = []
    monkeypatch.setattr(chatterbox, 'synthesize_lines', lambda lines, owner: calls.append((lines, owner)) or [b'\x01\x00' * 4800])
    audio, captions = synthesize_scene(tmp_path, 'one', 'Oi Lara.', 'Lara', 'lara', 81, 16, 'owner')
    assert calls == [([('Oi Lara.', 'lara')], 'owner')]
    with wave.open(str(audio), 'rb') as stream:
        assert stream.getframerate() == 48000
        assert stream.getnframes() == 243000
    assert json.loads(captions.read_text(encoding='utf-8'))['segments'][0]['voice_profile'] == 'lara'
    with pytest.raises(SpeechError, match='Escolha uma voz'):
        synthesize_scene(tmp_path, 'other', 'Oi', 'Lara', 'lara', 81, 16, 'other')
    monkeypatch.setattr(chatterbox, 'synthesize_lines', lambda lines, owner: [b'\x01\x00' * 300000])
    with pytest.raises(SpeechError, match='excede'):
        synthesize_scene(tmp_path, 'long', 'Fala longa', 'Lara', 'lara', 81, 16, 'owner')


def test_scene_manifest_keeps_audio_and_captions_as_scoped_artifacts(tmp_path, monkeypatch):
    def fake_speech(directory, run_id, text, speaker, profile, frames, fps, owner):
        assert (text, speaker, profile, owner) == ('Olá.', 'Lara', 'a' * 16, 'owner')
        audio, captions = directory / f'speech_{run_id}.wav', directory / f'speech_{run_id}.json'
        audio.write_bytes(reference())
        captions.write_text('{}', encoding='utf-8')
        return audio, captions
    monkeypatch.setattr('central.motion_speech.synthesize_scene', fake_speech)
    manifest = {'artifacts': [], 'jobs': [{'params': {}}]}
    data = SimpleNamespace(project_id='pilot', episode=1, frames=81, fps=16,
        speech_text='Olá.', speaker='Lara', voice_profile='a' * 16)
    attach_scene_speech(manifest, data, str(tmp_path), 'run1', 'owner')
    assert [item['kind'] for item in manifest['artifacts']] == ['audio', 'captions']
    assert manifest['jobs'][0]['params']['speech_artifact_id'] == 'speech'
    assert (tmp_path / 'MotionStudio' / manifest['artifacts'][0]['path']).is_file()


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
