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


def _magenta_corner(path, ffmpeg):
    corner = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(path),
        '-vf', 'crop=1:1:0:0,format=rgb24', '-frames:v', '1',
        '-f', 'rawvideo', '-'], capture_output=True, timeout=30, check=False)
    if corner.returncode or len(corner.stdout) != 3:
        raise PhotoSequenceError('Não foi possível inspecionar a cor de uma imagem.')
    red, green, blue = corner.stdout
    return red > 150 and blue > 110 and green < 150 and red > green * 1.35 and blue > green * 1.2


def render_photo_scene(background, poses, output, *, frames=96, fps=24,
                       ffmpeg='ffmpeg', ffprobe='ffprobe'):
    """Keep background pixels fixed; show each isolated pose for a short interval."""
    background, output = Path(background), Path(output)
    poses = [Path(pose) for pose in poses]
    if not 2 <= len(poses) <= 30 or not 24 <= frames <= 720 or fps != 24 or frames < len(poses):
        raise PhotoSequenceError('Use 2 a 30 poses e uma duração de 1 a 30 segundos em 24 FPS.')
    if not background.is_file() or any(not pose.is_file() for pose in poses):
        raise PhotoSequenceError('Falta o cenário fixo ou uma das poses.')
    if _magenta_corner(background, ffmpeg):
        raise PhotoSequenceError('O cenário recebeu fundo magenta; gere um ambiente vazio antes de montar a cena.')
    output.parent.mkdir(parents=True, exist_ok=True)
    stills = []
    for index, pose in enumerate(poses):
        # An isolated magenta background is mandatory. It prevents a generated
        # room or street from replacing the scene's fixed setting.
        if not _magenta_corner(pose, ffmpeg):
            raise PhotoSequenceError(f'Pose {index + 1} precisa de fundo magenta uniforme.')
        still = output.with_name(f'{output.stem}.pose_{index:02d}.png')
        _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
            '-i', background, '-i', pose, '-filter_complex',
            '[0:v]scale=720:1280,format=rgba[bg];'
            '[1:v]colorkey=0xff00ff:0.48:0.0,scale=520:-1,format=rgba[actor];'
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


def render_reference_scene(images, output, *, frames=360, fps=24,
                           ffmpeg='ffmpeg', ffprobe='ffprobe'):
    """Move gently across full scene references and dissolve between action states."""
    images = [Path(image) for image in images]
    output = Path(output)
    if not 2 <= len(images) <= 30 or not 24 <= frames <= 720 or fps != 24:
        raise PhotoSequenceError('Use 2 a 30 quadros de cena e até 30 segundos em 24 FPS.')
    if any(not image.is_file() or _magenta_corner(image, ffmpeg) for image in images):
        raise PhotoSequenceError('Os quadros completos precisam conter o cenário, sem fundo magenta.')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Every source remains visible while the camera drifts. A long dissolve
    # changes the scene progressively without exposing cutout edges.
    duration = frames / fps
    segment = duration / (len(images) - 1)
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y']
    for image in images:
        args += ['-loop', '1', '-framerate', str(fps), '-t', f'{duration:.6f}', '-i', str(image)]
    filters = []
    for index in range(len(images)):
        filters.append(f'[{index}:v]scale=720:1280,'
                       "zoompan=z='min(zoom+0.00035,1.13)':"
                       "x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
                       "d=1:s=720x1280:fps=24,"
                       'setsar=1,format=yuv420p'
                       f'[v{index}]')
    last = 'v0'
    for index in range(1, len(images)):
        next_name = f'm{index}'
        filters.append(f'[{last}][v{index}]xfade=transition=fade:'
                       f'duration={segment:.6f}:offset={segment*(index-1):.6f}[{next_name}]')
        last = next_name
    _run(args + ['-filter_complex', ';'.join(filters), '-map', f'[{last}]',
        '-frames:v', str(frames), '-an', '-r', str(fps), '-c:v', 'libx264',
        '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(output)], timeout=600)
    probe = subprocess.run([str(ffprobe), '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_frames,width,height,r_frame_rate', '-of', 'json',
        str(output)], capture_output=True, text=True, timeout=30, check=False)
    if probe.returncode:
        raise PhotoSequenceError('O ffprobe não conseguiu validar a cena por referências.')
    video = json.loads(probe.stdout)['streams'][0]
    if (int(video.get('nb_frames') or 0) != frames or video.get('width') != 720
            or video.get('height') != 1280 or video.get('r_frame_rate') != '24/1'):
        raise PhotoSequenceError('A cena não tem a duração ou o formato esperado.')
    return {'path': output, 'frames': frames, 'fps': fps, 'references': len(images)}
