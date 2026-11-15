import json
import shutil
import subprocess

import pytest

from central.motion_effects import render_effect_scene


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg indisponível')
def test_door_slam_keeps_length_and_switches_to_closed_reference(tmp_path):
    before = tmp_path / 'before.mp4'
    after = tmp_path / 'after.mp4'
    for path, color in ((before, 'red'), (after, 'blue')):
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', f'color=c={color}:s=160x240:r=24:d=1',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
    output = render_effect_scene(before, tmp_path / 'edited.mp4', 'door_slam', 0.5,
                                 frames=24, after_source=after)
    probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,nb_frames', '-of', 'json', str(output)])
    info = json.loads(probe)
    assert abs(float(info['format']['duration']) - 1) < .06
    assert any(s['codec_type'] == 'video' and int(s['nb_frames']) == 24 for s in info['streams'])
    assert any(s['codec_type'] == 'audio' for s in info['streams'])
    colors = []
    for at in ('0.25', '0.75'):
        frame = subprocess.check_output(['ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-ss', at, '-i', str(output), '-frames:v', '1', '-f', 'rawvideo',
            '-pix_fmt', 'rgb24', '-s', '1x1', '-'])
        colors.append(frame)
    assert colors[0][0] > colors[0][2]
    assert colors[1][2] > colors[1][0]
