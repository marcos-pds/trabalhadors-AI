"""Isolated Python 3.11 worker; reads one JSON job and writes local WAV files."""
import json
from pathlib import Path
import sys


def main():
    job = json.load(sys.stdin)
    sys.path.insert(0, job['code_dir'])
    import torch
    import torchaudio
    from chatterbox.tts import ChatterboxTTS

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = ChatterboxTTS.from_local(job['model_dir'], device=device)
    folder = Path(job['output_dir'])
    for index, line in enumerate(job['lines']):
        wav = model.generate(line['text'], language_id='pt', audio_prompt_path=line['reference'])
        torchaudio.save(str(folder / f'{index:02d}.wav'), wav.cpu(), model.sr,
                        encoding='PCM_S', bits_per_sample=16)


if __name__ == '__main__':
    main()
