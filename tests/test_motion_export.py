import json
import shutil
import subprocess
import wave

import pytest

from central.motion_export import assemble_episode


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg indisponível')
def test_export_joins_scenes_with_voice_and_silence(tmp_path):
    videos = []
    for color in ('red', 'blue'):
        video = tmp_path / f'{color}.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', f'color=c={color}:s=160x240:r=16:d=0.5',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
        videos.append(video)
    speech = tmp_path / 'speech.wav'
    with wave.open(str(speech), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b'\x00\x00' * 24000)
    result = assemble_episode([(videos[0], speech, .5), (videos[1], None, .5)], tmp_path / 'final.mp4',
                              captions=['Olá, mundo!', ''])
    assert result['scenes'] == 2
    assert .9 <= result['duration'] <= 1.2
    probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'stream=codec_type,codec_name,width,height', '-of', 'json', str(result['path'])])
    streams = json.loads(probe)['streams']
    assert any(stream['codec_type'] == 'video' and stream['width'] == 720 and stream['height'] == 1280 for stream in streams)
    assert any(stream['codec_type'] == 'audio' and stream['codec_name'] == 'aac' for stream in streams)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg indisponível')
def test_export_keeps_one_narration_across_scene_boundary(tmp_path):
    videos = []
    for color in ('red', 'blue'):
        video = tmp_path / f'{color}.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', f'color=c={color}:s=160x240:r=24:d=0.5',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
        videos.append(video)
    narration = tmp_path / 'narration.wav'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                    str(narration)], check=True)
    result = assemble_episode([(videos[0], None, .5), (videos[1], None, .5)],
                              tmp_path / 'continuous.mp4', narration=narration)
    decoded = subprocess.check_output(['ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-i', str(result['path']), '-f', 's16le', '-ac', '1', '-ar', '48000', '-'])
    assert len(decoded) >= 48000 * 2 * .9
    assert any(byte for byte in decoded[round(.48 * 96000):round(.52 * 96000)])


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg indisponível')
def test_export_preserves_embedded_audio_in_single_scene(tmp_path):
    source = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=c=black:s=160x240:r=24:d=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                    '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(source)], check=True)
    result = assemble_episode([(source, None, 1)], tmp_path / 'final.mp4')
    decoded = subprocess.check_output(['ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-i', str(result['path']), '-f', 's16le', '-ac', '1', '-ar', '48000', '-'])
    assert result['scenes'] == 1
    assert any(decoded)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg indisponível')
def test_export_mixes_scene_effect_under_continuous_narration(tmp_path):
    source = tmp_path / 'effect.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=c=black:s=160x240:r=24:d=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                    '-c:v', 'libx264', '-c:a', 'aac', '-shortest', str(source)], check=True)
    silence = tmp_path / 'narration.wav'
    with wave.open(str(silence), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b'\x00\x00' * 48000)
    result = assemble_episode([(source, None, 1)], tmp_path / 'mix.mp4', narration=silence)
    decoded = subprocess.check_output(['ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-i', str(result['path']), '-f', 's16le', '-ac', '1', '-ar', '48000', '-'])
    assert any(decoded)
