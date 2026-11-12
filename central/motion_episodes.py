"""Build bounded Wan scene batches for a 60-second vertical episode."""

EPISODE_FPS = 16
EPISODE_FRAMES = 60 * EPISODE_FPS
SCENE_FRAMES = (121, 121, 121, 121, 121, 121, 121, 113)
EPISODE_DIALOGUE = (
    {'start': 10.5, 'speaker': 'Lara', 'text': 'Ué... como assim? Esse é o meu número.'},
    {'start': 20, 'speaker': 'Voz desconhecida', 'text': 'Lara... sou eu. Você precisa me escutar.'},
    {'start': 28, 'speaker': 'Lara', 'text': 'Quem tá falando?'},
    {'start': 32.5, 'speaker': 'Voz desconhecida', 'text': 'Não abre a porta. Não importa quem seja.'},
    {'start': 44, 'speaker': 'Lara', 'text': 'Meu Deus... quem tá aí?'},
    {'start': 51, 'speaker': 'Voz atrás da porta', 'text': 'Lara... abre. Eu sou você.'},
)


def wan_workflow(prompt, seed, frames, fps, filename_prefix):
    positive = '1'
    negative = '2'
    unet = '3'
    clip = '4'
    vae = '5'
    sampling = '6'
    latent = '7'
    sampler = '8'
    decode = '9'
    video = '10'
    save = '11'
    return {
        unet: {'class_type': 'UNETLoader', 'inputs': {
            'unet_name': 'wan2.1_t2v_1.3B_fp16.safetensors', 'weight_dtype': 'default'}},
        clip: {'class_type': 'CLIPLoader', 'inputs': {
            'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan', 'device': 'default'}},
        vae: {'class_type': 'VAELoader', 'inputs': {'vae_name': 'wan_2.1_vae.safetensors'}},
        sampling: {'class_type': 'ModelSamplingSD3', 'inputs': {'model': [unet, 0], 'shift': 8}},
        positive: {'class_type': 'CLIPTextEncode', 'inputs': {'clip': [clip, 0], 'text': prompt}},
        negative: {'class_type': 'CLIPTextEncode', 'inputs': {
            'clip': [clip, 0], 'text': 'watermark, subtitles, blurry, distorted geometry, flicker'}},
        latent: {'class_type': 'EmptyHunyuanLatentVideo', 'inputs': {
            'width': 288, 'height': 512, 'length': frames, 'batch_size': 1}},
        sampler: {'class_type': 'KSampler', 'inputs': {
            'model': [sampling, 0], 'positive': [positive, 0], 'negative': [negative, 0],
            'latent_image': [latent, 0], 'seed': seed, 'steps': 16, 'cfg': 5.5,
            'sampler_name': 'uni_pc', 'scheduler': 'simple', 'denoise': 1}},
        decode: {'class_type': 'VAEDecode', 'inputs': {'samples': [sampler, 0], 'vae': [vae, 0]}},
        video: {'class_type': 'CreateVideo', 'inputs': {'images': [decode, 0], 'fps': fps}},
        save: {'class_type': 'SaveVideo', 'inputs': {
            'video': [video, 0], 'filename_prefix': filename_prefix,
            'format': {'format': 'mp4', 'codec': {'codec': 'h264'}}}},
    }


def build_episode_manifest(project_id, episode, prompts, seed, run_id):
    """Return one durable queue manifest and the local workflow files it needs."""
    workflows = []
    artifacts = []
    jobs = []
    for index, (prompt, frames) in enumerate(zip(prompts, SCENE_FRAMES), 1):
        scene = f'{index:02d}'
        workflow_id = f'workflow_{scene}'
        video_id = f'video_{scene}'
        job_id = f'scene_{scene}'
        stem = f'episodes/{project_id}/episode_{episode:02d}/scene_{scene}_{run_id}'
        workflow_path = f'{stem}.json'
        video_path = f'{stem}.mp4'
        scene_seed = (seed + index - 1) % (2**32)
        workflows.append((workflow_path, wan_workflow(
            prompt, scene_seed, frames, EPISODE_FPS, f'central_motion_ep{episode}_scene{scene}')))
        artifacts.extend((
            {'id': workflow_id, 'kind': 'workflow', 'path': workflow_path,
             'provenance': {'source': 'local'}},
            {'id': video_id, 'kind': 'video', 'path': video_path,
             'provenance': {'source': 'planned', 'job_id': job_id, 'inputs': [workflow_id]}},
        ))
        jobs.append({
            'id': job_id, 'adapter': 'comfyui_wan', 'stage': 'generate',
            'inputs': [workflow_id], 'outputs': [video_id],
            'params': {'model': 'wan', 'seed': scene_seed, 'frames': frames,
                       'fps': EPISODE_FPS, 'prompt': prompt, 'scene_number': index},
        })
    audio_id = 'narration'
    captions_id = 'captions'
    final_id = 'episode_final'
    audio_path = f'episodes/{project_id}/episode_{episode:02d}/narration_{run_id}.wav'
    captions_path = f'episodes/{project_id}/episode_{episode:02d}/captions_{run_id}.json'
    final_path = f'episodes/{project_id}/episode_{episode:02d}/episode_{run_id}.mp4'
    artifacts.extend((
        {'id': audio_id, 'kind': 'audio', 'path': audio_path, 'provenance': {'source': 'local'}},
        {'id': captions_id, 'kind': 'captions', 'path': captions_path, 'provenance': {'source': 'local'}},
        {'id': final_id, 'kind': 'video', 'path': final_path,
         'provenance': {'source': 'planned', 'job_id': 'assemble', 'inputs': [
             *(f'video_{index:02d}' for index in range(1, 9)), audio_id, captions_id]}},
    ))
    jobs.append({
        'id': 'assemble', 'adapter': 'episode_assembly', 'stage': 'assemble',
        'inputs': [*(f'video_{index:02d}' for index in range(1, 9)), audio_id, captions_id],
        'outputs': [final_id],
        'params': {'frames': EPISODE_FRAMES, 'fps': EPISODE_FPS},
    })
    return {
        'schema_version': 1,
        'project_id': project_id,
        'artifacts': artifacts,
        'jobs': jobs,
    }, workflows
