import json
import subprocess

import pytest

from central.photo_sequence import PhotoSequenceError, render_photo_scene


def run(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], check=True)


def test_photo_scene_uses_fixed_background_and_exact_frames(tmp_path):
    background = tmp_path / 'background.png'
    poses = [tmp_path / f'pose-{index}.png' for index in range(2)]
    run('-f', 'lavfi', '-i', 'color=c=blue:s=720x1280', '-frames:v', '1', background)
    for index, pose in enumerate(poses):
        run('-f', 'lavfi', '-i', 'color=c=magenta:s=512x1024', '-vf',
            f'drawbox=x={100 + index*100}:y=400:w=80:h=80:color=green:t=fill',
            '-frames:v', '1', pose)
    output = tmp_path / 'scene.mp4'
    result = render_photo_scene(background, poses, output, frames=48)
    assert result['frames'] == 48
    assert result['poses'] == 2
    assert output.is_file()
    probe = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_frames,width,height', '-of', 'json', output], text=True)
    stream = json.loads(probe)['streams'][0]
    assert stream['nb_frames'] == '48'
    assert stream['width'] == 720 and stream['height'] == 1280
    # The generated actor may move; the upper-left background stays untouched.
    def corner(seconds):
        return subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', str(seconds),
            '-i', output, '-vf', 'crop=2:2:0:0,format=rgb24',
            '-frames:v', '1', '-f', 'rawvideo', '-'])
    assert corner(0) == corner(1.1)


def test_rejects_full_scene_in_place_of_isolated_pose(tmp_path):
    background = tmp_path / 'background.png'
    pose = tmp_path / 'pose.png'
    run('-f', 'lavfi', '-i', 'color=c=blue:s=720x1280', '-frames:v', '1', background)
    run('-f', 'lavfi', '-i', 'color=c=blue:s=512x1024', '-frames:v', '1', pose)
    with pytest.raises(PhotoSequenceError, match='magenta'):
        render_photo_scene(background, [pose, pose], tmp_path / 'scene.mp4')
