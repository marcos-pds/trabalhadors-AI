"""Build a scene from isolated poses over one immutable background."""
import json
import subprocess
from pathlib import Path


class PhotoSequenceError(RuntimeError):
    pass


def _run(args, timeout=180):
    try:
        result = subprocess.run([str(arg) for arg in args], capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhotoSequenceError('O FFmpeg não conseguiu montar a sequência de fotos.') from exc
    if result.returncode:
        raise PhotoSequenceError('A montagem das fotos falhou: ' + result.stderr[-350:])


def render_photo_scene(background, poses, output, *, frames=96, fps=24,
                       ffmpeg='ffmpeg', ffprobe='ffprobe'):
    """Keep background pixels fixed; show each isolated pose for a short interval."""
    background, output = Path(background), Path(output)
    poses = [Path(pose) for pose in poses]
    if not 2 <= len(poses) <= 30 or not 24 <= frames <= 720 or fps != 24 or frames < len(poses):
        raise PhotoSequenceError('Use 2 a 30 poses e uma duração de 1 a 30 segundos em 24 FPS.')
    if not background.is_file() or any(not pose.is_file() for pose in poses):
        raise PhotoSequenceError('Falta o cenário fixo ou uma das poses.')
    output.parent.mkdir(parents=True, exist_ok=True)
    stills = []
    for index, pose in enumerate(poses):
        # An isolated magenta background is mandatory. It prevents a generated
        # room or street from replacing the scene's fixed setting.
        corner = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(pose),
            '-vf', 'crop=1:1:0:0,format=rgb24', '-frames:v', '1',
            '-f', 'rawvideo', '-'], capture_output=True, timeout=30, check=False)
        if corner.returncode or len(corner.stdout) != 3 or not (
                corner.stdout[0] > 170 and corner.stdout[1] < 110 and corner.stdout[2] > 130):
            raise PhotoSequenceError(f'Pose {index + 1} precisa de fundo magenta uniforme.')
        still = output.with_name(f'{output.stem}.pose_{index:02d}.png')
        _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
            '-i', background, '-i', pose, '-filter_complex',
            '[0:v]scale=720:1280,format=rgba[bg];'
            '[1:v]colorkey=0xff00ff:0.23:0.08,scale=520:-1,format=rgba[actor];'
            '[bg][actor]overlay=(W-w)/2:H-h-60:format=auto,format=rgb24[v]',
            '-map', '[v]', '-frames:v', '1', still])
        stills.append(still)
    counts = [frames // len(stills) + (index < frames % len(stills))
              for index in range(len(stills))]
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y']
    for still, count in zip(stills, counts):
        args += ['-loop', '1', '-framerate', str(fps), '-t', f'{count/fps:.6f}', '-i', str(still)]
    joined = ''.join(f'[{index}:v]scale=720:1280,setsar=1,format=yuv420p[v{index}];'
                     for index in range(len(stills)))
    joined += ''.join(f'[v{index}]' for index in range(len(stills)))
    joined += f'concat=n={len(stills)}:v=1:a=0[v]'
    _run(args + ['-filter_complex', joined, '-map', '[v]', '-frames:v', str(frames),
        '-an', '-r', str(fps), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output], timeout=300)
    probe = subprocess.run([str(ffprobe), '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_frames,width,height,r_frame_rate', '-of', 'json',
        str(output)], capture_output=True, text=True, timeout=30, check=False)
    if probe.returncode:
        raise PhotoSequenceError('O ffprobe não conseguiu validar a sequência de fotos.')
    video = json.loads(probe.stdout)['streams'][0]
    if (int(video.get('nb_frames') or 0) != frames or video.get('width') != 720
            or video.get('height') != 1280 or video.get('r_frame_rate') != '24/1'):
        raise PhotoSequenceError('A sequência de fotos não tem a duração ou formato esperado.')
    return {'path': output, 'frames': frames, 'fps': fps, 'poses': len(poses)}
