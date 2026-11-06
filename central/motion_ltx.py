"""Small image-conditioned LTX scene workflow for the local ComfyUI runtime."""

MODEL = "ltxv-2b-0.9.8-distilled-fp8.safetensors"
ENCODER = "t5xxl_fp8_e4m3fn.safetensors"


def ltx_workflow(prompt, image_name, seed, frames, fps, filename_prefix,
                 width=288, height=512):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": MODEL}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": ENCODER, "type": "ltxv", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "flicker, changed face, changed clothing, distorted anatomy, text, watermark"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "LTXVImgToVideo", "inputs": {"positive": ["3", 0], "negative": ["4", 0], "vae": ["1", 2], "image": ["5", 0], "width": width, "height": height, "length": frames, "batch_size": 1, "strength": 1.0}},
        "7": {"class_type": "LTXVConditioning", "inputs": {"positive": ["6", 0], "negative": ["6", 1], "frame_rate": fps}},
        "8": {"class_type": "LTXVScheduler", "inputs": {"steps": 8, "max_shift": 2.05, "base_shift": 0.95, "stretch": True, "terminal": 0.1, "latent": ["6", 2]}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "10": {"class_type": "SamplerCustom", "inputs": {"model": ["1", 0], "add_noise": True, "noise_seed": seed, "cfg": 1.0, "positive": ["7", 0], "negative": ["7", 1], "sampler": ["9", 0], "sigmas": ["8", 0], "latent_image": ["6", 2]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["1", 2]}},
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": fps}},
        "13": {"class_type": "SaveVideo", "inputs": {"video": ["12", 0], "filename_prefix": filename_prefix, "format": "mp4", "format.codec": "h264"}},
    }
