"""Loopback-only VoiceStudio speech provider for Motion Studio."""
from array import array
from io import BytesIO
import os
import wave

import httpx
from .voice_studio_audio import plan_script


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
        available = any(item.get('id') == 'omnivoice' and item.get('available')
                        for item in response.json().get('backends', []))
        if not available:
            return False
        models = httpx.get(f'{BASE_URL}/models', headers=_headers(), timeout=8)
        models.raise_for_status()
        return any(item.get('repo_id') == 'k2-fsa/OmniVoice' and item.get('installed')
                   for item in models.json().get('models', []))
    except (httpx.HTTPError, ValueError, TypeError):
        return False


def synthesize_line(text, voice_id, *, instructions=None):
    voices = {voice['id'] for voice in available_voices()}
    if voice_id not in voices:
        raise VoiceStudioError('O perfil de voz selecionado não existe no VoiceStudio.')
    body = {'model': 'omnivoice', 'voice': voice_id, 'input': text,
            'language': 'pt', 'num_step': 32, 'response_format': 'wav'}
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


def synthesize_narration(text, voice_id):
    """Keep a single profile while composing long narration with exact pauses."""
    if len(text) > 4096:
        raise VoiceStudioError('A narração excede o limite de 4096 caracteres.')
    try:
        plan = plan_script(text)
    except ValueError as exc:
        raise VoiceStudioError(str(exc)) from exc
    output = bytearray()
    for kind, value in plan:
        if kind == 'pause':
            output.extend(b'\0\0' * round(48000 * value / 1000))
        else:
            output.extend(synthesize_line(value, voice_id))
    return bytes(output)


def synthesize_aligned_narration(lines, voice_id, directions=None):
    """Place each spoken line in its video scene, returning one continuous WAV payload."""
    if not lines or sum(len(text) for text, _ in lines) > 4096:
        raise VoiceStudioError('A narração excede o limite de 4096 caracteres.')
    if directions is not None and len(directions) != len(lines):
        raise VoiceStudioError('As direções de voz não correspondem às cenas.')
    output = bytearray()
    for index, (text, seconds) in enumerate(lines):
        slot_samples = round(seconds * 48000)
        direction = directions[index] if directions else None
        instructions = {
            'whisper': 'Speak in a low, intimate whisper in Brazilian Portuguese, with natural suspense and clear words.',
            'breathless': 'Speak in Brazilian Portuguese with audible urgency and breathless emotion, keeping every word clear.',
            'fear': 'Speak in Brazilian Portuguese with believable fear and a slightly trembling voice. Articulate every word clearly.',
            'sad': 'Speak in Brazilian Portuguese with restrained sadness and gentle pauses. Articulate every word clearly.',
            'excited': 'Speak in Brazilian Portuguese with lively excitement and natural energy. Articulate every word clearly.',
            'angry': 'Speak in Brazilian Portuguese with controlled anger and firm emphasis. Articulate every word clearly.',
            'calm': 'Speak in Brazilian Portuguese calmly, warmly and naturally. Articulate every word clearly.',
            'suspense': 'Speak in Brazilian Portuguese with quiet tension and deliberate pacing. Articulate every word clearly.',
        }.get(direction)
        spoken = synthesize_line(text, voice_id, instructions=instructions) if instructions else synthesize_line(text, voice_id)
        spoken_samples = len(spoken) // 2
        if slot_samples <= 0 or spoken_samples > slot_samples:
            raise VoiceStudioError('Uma fala dura mais que sua cena. Reduza o texto ou aumente a cena.')
        output.extend(spoken)
        output.extend(b'\0\0' * (slot_samples - spoken_samples))
    return bytes(output)


