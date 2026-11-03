"""Create timed narration with VoiceStudio or the legacy Windows SAPI motor."""
from array import array
import json
import math
import random
import tempfile
import wave
from pathlib import Path


VOICE_PROFILES = {
    'lara': {'label': 'Lara · natural', 'rate': -1, 'pitch': 0},
    'telefone': {'label': 'Voz ao telefone · aguda', 'rate': -1, 'pitch': 3},
    'porta': {'label': 'Voz atrás da porta · grave', 'rate': -1, 'pitch': -1},
}
DEFAULT_VOICES = {'Lara': 'lara', 'Voz desconhecida': 'telefone', 'Voz atrás da porta': 'porta'}


class SpeechError(RuntimeError):
    """Local Portuguese speech synthesis is unavailable or invalid."""


def resolve_voices(dialogue, assignments=None):
    assignments = assignments or {}
    if any(value not in VOICE_PROFILES for value in assignments.values()):
        raise SpeechError('O perfil de voz selecionado não existe.')
    return {cue['speaker']: assignments.get(cue['speaker'], DEFAULT_VOICES.get(cue['speaker'], 'lara')) for cue in dialogue}


def synthesize_episode(directory, run_id, dialogue, seed, assignments=None, duration=60, engine='sapi'):
    directory = Path(directory)
    audio_path = directory / f'narration_{run_id}.wav'
    captions_path = directory / f'captions_{run_id}.json'
    if engine not in ('sapi', 'voicestudio'):
        raise SpeechError('Motor de voz desconhecido.')
    pythoncom = None
    if engine == 'sapi':
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise SpeechError('A voz local pt-BR do Windows não está disponível nesta instalação.') from exc
        pythoncom.CoInitialize()
    try:
        if engine == 'sapi':
            voice = win32com.client.Dispatch('SAPI.SpVoice')
            voices = voice.GetVoices()
            portuguese = next(
                (voices.Item(index) for index in range(voices.Count)
                 if int(voices.Item(index).GetAttribute('Language'), 16) == 0x0416), None)
            if portuguese is None:
                raise SpeechError('Nenhuma voz pt-BR está instalada no Windows.')
            voice.Voice = portuguese
            voice.Volume = 100
            stream = win32com.client.Dispatch('SAPI.SpFileStream')
            selected = resolve_voices(dialogue, assignments)
        else:
            from .motion_voicestudio import available_voices
            valid = {item['id'] for item in available_voices()}
            selected = {cue['speaker']: (assignments or {}).get(cue['speaker'], 'default') for cue in dialogue}
            if any(profile not in valid for profile in selected.values()):
                raise SpeechError('Escolha uma voz disponível no VoiceStudio para cada personagem.')
        with tempfile.TemporaryDirectory(prefix='motion-speech-', dir=directory) as work:
            utterances = []
            for index, cue in enumerate(dialogue):
                if engine == 'voicestudio':
                    from .motion_voicestudio import synthesize_line
                    audio = synthesize_line(cue['text'], selected[cue['speaker']])
                    utterances.append((cue, audio, len(audio) // 2))
                else:
                    profile = VOICE_PROFILES[selected[cue['speaker']]]
                    voice.Rate = profile['rate']
                    path = Path(work) / f'line_{index:02d}.wav'
                    stream.Open(str(path), 3)
                    voice.AudioOutputStream = stream
                    voice.Speak(cue['text'], 0)
                    voice.AudioOutputStream = None
                    stream.Close()
                    with wave.open(str(path), 'rb') as utterance:
                        params = utterance.getparams()
                        if params.nchannels != 1 or params.sampwidth != 2 or params.framerate != 22050:
                            raise SpeechError('A voz pt-BR gerou um formato de áudio inesperado.')
                        spoken = array('h')
                        spoken.frombytes(utterance.readframes(params.nframes))
                        factor = 2 ** (profile['pitch'] / 12)
                        if factor != 1:
                            spoken = array('h', (spoken[min(len(spoken) - 1, int(i * factor))]
                                                 for i in range(round(len(spoken) / factor))))
                        utterances.append((cue, spoken.tobytes(), len(spoken)))

            rate = 48000 if engine == 'voicestudio' else 22050
            samples = array('h', [0]) * (rate * duration)
            rng = random.Random(seed)
            for index in range(len(samples)):
                samples[index] = rng.randrange(-90, 91)

            captions = []
            for index, (cue, audio, count) in enumerate(utterances):
                start = round(cue['start'] * rate)
                end = start + count
                next_start = round(dialogue[index + 1]['start'] * rate) if index + 1 < len(dialogue) else len(samples)
                if end > min(next_start, len(samples)):
                    raise SpeechError(f'A fala de {cue["speaker"]} em {cue["start"]} s excede o intervalo reservado no roteiro.')
                spoken = array('h')
                spoken.frombytes(audio)
                for offset, sample in enumerate(spoken):
                    target = start + offset
                    samples[target] = max(-32768, min(32767, samples[target] + round(sample * .82)))
                captions.append({
                    'start': cue['start'],
                    'end': end / rate,
                    'speaker': cue['speaker'],
                    'voice_profile': selected[cue['speaker']],
                    'text': cue['text'],
                })

            def tone(start_seconds, duration, frequency, volume, decay=False):
                start = round(start_seconds * rate)
                length = min(round(duration * rate), len(samples) - start)
                for offset in range(max(0, length)):
                    envelope = math.exp(-5 * offset / max(1, length)) if decay else 1
                    value = round(math.sin(2 * math.pi * frequency * offset / rate) * volume * envelope)
                    target = start + offset
                    samples[target] = max(-32768, min(32767, samples[target] + value))

            if duration == 60:
                tone(0.7, 2.4, 48, 2600, True)
                phone_start, phone_length = round(7.5 * rate), round(2.2 * rate)
                for offset in range(phone_length):
                    pulse = .35 + .65 * (math.sin(2 * math.pi * 5 * offset / rate) > 0)
                    value = round(math.sin(2 * math.pi * 125 * offset / rate) * 2300 * pulse)
                    target = phone_start + offset
                    samples[target] = max(-32768, min(32767, samples[target] + value))
                for start in (40.1, 41.5, 42.9):
                    tone(start, .24, 72, 6500, True)
                tone(59.45, .55, 42, 9000, True)

            with wave.open(str(audio_path), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(rate)
                output.writeframes(samples.tobytes())
        captions_path.write_text(json.dumps({
            'language': 'pt-BR',
            'engine': engine,
            'voice_profiles': selected,
            'segments': captions,
        }, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        return audio_path, captions_path
    except SpeechError:
        raise
    except Exception as exc:
        from .motion_voicestudio import VoiceStudioError
        if isinstance(exc, VoiceStudioError):
            raise SpeechError(str(exc)) from exc
        raise SpeechError('Não foi possível gerar a narração local em pt-BR.') from exc
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()
