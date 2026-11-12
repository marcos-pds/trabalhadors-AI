"""Install the official pt-BR inference code and small shared assets locally."""
from pathlib import Path
import shutil

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1] / 'data' / 'motion-studio'
MODEL = ROOT / 'ptbr-model'
CODE = ROOT / 'ptbr-runtime' / 'chatterbox'


def main():
    model = Path(snapshot_download(
        repo_id='ResembleAI/chatterbox', repo_type='model',
        revision='5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18',
        allow_patterns=['ve.pt', 'conds.pt', 'grapheme_mtl_merged_expanded_v1.json'],
    ))
    space = Path(snapshot_download(
        repo_id='ResembleAI/Chatterbox-Multilingual-TTS-pt-br', repo_type='space',
        revision='9e515821e826e207cd617a0fdd0223899ed108ea',
        allow_patterns=['chatterbox/src/chatterbox/**'],
    ))
    MODEL.mkdir(parents=True, exist_ok=True)
    for name in ('ve.pt', 'conds.pt', 'grapheme_mtl_merged_expanded_v1.json'):
        shutil.copyfile(model / name, MODEL / name)
    shutil.copytree(space / 'chatterbox' / 'src' / 'chatterbox', CODE, dirs_exist_ok=True)
    print('Código e ativos pt-BR instalados em', ROOT)


if __name__ == '__main__':
    main()
