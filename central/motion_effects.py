"""Reversible local scene edits and procedural sound design for photo episodes."""
import json
import math
import random
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path


PRESETS = {'footsteps', 'lamp_clicks', 'door_slam', 'wind', 'metal_creak'}


class MotionEffectError(RuntimeError):
    pass


def _run(args):
    result = subprocess.run([str(item) for item in args], capture_output=True, text=True,
                            timeout=300, check=False)
    if result.returncode:
        raise MotionEffectError('Falha ao montar efeito da cena: ' + result.stderr[-2000:])


def _effect_audio(path, preset, duration, cue):
    rate = 48000
    count = round(duration * rate)
    rng = random.Random(9124)
    samples = array('h')
    wind = 0.0
    for index in range(count):
        t = index / rate
        wind = wind * .996 + (rng.random() * 2 - 1) * .004
        signal = wind * .075
        if preset == 'footsteps':
            phase = (t - .7) % 1.35
            if t >= .7 and phase < .17:
                envelope = math.exp(-phase * 28)
                signal += envelope * (.16 * math.sin(2 * math.pi * 63 * phase)
                                      + .035 * (rng.random() * 2 - 1))
        elif preset == 'lamp_clicks':
            phase = (t - 1.8) % 3.2
            if t >= 1.8 and phase < .035:
                signal += .22 * math.exp(-phase * 140) * (rng.random() * 2 - 1)
        elif preset == 'door_slam':
            phase = t - cue
            if 0 <= phase < .9:
                envelope = math.exp(-phase * 8)
                signal += envelope * (.5 * math.sin(2 * math.pi * 58 * phase)
                                      + .22 * (rng.random() * 2 - 1))
            for delay, gain in ((.16, .18), (.32, .09)):
                echo = phase - delay
                if 0 <= echo < .35:
                    signal += gain * math.exp(-echo * 12) * math.sin(2 * math.pi * 66 * echo)
        elif preset == 'metal_creak':
            phase = t - cue
            if 0 <= phase < 1.6:
                envelope = math.sin(math.pi * phase / 1.6) ** 2
                signal += envelope * (.13 * math.sin(2 * math.pi * (180 * phase + 95 * phase * phase))
                                      + .025 * (rng.random() * 2 - 1))
        elif preset == 'wind':
            signal += wind * .13
        samples.append(max(-32768, min(32767, round(signal * 32767))))
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())


def render_effect_scene(source, output, preset, cue_seconds, *, frames=360, fps=24,
                        after_source=None,
                        ffmpeg='ffmpeg', ffprobe='ffprobe'):
    source, output = Path(source), Path(output)
    if preset not in PRESETS or not 24 <= frames <= 720 or fps != 24:
        raise MotionEffectError('Efeito ou duração inválida.')
    duration = frames / fps
    if not .5 <= cue_seconds <= duration - .5:
        raise MotionEffectError('Escolha um instante dentro da cena.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='motion-effect-') as folder:
        folder = Path(folder)
        video = source
        if preset == 'door_slam':
            after = folder / 'after.png'
            if after_source:
                _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i',
                      after_source, '-frames:v', '1', after])
            else:
                _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss',
                      f'{duration-.2:.3f}', '-i', source, '-frames:v', '1', after])
            video = folder / 'impact.mp4'
            first = round(cue_seconds * fps)
            second = frames - first
            graph = (f'[0:v]trim=duration={first/fps},setpts=PTS-STARTPTS,'
                     f'scale=736:1308,crop=720:1280:8:14,setsar=1,'
                     f'setpts=PTS-STARTPTS[v0];'
                     f'[1:v]scale=736:1308,crop=720:1280:8:14,setsar=1,trim=duration={second/fps},'
                     f'setpts=PTS-STARTPTS[v1];'
                     f'[v0][v1]concat=n=2:v=1:a=0,scale=736:1308,'
                     f"crop=720:1280:x='8+if(between(t,{cue_seconds},{cue_seconds+.3}),6*sin(80*t),0)':"
                     f"y='14+if(between(t,{cue_seconds},{cue_seconds+.3}),5*cos(73*t),0)',"
                     f'format=yuv420p[v]')
            _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                  '-i', source,
                  '-loop', '1', '-framerate', str(fps), '-t', f'{second/fps:.6f}', '-i', after,
                  '-filter_complex', graph, '-map', '[v]', '-frames:v', str(frames),
                  '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', video])
        audio = folder / 'effect.wav'
        _effect_audio(audio, preset, duration, cue_seconds)
        _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', video, '-i', audio,
              '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
              '-t', f'{duration:.6f}', '-movflags', '+faststart', output])
    probe = subprocess.run([str(ffprobe), '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,nb_frames', '-of', 'json', str(output)],
        capture_output=True, text=True, timeout=30, check=False)
    if probe.returncode:
        raise MotionEffectError('O ffprobe não conseguiu validar a cena editada.')
    media = json.loads(probe.stdout)
    video_stream = next((stream for stream in media['streams'] if stream['codec_type'] == 'video'), None)
    if (not video_stream or int(video_stream.get('nb_frames') or 0) != frames or
            not any(stream['codec_type'] == 'audio' for stream in media['streams']) or
            abs(float(media['format']['duration']) - duration) > .06):
        raise MotionEffectError('A cena editada perdeu quadros, áudio ou duração.')
    return output
