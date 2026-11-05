"""Bounded AI Motion Studio contracts and plans; never execute media or HTTP calls."""
from dataclasses import dataclass
import importlib.metadata
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit

MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARTIFACTS = 128
MAX_JOBS = 64
ADAPTERS = {
    'comfyui_wan': ('generate', {'workflow', 'image'}, {'video'}),
    'episode_assembly': ('assemble', {'video', 'audio', 'captions'}, {'video'}),
    'remotion': ('compose', {'composition', 'video', 'audio', 'captions'}, {'video'}),
    'whisperx': ('transcribe', {'audio', 'video'}, {'captions'}),
    'ffmpeg': ('encode', {'audio', 'video'}, {'video', 'audio'}),
}
KINDS = {'workflow', 'composition', 'video', 'audio', 'captions', 'image'}
EXTENSIONS = {'workflow': {'.json'}, 'composition': {'.tsx', '.jsx', '.ts', '.js'},
              'video': {'.mp4'}, 'audio': {'.wav'}, 'captions': {'.json'}, 'image': {'.jpg', '.jpeg', '.png', '.webp'}}
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\Z')
_RESERVED = re.compile(r'(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\.|$)', re.I)
_SECRET = re.compile(r'(?i)(?:bearer\s+|sk-[a-z0-9]{8,}|(?:api[_-]?key|password|secret|token)\s*[:=])')


class ContractError(ValueError):
    """Invalid local contract. Messages contain field names, never input values."""


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ContractError('invalid fields')


def _text(value, maximum=256):
    if (not isinstance(value, str) or not 0 < len(value) <= maximum
            or any(ord(c) < 32 for c in value) or _SECRET.search(value)
            or '://' in value):
        raise ContractError('invalid text or credentials')
    return value


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ContractError('invalid identifier')
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractError('invalid integer')
    return value


