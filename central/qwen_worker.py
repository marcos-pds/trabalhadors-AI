"""Isolated local Qwen TTS inference process; input is one JSON request on stdin."""
import json
import sys


def main():
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    request = json.load(sys.stdin)
    torch.manual_seed(request['seed'])
    model = Qwen3TTSModel.from_pretrained(request['model'], device_map='cuda:0',
                                          dtype=torch.bfloat16 if 'reference' in request else torch.float16,
                                          attn_implementation='sdpa')
    if 'reference' in request:
        wavs, rate = model.generate_voice_clone(text=request['text'], language='Portuguese',
                                                ref_audio=request['reference'], ref_text=request['transcript'])
    else:
        wavs, rate = model.generate_voice_design(text=request['text'], language='Portuguese',
                                                  instruct=request['instruction'])
    sf.write(request['output'], wavs[0], rate, subtype='PCM_16')


if __name__ == '__main__':
    main()
