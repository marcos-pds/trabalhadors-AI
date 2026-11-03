"""Create a local pt-BR narration track and timed captions with Windows SAPI."""
from array import array
import json
import math
import random
import tempfile
import wave
from pathlib import Path


class SpeechError(RuntimeError):
    """Local Portuguese speech synthesis is unavailable or invalid."""


def synthesize_episode(directory, run_id, dialogue, seed):
    directory = Path(directory)
    audio_path = directory / f'narration_{run_id}.wav'
    captions_path = directory / f'captions_{run_id}.json'
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise SpeechError('A voz local pt-BR do Windows não está disponível nesta instalação.') from exc

    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch('SAPI.SpVoice')
        voices = voice.GetVoices()
        portuguese = next(
            (voices.Item(index) for index in range(voices.Count)
             if int(voices.Item(index).GetAttribute('Language'), 16) == 0x0416),
            None,
        )
        if portuguese is None:
            raise SpeechError('Nenhuma voz pt-BR está instalada no Windows.')
        voice.Voice = portuguese
        voice.Rate = -1
        voice.Volume = 100
        stream = win32com.client.Dispatch('SAPI.SpFileStream')
        with tempfile.TemporaryDirectory(prefix='motion-speech-', dir=directory) as work:
            utterances = []
            for index, cue in enumerate(dialogue):
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
                    utterances.append((cue, utterance.readframes(params.nframes), params.nframes))

            rate = 22050
            samples = array('h', [0]) * (rate * 60)
            rng = random.Random(seed)
            for index in range(len(samples)):
                samples[index] = rng.randrange(-90, 91)

            captions = []
            for index, (cue, audio, count) in enumerate(utterances):
                start = round(cue['start'] * rate)
                end = start + count
                next_start = round(dialogue[index + 1]['start'] * rate) if index + 1 < len(dialogue) else len(samples)
                if end > min(next_start, len(samples)):
                    raise SpeechError('Uma fala excede o intervalo reservado no roteiro.')
                spoken = array('h')
                spoken.frombytes(audio)
                for offset, sample in enumerate(spoken):
                    target = start + offset
                    samples[target] = max(-32768, min(32767, samples[target] + round(sample * .82)))
                captions.append({
                    'start': cue['start'],
                    'end': end / rate,
                    'speaker': cue['speaker'],
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
            'segments': captions,
        }, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        return audio_path, captions_path
    except SpeechError:
        raise
    except Exception as exc:
        raise SpeechError('Não foi possível gerar a narração local em pt-BR.') from exc
    finally:
        pythoncom.CoUninitialize()
