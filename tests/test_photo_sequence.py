import json
import subprocess

import pytest

from central.photo_sequence import PhotoSequenceError, render_photo_scene, render_reference_scene


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


def test_rejects_magenta_character_plate_as_background(tmp_path):
    background = tmp_path / 'background.png'
    pose = tmp_path / 'pose.png'
    run('-f', 'lavfi', '-i', 'color=c=0xaa33cc:s=720x1280', '-frames:v', '1', background)
    run('-f', 'lavfi', '-i', 'color=c=magenta:s=512x1024', '-frames:v', '1', pose)
    with pytest.raises(PhotoSequenceError, match='cenário recebeu fundo magenta'):
        render_photo_scene(background, [pose, pose], tmp_path / 'scene.mp4')


def test_full_scene_references_keep_exact_fifteen_second_timing(tmp_path):
    first, last = tmp_path / 'first.png', tmp_path / 'last.png'
    run('-f', 'lavfi', '-i', 'color=c=blue:s=720x1280', '-frames:v', '1', first)
    run('-f', 'lavfi', '-i', 'color=c=green:s=720x1280', '-frames:v', '1', last)
    output = tmp_path / 'reference.mp4'
    result = render_reference_scene([first, last], output, frames=360)
    assert result['references'] == 2
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_frames,r_frame_rate,width,height', '-of', 'json', output], text=True))['streams'][0]
    assert probe == {'width': 720, 'height': 1280, 'r_frame_rate': '24/1', 'nb_frames': '360'}
