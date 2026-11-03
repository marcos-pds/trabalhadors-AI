"""Assemble the episode's eight scenes, narration and burnt-in captions."""
import argparse
import json
import os
from pathlib import Path
from fractions import Fraction
import tempfile


def _caption(image, cue, font):
    from PIL import Image, ImageDraw

    text = f"{cue['speaker'].upper()}: {cue['text']}"
    draw = ImageDraw.Draw(image)
    lines = []
    current = ''
    for word in text.split():
        candidate = f'{current} {word}'.strip()
        if current and draw.textlength(candidate, font=font) > image.width - 32:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    line_height = font.size + 5
    box_height = line_height * len(lines) + 18
    top = image.height - box_height - 18
    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    panel = ImageDraw.Draw(overlay)
    panel.rounded_rectangle(
        (10, top, image.width - 10, image.height - 12),
        radius=8, fill=(0, 0, 0, 205),
    )
    for index, line in enumerate(lines):
        x = (image.width - panel.textlength(line, font=font)) / 2
        panel.text((x, top + 9 + index * line_height), line,
                   font=font, fill=(255, 255, 255, 255),
                   stroke_width=1, stroke_fill=(0, 0, 0, 255))
    image.alpha_composite(overlay)
    return image


def assemble_episode(scene_paths, audio_path, captions_path, output_path, fps, frames):
    import av
    from PIL import ImageFont

    scene_paths = [Path(path) for path in scene_paths]
    audio_path, captions_path, output_path = map(Path, (audio_path, captions_path, output_path))
    captions = json.loads(captions_path.read_text(encoding='utf-8'))['segments']
    if len(scene_paths) != 8 or frames != fps * 60:
        raise ValueError('episode assembly requires eight scenes and exactly 60 seconds')

    font_path = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'arial.ttf'
    font = ImageFont.truetype(str(font_path), 16) if font_path.is_file() else ImageFont.load_default()

    audio_packets = []
    with av.open(str(audio_path), mode='r') as audio_input:
        if not audio_input.streams.audio:
            raise ValueError('narration has no audio stream')
        source_audio = audio_input.streams.audio[0]
        rate = source_audio.rate
        handle, temporary = tempfile.mkstemp(
            prefix=output_path.stem + '-', suffix='.mp4', dir=output_path.parent,
        )
        os.close(handle)
        try:
            with av.open(temporary, mode='w', format='mp4') as output:
                video = output.add_stream('libx264', rate=fps)
                video.width = 288
                video.height = 512
                video.pix_fmt = 'yuv420p'
                video.options = {'preset': 'veryfast', 'crf': '20'}
                video.time_base = Fraction(1, fps)
                audio = output.add_stream('aac', rate=rate)
                audio.layout = 'mono'
                audio.bit_rate = 96000
                audio.time_base = Fraction(1, rate)

                video_packets = []
                from PIL import Image
                frame_index = 0
                for scene_path in scene_paths:
                    with av.open(str(scene_path), mode='r') as source:
                        if not source.streams.video:
                            raise ValueError('scene has no video stream')
                        stream = source.streams.video[0]
                        for frame in source.decode(stream):
                            if frame_index == frames:
                                break
                            image = frame.to_image().convert('RGB')
                            if image.size != (288, 512):
                                image = image.resize((288, 512), Image.Resampling.LANCZOS)
                            seconds = frame_index / fps
                            cue = next((item for item in captions
                                        if item['start'] <= seconds < item['end']), None)
                            if cue:
                                image = _caption(image.convert('RGBA'), cue, font).convert('RGB')
                            encoded = av.VideoFrame.from_image(image)
                            encoded.pts = frame_index
                            encoded.time_base = Fraction(1, fps)
                            video_packets.extend(video.encode(encoded))
                            frame_index += 1
                    if frame_index == frames:
                        break
                if frame_index != frames:
                    raise ValueError('scenes do not contain exactly 60 seconds of video')
                video_packets.extend(video.encode(None))

                resampler = av.AudioResampler(
                    format=audio.codec_context.format.name, layout='mono', rate=rate,
                )
                sample_position = 0
                for source_frame in audio_input.decode(source_audio):
                    for frame in resampler.resample(source_frame):
                        frame.pts = sample_position
                        frame.time_base = Fraction(1, rate)
                        sample_position += frame.samples
                        audio_packets.extend(audio.encode(frame))
                for frame in resampler.resample(None):
                    frame.pts = sample_position
                    frame.time_base = Fraction(1, rate)
                    sample_position += frame.samples
                    audio_packets.extend(audio.encode(frame))
                audio_packets.extend(audio.encode(None))

                packets = [((packet.dts if packet.dts is not None else packet.pts) *
                            packet.time_base, packet, video)
                           for packet in video_packets]
                packets.extend(((packet.dts if packet.dts is not None else packet.pts) *
                                packet.time_base, packet, audio)
                               for packet in audio_packets)
                for _, packet, stream in sorted(packets, key=lambda item: item[0]):
                    packet.stream = stream
                    output.mux(packet)
            os.replace(temporary, output_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('assemble',))
    parser.add_argument('--audio', required=True)
    parser.add_argument('--captions', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--fps', type=int, required=True)
    parser.add_argument('--frames', type=int, required=True)
    parser.add_argument('scenes', nargs=8)
    args = parser.parse_args()
    assemble_episode(args.scenes, args.audio, args.captions, args.output, args.fps, args.frames)


if __name__ == '__main__':
    main()
