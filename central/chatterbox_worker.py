"""Isolated Python 3.11 worker; reads one JSON job and writes local WAV files."""
import json
from pathlib import Path
import sys


def main():
    job = json.load(sys.stdin)
    import torch
    import torchaudio
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model='v3')
    folder = Path(job['output_dir'])
    for index, line in enumerate(job['lines']):
        wav = model.generate(line['text'], language_id='pt', audio_prompt_path=line['reference'])
        torchaudio.save(str(folder / f'{index:02d}.wav'), wav.cpu(), model.sr,
                        encoding='PCM_S', bits_per_sample=16)


if __name__ == '__main__':
    main()
