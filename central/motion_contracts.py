"""Bounded AI Motion Studio contracts and plans; never execute media or HTTP calls."""
from dataclasses import dataclass
import importlib.metadata
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARTIFACTS = 128
MAX_JOBS = 64
ADAPTERS = {
    'comfyui_wan': ('generate', {'workflow'}, {'video'}),
    'remotion': ('compose', {'composition', 'video', 'audio', 'captions'}, {'video'}),
    'whisperx': ('transcribe', {'audio', 'video'}, {'captions'}),
    'ffmpeg': ('encode', {'audio', 'video'}, {'video', 'audio'}),
}
KINDS = {'workflow', 'composition', 'video', 'audio', 'captions'}
EXTENSIONS = {'workflow': {'.json'}, 'composition': {'.tsx', '.jsx', '.ts', '.js'},
              'video': {'.mp4'}, 'audio': {'.wav'}, 'captions': {'.json'}}
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

    def __post_init__(self):
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
        executable = shutil.which(adapter) if adapter != 'comfyui_wan' else None
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
            'service_status': 'pending', 'execution_supported': False,
            'endpoint_configured': bool(config.comfy_endpoint) if adapter == 'comfyui_wan' else False,
        }
    return result


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
        _keys(params, ('model', 'seed', 'frames', 'fps'))
        if params['model'] != 'wan':
            raise ContractError('unsupported model family')
        _integer(params['seed'], 0, 2**32 - 1)
        _integer(params['frames'], 1, 4096)
        _integer(params['fps'], 1, 120)
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
        executable = shutil.which(adapter) if adapter != 'comfyui_wan' else None
        if status == 'planned' and adapter != 'comfyui_wan':
            if not executable:
                status, reason = 'unavailable', 'runtime_missing_or_unconfigured'
            else:
                if adapter == 'ffmpeg':
                    args = ['-nostdin', '-n', '-protocol_whitelist', 'file', '-i', paths[0]]
                    args += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p'] if params['profile'] == 'h264' else ['-vn', '-c:a', 'pcm_s16le']
                    args += [output]
                elif adapter == 'whisperx':
                    args = [paths[0], '--language', params['language'], '--model', params['model'], '--output_format', 'json', '--output_dir', str(Path(output).parent)]
                else:
                    entry = next(str(root / artifacts[i]['path']) for i in job['inputs'] if artifacts[i]['kind'] == 'composition')
                    args = ['render', entry, params['composition'], output, '--codec', 'h264', '--fps', str(params['fps'])]
                command = CommandPlan(tuple([executable, *args]), str(root))
        plans.append(JobPlan(job['id'], adapter, status, reason, tuple(job['inputs']),
                             tuple(job['outputs']), command,
                             'enqueue_workflow' if adapter == 'comfyui_wan' and status == 'planned' else None,
                             config.comfy_endpoint if adapter == 'comfyui_wan' else None))
        statuses[job['id']] = status
    return tuple(plans)
