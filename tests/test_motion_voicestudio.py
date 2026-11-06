import json
import wave
from io import BytesIO

import httpx
import pytest

from central.motion_speech import SpeechError, synthesize_episode
from central.motion_voicestudio import VoiceStudioError, available_voices, engine_ready, synthesize_line


def test_catalog_only_exposes_saved_voice_profiles(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, json={'voices': [
            {'voice_id': 'alloy', 'name': 'Alloy', 'type': 'openai_alias'},
            {'voice_id': 'lara-id', 'name': 'Lara', 'type': 'profile'},
        ]}, request=httpx.Request('GET', url))
    monkeypatch.setattr('central.motion_voicestudio.httpx.get', fake_get)
    assert available_voices() == [{'id': 'lara-id', 'name': 'Lara'}]


def test_engine_readiness_requires_voxcpm2(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, json={'backends': [
            {'id': 'omnivoice', 'available': True},
            {'id': 'voxcpm2', 'available': False},
        ]}, request=httpx.Request('GET', url))
    monkeypatch.setattr('central.motion_voicestudio.httpx.get', fake_get)
    assert engine_ready() is False
    def ready_get(url, **kwargs):
        body = {'backends': [{'id': 'voxcpm2', 'available': True}]} if url.endswith('/engines/tts') else {
            'models': [{'repo_id': 'openbmb/VoxCPM2', 'installed': True}]}
        return httpx.Response(200, json=body, request=httpx.Request('GET', url))
    monkeypatch.setattr('central.motion_voicestudio.httpx.get', ready_get)
    assert engine_ready() is True


def test_speech_uses_saved_profile_id_and_resamples_wav(monkeypatch):
    monkeypatch.setattr('central.motion_voicestudio.available_voices',
                        lambda: [{'id': 'lara-id', 'name': 'Lara'}])
    sent = []
    def fake_post(url, **kwargs):
        sent.append(kwargs['json'])
        out = BytesIO()
        with wave.open(out, 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(24000)
            stream.writeframes(b'\x01\x00' * 24000)
        return httpx.Response(200, content=out.getvalue(), request=httpx.Request('POST', url))
    monkeypatch.setattr('central.motion_voicestudio.httpx.post', fake_post)
    assert len(synthesize_line('Olá', 'lara-id')) == 48000 * 2
    assert sent[0] == {'model': 'voxcpm2', 'voice': 'lara-id', 'input': 'Olá',
                       'language': 'Portuguese', 'response_format': 'wav'}
    with pytest.raises(VoiceStudioError, match='perfil de voz'):
        synthesize_line('Olá', 'missing')


def test_episode_keeps_voice_identity_across_repeated_dialogue(tmp_path, monkeypatch):
    monkeypatch.setattr('central.motion_voicestudio.available_voices',
                        lambda: [{'id': 'lara-id', 'name': 'Lara'}, {'id': 'phone-id', 'name': 'Telefone'}])
    calls = []
    def fake_line(text, voice_id):
        calls.append((text, voice_id))
        return b'\x01\x00' * 4800
    monkeypatch.setattr('central.motion_voicestudio.synthesize_line', fake_line)
    dialogue = [
        {'start': 0, 'speaker': 'Lara', 'text': 'Primeira.'},
        {'start': 2, 'speaker': 'Telefone', 'text': 'Resposta.'},
        {'start': 4, 'speaker': 'Lara', 'text': 'Segunda.'},
    ]
    audio, captions = synthesize_episode(tmp_path, 'voice-test', dialogue, 1,
                                         {'Lara': 'lara-id', 'Telefone': 'phone-id'}, 6, 'voicestudio')
    assert calls == [('Primeira.', 'lara-id'), ('Resposta.', 'phone-id'), ('Segunda.', 'lara-id')]
    assert json.loads(captions.read_text(encoding='utf-8'))['voice_profiles']['Lara'] == 'lara-id'
    with wave.open(str(audio), 'rb') as stream:
        assert stream.getnframes() == 6 * 48000
    with pytest.raises(SpeechError, match='Escolha uma voz'):
        synthesize_episode(tmp_path, 'bad', dialogue, 1, {'Lara': 'missing'}, 6, 'voicestudio')
