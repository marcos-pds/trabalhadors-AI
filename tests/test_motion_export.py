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
