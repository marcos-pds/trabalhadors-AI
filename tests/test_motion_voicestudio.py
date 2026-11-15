import json
import wave
from io import BytesIO

import httpx
import pytest

from central.motion_speech import SpeechError, synthesize_episode
from central.motion_voicestudio import VoiceStudioError, available_voices, engine_ready, import_voice, synthesize_aligned_narration, synthesize_line, synthesize_narration


def test_catalog_only_exposes_saved_voice_profiles(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, json={'voices': [
            {'voice_id': 'alloy', 'name': 'Alloy', 'type': 'openai_alias'},
            {'voice_id': 'lara-id', 'name': 'Lara', 'type': 'profile'},
        ]}, request=httpx.Request('GET', url))
    monkeypatch.setattr('central.motion_voicestudio.httpx.get', fake_get)
    assert available_voices() == [{'id': 'lara-id', 'name': 'Lara'}]


def test_engine_readiness_requires_omnivoice(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(200, json={'backends': [
            {'id': 'omnivoice', 'available': False},
        ]}, request=httpx.Request('GET', url))
    monkeypatch.setattr('central.motion_voicestudio.httpx.get', fake_get)
    assert engine_ready() is False
    def ready_get(url, **kwargs):
        body = {'backends': [{'id': 'omnivoice', 'available': True}]} if url.endswith('/engines/tts') else {
            'models': [{'repo_id': 'k2-fsa/OmniVoice', 'installed': True}]}
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
    assert sent[0] == {'model': 'omnivoice', 'voice': 'lara-id', 'input': 'Olá',
                       'language': 'pt', 'num_step': 32, 'response_format': 'wav'}
    with pytest.raises(VoiceStudioError, match='perfil de voz'):
        synthesize_line('Olá', 'missing')


def test_continuous_narration_keeps_every_scene_and_pause(monkeypatch):
    calls=[]
    def fake_line(text, voice_id):
        calls.append((text,voice_id))
        return b'\x01\x00' * 4800
    monkeypatch.setattr('central.motion_voicestudio.synthesize_line',fake_line)
    result=synthesize_narration('Primeira. [pause 180ms] Segunda.','lara-id')
    assert calls==[('Primeira.','lara-id'),('Segunda.','lara-id')]
    assert len(result)==2*4800*2 + round(48000*.18)*2


def test_narration_starts_each_line_at_its_scene_boundary(monkeypatch):
    monkeypatch.setattr('central.motion_voicestudio.synthesize_line',
                        lambda text, voice_id: b'\x01\x00' * 4800)
    result=synthesize_aligned_narration([('Primeira.',1),('Segunda.',1)],'lara-id')
    assert len(result)==2*48000*2
    assert result[:2]==b'\x01\x00'
    assert result[48000*2:48000*2+2]==b'\x01\x00'
    assert result[48000*2-2:48000*2]==b'\x00\x00'
    with pytest.raises(VoiceStudioError,match='dura mais'):
        synthesize_aligned_narration([('Longa.',.05)],'lara-id')


def test_requested_whisper_and_breathlessness_reach_voice_engine(monkeypatch):
    calls = []
    def fake_line(text, voice_id, *, instructions=None):
        calls.append((text, voice_id, instructions))
        return b'\x01\x00' * 4800
    monkeypatch.setattr('central.motion_voicestudio.synthesize_line', fake_line)
    synthesize_aligned_narration([('Segredo.', 1), ('Corra.', 1)], 'narrador-id',
                                 directions=['whisper', 'breathless'])
    assert calls[0][1] == calls[1][1] == 'narrador-id'
    assert 'whisper' in calls[0][2]
    assert 'breathless' in calls[1][2]


def test_import_creates_a_local_profile_from_short_pcm_reference(monkeypatch):
    source=BytesIO()
    with wave.open(source,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(24000)
        stream.writeframes(b'\0\0'*24000*4)
    sent=[]
    def fake_post(url,**kwargs):
        sent.append((url,kwargs['data']['ref_text'],kwargs['files']['ref_audio'][1]))
        return httpx.Response(200,json={'id':'443b36e2','name':'Minha voz'},request=httpx.Request('POST',url))
    monkeypatch.setattr('central.motion_voicestudio.httpx.post',fake_post)
    assert import_voice('Minha voz','Texto exato.',source.getvalue())['id']=='443b36e2'
    assert sent[0][0].endswith('/profiles')
    assert sent[0][1]=='Texto exato.'
    short=BytesIO()
    with wave.open(short,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(24000)
        stream.writeframes(b'\0\0'*24000)
    with pytest.raises(VoiceStudioError,match='3 a 20'):
        import_voice('Curta','Texto',short.getvalue())


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