def _reparse(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def _root(value):
    if not isinstance(value, (str, Path)):
        raise ContractError('invalid project root')
    path = Path(value)
    if path.anchor.startswith('\\\\'):
        raise ContractError('network or device project root')
    if any(part in ('.', '..') or part.endswith((' ', '.')) or '~' in part
           or _RESERVED.match(part) for part in path.parts[1:]):
        raise ContractError('aliased project root')
    if not path.is_absolute() or not path.is_dir():
        raise ContractError('project root must be an existing absolute directory')
    for part in (path, *path.parents):
        if _reparse(part):
            raise ContractError('linked project root')
    return path.resolve(strict=True)


def scoped_path(project_root, relative, *, output=False):
    """Validate portable relative paths, including existing parents and reparse points.

    Outputs must not exist. This is planning-time validation; executors must repeat
    it immediately before opening files to guard against filesystem races.
    """
    root = _root(project_root)
    _text(relative, 240)
    parts = relative.split('/')
    if any(not re.fullmatch(r'[A-Za-z0-9_. -]{1,100}', p) or p in ('.', '..')
           or p.endswith((' ', '.')) or p.startswith(' ') or _RESERVED.match(p)
           for p in parts):
        raise ContractError('invalid relative path')
    path = root
    for part in parts:
        path = path / part
        if os.path.lexists(path):
            if _reparse(path):
                raise ContractError('linked path')
            if path != root.joinpath(*parts) and not path.is_dir():
                raise ContractError('non-directory parent')
    if not path.resolve().is_relative_to(root):
        raise ContractError('path escapes project')
    if output:
        if path.exists():
            raise ContractError('output already exists')
    elif not path.is_file() or path.stat().st_nlink != 1:
        raise ContractError('input must be a regular unlinked file')
    return path


@dataclass(frozen=True)
class MotionConfig:
    """Only this explicit configuration may carry an endpoint; credentials forbidden."""
    comfy_endpoint: str | None = None
    allow_remote: bool = False
    comfy_root: str | None = None
    executables: dict | None = None

    def __post_init__(self):
        if self.executables is not None:
            if not isinstance(self.executables, dict) or set(self.executables) - {'ffmpeg','ffprobe','remotion','whisperx','episode_assembly'}:
                raise ContractError('invalid executable configuration')
            for value in self.executables.values():
                if not isinstance(value, str):
                    raise ContractError('invalid executable path')
                path = Path(value)
                if not path.is_absolute() or not path.is_file() or _reparse(path):
                    raise ContractError('runtime must be an existing regular absolute file')
                _root(path.parent)
        if type(self.allow_remote) is not bool:
            raise ContractError('invalid remote policy')
        if self.comfy_root is not None:
            _root(self.comfy_root)
        if self.comfy_endpoint is not None:
            endpoint = self.comfy_endpoint
            if not isinstance(endpoint, str) or len(endpoint) > 512 or any(ord(c) <= 32 for c in endpoint):
                raise ContractError('invalid endpoint')
            try:
                url = urlsplit(endpoint)
                port = url.port
                host = url.hostname
                if (url.scheme not in ('http', 'https') or not host or url.username is not None
                        or url.password is not None or url.query or url.fragment or url.path not in ('', '/')
                        or '\\' in endpoint or '%' in endpoint or port == 0):
                    raise ValueError()
                try:
                    local = ipaddress.ip_address(host).is_loopback
                except ValueError:
                    local = host == 'localhost'
                if not local and not self.allow_remote:
                    raise ValueError()
            except ValueError:
                raise ContractError('endpoint requires explicit safe configuration') from None


def capability_inventory(config=None):
    """Presence/metadata only: no processes, network, model loading or installs.

    Installed does not mean healthy. No CLI version is guessed or executed.
    """
    config = config or MotionConfig()
    result = {}
    for adapter, (stage, _, _) in ADAPTERS.items():
        executable = runtime_path(adapter, config) if adapter != 'comfyui_wan' else None
        version = None
        if adapter == 'whisperx' and executable:
            try:
                version = importlib.metadata.version('whisperx')
            except importlib.metadata.PackageNotFoundError:
                pass
        installed = bool(executable)
        if adapter == 'comfyui_wan':
            installed = bool(config.comfy_root and
                             (Path(config.comfy_root) / 'main.py').is_file() and
                             not _reparse(Path(config.comfy_root) / 'main.py'))
        result[adapter] = {
            'contract_implemented': True, 'stage': stage,
            'installed': installed, 'version': version,
            'version_source': 'package_metadata' if version else None,
            'service_status': 'pending', 'execution_supported': True,
            'endpoint_configured': bool(config.comfy_endpoint) if adapter == 'comfyui_wan' else False,
        }
    return result


def runtime_path(adapter, config):
    configured = (config.executables or {}).get(adapter)
    if configured:
        return configured
    if adapter == 'episode_assembly':
        candidates = []
        if config.comfy_root:
            candidates.append(Path(config.comfy_root).parent / '.venv' / 'Scripts' / 'python.exe')
        local_app_data = os.environ.get('LOCALAPPDATA')
        if local_app_data:
            candidates.append(Path(local_app_data) / 'Central-IA' / 'motion-studio' /
                              '.venv' / 'Scripts' / 'python.exe')
        return next((str(path) for path in candidates
                     if path.is_file() and not _reparse(path)), None)
    return shutil.which(adapter)


def validate_media_with_ffprobe(path, config, *, expected_fps=None, expected_duration=None, require_audio=False):
    """Validate a produced MP4 with the trusted local ffprobe executable."""
    probe = runtime_path('ffprobe', config) or shutil.which('ffprobe')
    if not probe or not Path(probe).is_file():
        raise ContractError('ffprobe_unavailable')
    command = [probe, '-v', 'error', '-show_entries',
               'format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,nb_frames',
               '-of', 'json', str(path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True)
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        raise ContractError('ffprobe_invalid_media') from None
    streams = data.get('streams') if isinstance(data, dict) else None
    if not isinstance(streams, list): raise ContractError('ffprobe_invalid_media')
    video = next((item for item in streams if item.get('codec_type') == 'video'), None)
    audio = next((item for item in streams if item.get('codec_type') == 'audio'), None)
    if not video or video.get('codec_name') != 'h264' or int(video.get('width') or 0) < 2 or int(video.get('height') or 0) < 2:
        raise ContractError('invalid_mp4_video_stream')
    if require_audio and not audio: raise ContractError('missing_mp4_audio_stream')
    duration = float((data.get('format') or {}).get('duration') or 0)
    if duration <= 0: raise ContractError('invalid_mp4_duration')
    if expected_duration is not None and abs(duration - expected_duration) > 0.15:
        raise ContractError('invalid_mp4_duration')
    if expected_fps is not None:
        rate = str(video.get('avg_frame_rate') or '')
        try:
            numerator, denominator = rate.split('/', 1)
            actual_fps = float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            raise ContractError('invalid_mp4_fps') from None
        if abs(actual_fps - expected_fps) > 0.5:
            raise ContractError('invalid_mp4_fps')
    return {'duration': duration, 'fps': video.get('avg_frame_rate'), 'width': video['width'], 'height': video['height'], 'audio': bool(audio)}


def configured_motion():
    """Administrator-owned paths, never a path submitted by a model or browser."""
    paths = {name:os.environ['CENTRAL_MOTION_'+name.upper()] for name in ('ffmpeg','ffprobe','remotion','whisperx')
             if os.environ.get('CENTRAL_MOTION_'+name.upper())}
    comfy_root = os.environ.get('CENTRAL_MOTION_COMFY_ROOT')
    comfy_endpoint = os.environ.get('CENTRAL_MOTION_COMFY_ENDPOINT')
    local_app_data = os.environ.get('LOCALAPPDATA')
    if local_app_data and not comfy_root:
        installation = Path(local_app_data) / 'Central-IA' / 'motion-studio'
        candidate = installation / 'ComfyUI'
        python = installation / '.venv' / 'Scripts' / 'python.exe'
        models = (
            candidate / 'models' / 'diffusion_models' / 'wan2.1_t2v_1.3B_fp16.safetensors',
            candidate / 'models' / 'text_encoders' / 'umt5_xxl_fp8_e4m3fn_scaled.safetensors',
            candidate / 'models' / 'vae' / 'wan_2.1_vae.safetensors',
        )
        if (candidate.is_dir() and (candidate / 'main.py').is_file()
                and python.is_file() and all(path.is_file() for path in models)):
            comfy_root = str(candidate)
            comfy_endpoint = comfy_endpoint or 'http://127.0.0.1:8188'
            paths['episode_assembly'] = str(python)
    return MotionConfig(comfy_endpoint=comfy_endpoint,
                        comfy_root=comfy_root, executables=paths or None)


def _bounded_manifest(manifest):
    # Validate the object graph before serialization: cycles, excessive depth and
    # non-JSON objects must not escape as recursion/encoding exceptions.
    active = set()
    count = 0

    def visit(value, depth=0):
        nonlocal count
        count += 1
        if count > 12000 or depth > 12:
            raise ContractError('manifest complexity limit')
        if type(value) in (dict, list):
            if id(value) in active or len(value) > 1024:
                raise ContractError('manifest complexity limit')
            active.add(id(value))
            if isinstance(value, dict):
                for key, child in value.items():
                    _text(key, 64)
                    visit(child, depth + 1)
            else:
                for child in value:
                    visit(child, depth + 1)
            active.remove(id(value))
        elif isinstance(value, str):
            _text(value, 4096)
        elif value is not None and type(value) not in (bool, int):
            raise ContractError('invalid JSON value')
        elif type(value) is int and abs(value) > 10**12:
            raise ContractError('integer limit')

    visit(manifest)
    if len(json.dumps(manifest, ensure_ascii=True).encode()) > MAX_MANIFEST_BYTES:
        raise ContractError('manifest size limit')


def _parameters(adapter, params):
    if adapter == 'comfyui_wan':
        _keys(params, ('model', 'seed', 'frames', 'fps'), ('prompt', 'replace_clip_id', 'scene_number', 'image_sha256',
              'speech_artifact_id', 'speech_text', 'speaker', 'voice_profile'))
        if 'prompt' in params:_text(params['prompt'],1024)
        if params.get('replace_clip_id') is not None:_identifier(params['replace_clip_id'])
        if 'scene_number' in params:_integer(params['scene_number'], 1, 64)
        speech = ('speech_artifact_id', 'speech_text', 'speaker', 'voice_profile')
        if any(key in params for key in speech):
            if not all(key in params for key in speech):
                raise ContractError('incomplete scene speech')
            _identifier(params['speech_artifact_id'])
            _text(params['speech_text'], 300)
            _text(params['speaker'], 64)
            if not isinstance(params['voice_profile'], str) or not re.fullmatch(r'[a-f0-9]{16}', params['voice_profile']):
                raise ContractError('invalid voice profile')
        if params['model'] not in ('wan', 'ltxv'):
            raise ContractError('unsupported model family')
        _integer(params['seed'], 0, 2**32 - 1)
        _integer(params['frames'], 1, 4096)
        _integer(params['fps'], 1, 120)
        if params['model'] == 'ltxv' and (not isinstance(params.get('image_sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', params['image_sha256']) or (params['frames'] - 1) % 8):
            raise ContractError('invalid image conditioned scene')
    elif adapter == 'episode_assembly':
        _keys(params, ('frames', 'fps'))
        _integer(params['fps'], 1, 120)
        _integer(params['frames'], 1, 4096)
        if params['frames'] != params['fps'] * 60:
            raise ContractError('episode assembly must be exactly 60 seconds')
    elif adapter == 'remotion':
        _keys(params, ('composition', 'fps'))
        _identifier(params['composition'])
        _integer(params['fps'], 1, 120)
    elif adapter == 'whisperx':
        _keys(params, ('language', 'model'))
        if params['language'] not in ('en', 'pt', 'es', 'fr', 'de', 'it', 'ja') or params['model'] not in ('tiny', 'base', 'small', 'medium', 'large-v3'):
            raise ContractError('unsupported transcription parameters')
    else:
        _keys(params, ('profile',))
        if params['profile'] not in ('h264', 'pcm_s16le'):
            raise ContractError('unsupported encoding profile')


def validate_manifest(manifest, project_root):
    """Validate a v1 DAG and return a detached JSON copy; do not write anything."""
    root = _root(project_root)
    _bounded_manifest(manifest)
    _keys(manifest, ('schema_version', 'project_id', 'artifacts', 'jobs'))
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
        raise ContractError('unsupported schema version')
    _identifier(manifest['project_id'])
    artifacts, jobs = manifest['artifacts'], manifest['jobs']
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= MAX_ARTIFACTS or not isinstance(jobs, list) or not 1 <= len(jobs) <= MAX_JOBS:
        raise ContractError('invalid manifest bounds')
    by_id, paths = {}, set()
    for artifact in artifacts:
        _keys(artifact, ('id', 'kind', 'path', 'provenance'))
        identifier = _identifier(artifact['id'])
        kind = artifact['kind']
        if identifier in by_id or not isinstance(kind, str) or kind not in KINDS:
            raise ContractError('invalid artifact identity or kind')
        provenance = artifact['provenance']
        _keys(provenance, ('source',), ('job_id', 'inputs', 'sha256'))
        if provenance['source'] == 'local':
            if set(provenance) - {'source', 'sha256'}:
                raise ContractError('invalid local provenance')
            if 'sha256' in provenance and (not isinstance(provenance['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', provenance['sha256'])):
                raise ContractError('invalid digest')
        elif provenance['source'] == 'planned':
            if set(provenance) != {'source', 'job_id', 'inputs'}:
                raise ContractError('invalid planned provenance')
            _identifier(provenance['job_id'])
            if not isinstance(provenance['inputs'], list):
                raise ContractError('invalid provenance links')
        else:
            raise ContractError('invalid provenance source')
        path = scoped_path(root, artifact['path'], output=provenance['source'] == 'planned')
        key = artifact['path'].casefold()
        if key in paths or path.suffix.lower() not in EXTENSIONS[kind]:
            raise ContractError('artifact path collision or format')
        paths.add(key)
        by_id[identifier] = artifact
    seen, produced = set(), set()
    for job in jobs:
        _keys(job, ('id', 'adapter', 'stage', 'inputs', 'outputs', 'params'))
        identifier = _identifier(job['id'])
        adapter = job['adapter']
        if identifier in seen or not isinstance(adapter, str) or adapter not in ADAPTERS:
            raise ContractError('invalid job identity or adapter')
        stage, input_kinds, output_kinds = ADAPTERS[adapter]
        if job['stage'] != stage:
            raise ContractError('wrong adapter stage')
        for field in ('inputs', 'outputs'):
            links = job[field]
            if (not isinstance(links, list) or not 1 <= len(links) <= 16
                    or any(not isinstance(link, str) or link not in by_id for link in links)
                    or len(set(links)) != len(links)):
                raise ContractError('invalid artifact links')
        inputs = [by_id[i] for i in job['inputs']]
        outputs = [by_id[i] for i in job['outputs']]
        if any(a['kind'] not in input_kinds for a in inputs) or any(a['kind'] not in output_kinds for a in outputs) or len(outputs) != 1:
            raise ContractError('invalid adapter artifact kinds')
        if adapter == 'remotion':
            if sum(a['kind'] == 'composition' for a in inputs) != 1:
                raise ContractError('one composition required')
        elif adapter == 'episode_assembly':
            if (sum(a['kind'] == 'video' for a in inputs) != 8
                    or sum(a['kind'] == 'audio' for a in inputs) != 1
                    or sum(a['kind'] == 'captions' for a in inputs) != 1):
                raise ContractError('episode assembly requires eight scenes, narration and captions')
        elif adapter == 'comfyui_wan':
            if (sum(a['kind']=='workflow' for a in inputs)!=1 or
                sum(a['kind']=='image' for a in inputs)!=(1 if job['params'].get('model')=='ltxv' else 0)):
                raise ContractError('invalid video model inputs')
        elif len(inputs) != 1:
            raise ContractError('one input required')
        for artifact in inputs:
            if artifact['provenance']['source'] == 'planned' and artifact['id'] not in produced:
                raise ContractError('jobs must be in dependency order')
        for artifact in outputs:
            if artifact['provenance'] != {'source': 'planned', 'job_id': identifier, 'inputs': job['inputs']} or artifact['id'] in produced:
                raise ContractError('output provenance mismatch')
        _parameters(adapter, job['params'])
        if adapter == 'whisperx' and Path(outputs[0]['path']).name != Path(inputs[0]['path']).stem + '.json':
            raise ContractError('whisperx output must match input stem')
        if adapter == 'ffmpeg' and job['params']['profile'] == 'h264' and inputs[0]['kind'] != 'video':
            raise ContractError('h264 requires a video input')
        if adapter == 'ffmpeg' and outputs[0]['kind'] != ('video' if job['params']['profile'] == 'h264' else 'audio'):
            raise ContractError('encoding profile does not match output')
        seen.add(identifier)
        produced.update(job['outputs'])
    if any(a['provenance']['source'] == 'planned' and a['id'] not in produced for a in artifacts):
        raise ContractError('orphan planned artifact')
    return json.loads(json.dumps(manifest))


@dataclass(frozen=True)
class CommandPlan:
    argv: tuple[str, ...]
    cwd: str
    shell: bool = False


@dataclass(frozen=True)
class JobPlan:
    job_id: str
    adapter: str
    status: str  # planned, blocked (dependency unavailable), or unavailable
    reason: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    command: CommandPlan | None = None
    service_operation: str | None = None
    endpoint: str | None = None


def plan_jobs(manifest, project_root, config=None):
    """Describe pending services and typed argv. Never enqueue or execute a job."""
    config = config or MotionConfig()
    manifest = validate_manifest(manifest, project_root)
    root = _root(project_root)
    inventory = capability_inventory(config)
    artifacts = {a['id']: a for a in manifest['artifacts']}
    plans, statuses = [], {}
    for job in manifest['jobs']:
        adapter, params = job['adapter'], job['params']
        available = inventory[adapter]['installed']
        if adapter == 'comfyui_wan':
            available = available and bool(config.comfy_endpoint)
        blocked = any(a['provenance']['source'] == 'planned' and
                      statuses[a['provenance']['job_id']] != 'planned'
                      for a in (artifacts[i] for i in job['inputs']))
        status = 'unavailable' if not available else 'blocked' if blocked else 'planned'
        reason = 'runtime_missing_or_unconfigured' if not available else 'dependency_unavailable' if blocked else 'service_pending'
        command = None
        paths = [str(root / artifacts[i]['path']) for i in job['inputs']]
        output = str(root / artifacts[job['outputs'][0]]['path'])
        executable = runtime_path(adapter, config) if adapter != 'comfyui_wan' else None
        if status == 'planned' and adapter != 'comfyui_wan':
            if not executable:
                status, reason = 'unavailable', 'runtime_missing_or_unconfigured'
            else:
                if adapter == 'episode_assembly':
                    audio = next(path for path, artifact in zip(paths, (artifacts[i] for i in job['inputs'])) if artifact['kind'] == 'audio')
                    captions = next(path for path, artifact in zip(paths, (artifacts[i] for i in job['inputs'])) if artifact['kind'] == 'captions')
                    videos = [path for path, artifact in zip(paths, (artifacts[i] for i in job['inputs'])) if artifact['kind'] == 'video']
                    script = str(Path(__file__).with_name('motion_media.py'))
                    args = [script, 'assemble', '--audio', audio, '--captions', captions,
                            '--output', output, '--fps', str(params['fps']),
                            '--frames', str(params['frames']), *videos]
                elif adapter == 'ffmpeg':
                    args = ['-nostdin', '-n', '-protocol_whitelist', 'file', '-i', paths[0]]
                    args += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p'] if params['profile'] == 'h264' else ['-vn', '-c:a', 'pcm_s16le']
                    args += [output]
                elif adapter == 'whisperx':
                    args = [paths[0], '--language', params['language'], '--model', params['model'], '--output_format', 'json', '--output_dir', str(Path(output).parent), '--device', 'cpu', '--compute_type', 'int8', '--vad_method', 'silero']
                else:
                    entry = next(str(root / artifacts[i]['path']) for i in job['inputs'] if artifacts[i]['kind'] == 'composition')
                    args = ['render', entry, params['composition'], output, '--codec', 'h264', '--fps', str(params['fps']), '--concurrency', '1']
                prefix = [executable]
                if adapter == 'remotion' and Path(executable).suffix == '.js':
                    node = shutil.which('node')
                    if not node:
                        raise ContractError('node runtime missing for remotion')
                    prefix = [node, executable]
                command = CommandPlan(tuple([*prefix, *args]), str(root))
        plans.append(JobPlan(job['id'], adapter, status, reason, tuple(job['inputs']),
                             tuple(job['outputs']), command,
                             'enqueue_workflow' if adapter == 'comfyui_wan' and status == 'planned' else None,
                             config.comfy_endpoint if adapter == 'comfyui_wan' else None))
        statuses[job['id']] = status
    return tuple(plans)