def synthesize_directed_scenes(scenes, profiles, user_id=None):
    """Render the exact spoken beats and scripted silences inside each scene slot."""
    output = bytearray()
    for scene in scenes:
        slot_samples = round(scene['seconds'] * 48000)
        segments = []
        for beat in scene['beats']:
            if beat.get('pause_ms'):
                segments.append(('pause', b'\0\0' * round(int(beat['pause_ms']) * 48)))
            elif beat.get('text'):
                speaker = beat['speaker']
                if speaker not in profiles:
                    raise VoiceStudioError(f'Falta uma voz para {speaker}.')
                direction = beat.get('direction')
                instruction = {
                    'whisper': 'Whisper naturally in Brazilian Portuguese. Keep every word clear.',
                    'breathless': 'Speak breathlessly in Brazilian Portuguese, with clear words.',
                    'fear': 'Speak with restrained fear in Brazilian Portuguese, with clear words.',
                    'sad': 'Speak with subtle sadness in Brazilian Portuguese, with clear words.',
                    'excited': 'Speak with natural excitement in Brazilian Portuguese, with clear words.',
                    'angry': 'Speak with controlled anger in Brazilian Portuguese, with clear words.',
                    'calm': 'Speak calmly in Brazilian Portuguese, with clear words.',
                    'suspense': 'Speak with growing tension in Brazilian Portuguese, with clear words.',
                }.get(direction)
                profile = profiles[speaker]
                if len(profile) == 16:
                    from .motion_qwen import QwenVoiceError, synthesize_line as qwen_line
                    try:
                        spoken = qwen_line(beat['text'], profile, user_id, instructions=instruction)
                    except QwenVoiceError as exc:
                        raise VoiceStudioError(str(exc)) from exc
                else:
                    spoken = synthesize_line(beat['text'], profile, instructions=instruction) if instruction else synthesize_line(beat['text'], profile)
                segments.append(('speech', spoken))
        used_samples = sum(len(segment) // 2 for _, segment in segments)
        if used_samples > slot_samples:
            raise VoiceStudioError(f"A fala da cena {scene['scene']} excede {scene['seconds']:.1f}s. Ajuste o ritmo ou a duração sem cortar palavras.")
        surplus = slot_samples - used_samples
        trailing_pause = bool(segments and segments[-1][0] == 'pause')
        last_speech = max((index for index, (kind, _) in enumerate(segments) if kind == 'speech'), default=0)
        if last_speech > 0:
            tail = 0 if trailing_pause else min(surplus, 2 * 48000)
            segments.insert(last_speech, ('pause', b'\0\0' * (surplus - tail)))
            surplus = tail
        audio = b''.join(segment for _, segment in segments)
        if len(audio) // 2 > slot_samples:
            raise VoiceStudioError(f"A fala da cena {scene['scene']} excede {scene['seconds']:.1f}s. Ajuste o ritmo ou a duração sem cortar palavras.")
        output.extend(audio)
        output.extend(b'\0\0' * (slot_samples - len(audio) // 2))
    return bytes(output)


def import_voice(name, transcript, wav):
    """Save a short, authorized reference only in the local VoiceStudio profile store."""
    if len(wav) > 7_000_000 or not wav.startswith(b'RIFF') or wav[8:12] != b'WAVE':
        raise VoiceStudioError('Envie um WAV PCM de até 7 MB.')
    try:
        with wave.open(BytesIO(wav), 'rb') as source:
            seconds = source.getnframes() / source.getframerate()
            if source.getnchannels() not in (1, 2) or source.getsampwidth() != 2 or source.getcomptype() != 'NONE':
                raise VoiceStudioError('A gravação precisa ser WAV PCM de 16 bits.')
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise VoiceStudioError('A gravação WAV não pôde ser lida.') from exc
    if not 3 <= seconds <= 20:
        raise VoiceStudioError('Use de 3 a 20 segundos de fala clara.')
    try:
        response = httpx.post(f'{BASE_URL}/profiles', headers=_headers(),
            data={'name':name.strip(),'ref_text':transcript.strip(),'kind':'clone',
                  'language':'Auto','seed':'42'},
            files={'ref_audio':('referencia.wav',wav,'audio/wav')},timeout=90)
        response.raise_for_status()
        record=response.json()
    except (httpx.HTTPError,ValueError) as exc:
        raise VoiceStudioError('O VoiceStudio não salvou o perfil de voz.') from exc
    if not isinstance(record,dict) or not isinstance(record.get('id'),str) or not record['id']:
        raise VoiceStudioError('O VoiceStudio não confirmou o perfil de voz.')
    return {'id':record['id'],'name':record.get('name') or name.strip()}
