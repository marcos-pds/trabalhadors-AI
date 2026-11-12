"""Assemble owner-validated scene paths into one vertical MP4."""
import json
import os
import subprocess
from pathlib import Path


class MotionExportError(RuntimeError):
    pass


def _srt_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    whole, remainder = divmod(rest, 1000)
    return f'{hours:02d}:{minutes:02d}:{whole:02d},{remainder:03d}'


def assemble_episode(scenes, output, ffmpeg='ffmpeg', ffprobe='ffprobe', captions=None):
    """Each scene is (video_path, optional_audio_path, duration_seconds)."""
    if not scenes or len(scenes) > 64:
        raise MotionExportError('O episódio precisa de cenas para montagem.')
    output = Path(output)
    temporary = output.with_name(output.stem + '.building.mp4')
    subtitle = output.with_name(output.stem + '.building.srt')
    args = [str(ffmpeg), '-hide_banner', '-nostdin', '-loglevel', 'error', '-y']
    filters = []
    concat = []
    total = 0.0
    for index, (video, audio, duration) in enumerate(scenes):
        if not 0 < duration <= 600:
            raise MotionExportError('Duração de cena inválida.')
        total += duration
        args += ['-i', str(video)]
        if audio:
            args += ['-i', str(audio)]
        else:
            args += ['-f', 'lavfi', '-t', f'{duration:.6f}', '-i', 'anullsrc=channel_layout=mono:sample_rate=48000']
        video_input, audio_input = index * 2, index * 2 + 1
        filters.append(f'[{video_input}:v]trim=duration={duration:.6f},setpts=PTS-STARTPTS,'
                       'scale=720:1280:force_original_aspect_ratio=decrease,'
                       'pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p'
                       f'[v{index}]')
        filters.append(f'[{audio_input}:a]aresample=48000,aformat=channel_layouts=mono,'
                       f'atrim=duration={duration:.6f},asetpts=PTS-STARTPTS,'
                       f'apad=whole_dur={duration:.6f},atrim=duration={duration:.6f}[a{index}]')
        concat.append(f'[v{index}][a{index}]')
    if captions is not None and len(captions) != len(scenes):
        raise MotionExportError('Legendas e cenas não correspondem.')
    visible = captions is not None and any(str(line).strip() for line in captions)
    if visible:
        clock = 0.0
        entries = []
        for index, ((_, _, duration), line) in enumerate(zip(scenes, captions), 1):
            clean = ' '.join(str(line).split()).upper()[:300]
            if clean:
                entries.append(f'{index}\n{_srt_time(clock)} --> {_srt_time(clock + duration)}\n{clean}\n')
            clock += duration
        subtitle.write_text('\n'.join(entries), encoding='utf-8')
        filters.append(''.join(concat) + f'concat=n={len(scenes)}:v=1:a=1[joined][a]')
        filters.append(f'[joined]subtitles=filename={subtitle.name}[v]')
    else:
        filters.append(''.join(concat) + f'concat=n={len(scenes)}:v=1:a=1[v][a]')
    args += ['-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-threads', '2', str(temporary)]
    try:
        result = subprocess.run(args, cwd=output.parent, capture_output=True, text=True, timeout=900, check=False)
        if result.returncode:
            raise MotionExportError('A montagem MP4 falhou: ' + result.stderr[-500:])
        probe = subprocess.run([str(ffprobe), '-v', 'error', '-show_entries',
            'format=duration:stream=codec_type,codec_name,width,height', '-of', 'json', str(temporary)],
            capture_output=True, text=True, timeout=30, check=False)
        if probe.returncode:
            raise MotionExportError('O ffprobe não conseguiu validar o MP4.')
        media = json.loads(probe.stdout)
        streams = media.get('streams', [])
        video = next((stream for stream in streams if stream.get('codec_type') == 'video'), None)
        audio = next((stream for stream in streams if stream.get('codec_type') == 'audio'), None)
        actual = float(media.get('format', {}).get('duration') or 0)
        if (not video or video.get('codec_name') != 'h264' or video.get('width') != 720
                or video.get('height') != 1280 or not audio or audio.get('codec_name') != 'aac'
                or abs(actual - total) > .6):
            raise MotionExportError('O MP4 final não passou na validação de áudio, vídeo ou duração.')
        os.replace(temporary, output)
        return {'path': output, 'duration': actual, 'scenes': len(scenes)}
    finally:
        temporary.unlink(missing_ok=True)
        subtitle.unlink(missing_ok=True)
