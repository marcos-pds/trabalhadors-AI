"""Motion contract tests use inert local files; no media process or HTTP call."""
import copy
import json
from pathlib import Path

import pytest

from central import motion_contracts as motion


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'clip.mp4').write_bytes(b'inert fixture')
    return tmp_path


def manifest(adapter='ffmpeg'):
    kinds = {'ffmpeg': ('video', 'clip.mp4', 'video', 'render.mp4', {'profile': 'h264'}),
             'whisperx': ('video', 'clip.mp4', 'captions', 'out/clip.json', {'language': 'pt', 'model': 'small'}),
             'remotion': ('composition', 'scene.tsx', 'video', 'render.mp4', {'composition': 'Intro', 'fps': 30}),
             'comfyui_wan': ('workflow', 'workflow.json', 'video', 'render.mp4', {'model': 'wan', 'seed': 1, 'frames': 81, 'fps': 24})}
    kind, path, output_kind, output, params = kinds[adapter]
    return {'schema_version': 1, 'project_id': 'demo', 'artifacts': [
        {'id': 'input', 'kind': kind, 'path': path, 'provenance': {'source': 'local'}},
        {'id': 'output', 'kind': output_kind, 'path': output,
         'provenance': {'source': 'planned', 'job_id': 'job', 'inputs': ['input']}}],
        'jobs': [{'id': 'job', 'adapter': adapter, 'stage': motion.ADAPTERS[adapter][0],
                  'inputs': ['input'], 'outputs': ['output'], 'params': params}]}


@pytest.mark.parametrize('adapter', list(motion.ADAPTERS))
def test_contracts_validate_and_missing_runtimes_are_unavailable(project, monkeypatch, adapter):
    data = manifest(adapter)
    (project / data['artifacts'][0]['path']).write_text('{}')
    monkeypatch.setattr(motion.shutil, 'which', lambda _: None)
    result = motion.validate_manifest(data, project)
    assert result == data and result is not data
    plan, = motion.plan_jobs(data, project)
    assert plan.status == 'unavailable'
    assert plan.command is None and plan.service_operation is None
    assert not (project / data['artifacts'][1]['path']).exists()


@pytest.mark.parametrize('adapter', ['ffmpeg', 'whisperx', 'remotion'])
def test_typed_commands_pending_only(project, monkeypatch, adapter):
    data = manifest(adapter)
    (project / data['artifacts'][0]['path']).write_text('{}')
    monkeypatch.setattr(motion.shutil, 'which', lambda name: str(project / (name + '.exe')))
    plan, = motion.plan_jobs(data, project)
    assert plan.status == 'planned' and plan.reason == 'service_pending'
    assert plan.command.shell is False
    assert isinstance(plan.command.argv, tuple)
    assert all(isinstance(arg, str) for arg in plan.command.argv)
    assert plan.command.cwd == str(project.resolve())
    assert str(project / data['artifacts'][1]['path']) in plan.command.argv or adapter == 'whisperx'
    assert not (project / data['artifacts'][1]['path']).exists()


def test_comfy_service_is_declarative(project):
    (project / 'workflow.json').write_text('{}')
    (project / 'main.py').write_text('# inert')
    config = motion.MotionConfig(comfy_endpoint='http://127.0.0.1:8188', comfy_root=str(project))
    plan, = motion.plan_jobs(manifest('comfyui_wan'), project, config)
    assert plan.status == 'planned' and plan.service_operation == 'enqueue_workflow'
    assert plan.command is None
    assert plan.endpoint == config.comfy_endpoint


@pytest.mark.parametrize('path', [
    '../escape.mp4', '/escape.mp4', 'C:/escape.mp4', 'C:escape.mp4',
    r'out\escape.mp4', '//host/share/a.mp4', 'out//a.mp4', 'out/./a.mp4',
    'out/../a.mp4', 'out/a.mp4:stream', 'NUL.mp4', 'con/a.mp4', 'COM1.mp4',
    'LPT9.mp4', 'out./a.mp4', 'out /a.mp4', 'out/a.mp4 ', 'OUT~1/a.mp4',
    'https://example.org/a.mp4', 'out/%2e%2e/a.mp4'])
def test_reject_output_escape_and_windows_aliases(project, path):
    data = manifest()
    data['artifacts'][1]['path'] = path
    with pytest.raises(motion.ContractError):
        motion.validate_manifest(data, project)


def test_existing_output_and_file_parent_rejected(project):
    data = manifest()
    (project / 'render.mp4').write_bytes(b'existing')
    with pytest.raises(motion.ContractError, match='already exists'):
        motion.validate_manifest(data, project)
    data['artifacts'][1]['path'] = 'clip.mp4/render.mp4'
    with pytest.raises(motion.ContractError, match='non-directory'):
        motion.validate_manifest(data, project)


def test_symlink_ancestor_and_root_rejected(project, tmp_path):
    target = tmp_path / 'actual'
    target.mkdir()
    link = project / 'linked'
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('OS requires symlink privilege')
    with pytest.raises(motion.ContractError, match='linked'):
        motion.scoped_path(project, 'linked/render.mp4', output=True)
    with pytest.raises(motion.ContractError, match='linked'):
        motion.scoped_path(link, 'render.mp4', output=True)
    dangling = project / 'dangling.mp4'
    dangling.symlink_to(target / 'missing.mp4')
    with pytest.raises(motion.ContractError, match='linked'):
        motion.scoped_path(project, 'dangling.mp4', output=True)


@pytest.mark.parametrize('mutate', [
    lambda d: d.update(schema_version=True),
    lambda d: d.update(status='completed'),
    lambda d: d['jobs'][0].update(stage='generate'),
    lambda d: d['jobs'][0].update(adapter=[]),
    lambda d: d['jobs'][0].update(inputs=['missing']),
    lambda d: d['jobs'][0].update(inputs=['input', 'input']),
    lambda d: d['jobs'][0].update(outputs=['input']),
    lambda d: d['jobs'][0]['params'].update(shell=True),
    lambda d: d['jobs'][0]['params'].update(profile='arbitrary'),
    lambda d: d['artifacts'][0].update(kind=[]),
    lambda d: d['artifacts'][0]['provenance'].update(sha256=[]),
    lambda d: d['artifacts'][1]['provenance'].update(job_id='different'),
    lambda d: d['artifacts'][1]['provenance'].update(inputs=[]),
    lambda d: d['artifacts'][1].update(path='CLIP.mp4'),
    lambda d: d['artifacts'][0].update(endpoint='http://localhost:8000'),
    lambda d: d['jobs'][0]['params'].update(token='private'),
])
def test_malformed_manifests(project, mutate):
    data = manifest()
    mutate(data)
    with pytest.raises(motion.ContractError):
        motion.validate_manifest(data, project)


@pytest.mark.parametrize('adapter,params', [
    ('comfyui_wan', {'model': 'wan', 'seed': True, 'frames': 1, 'fps': 24}),
    ('comfyui_wan', {'model': 'other', 'seed': 1, 'frames': 1, 'fps': 24}),
    ('remotion', {'composition': '--help', 'fps': 30}),
    ('remotion', {'composition': 'Intro', 'fps': 1000}),
    ('whisperx', {'language': 'auto', 'model': 'small'}),
    ('whisperx', {'language': 'pt', 'model': 'http://host/model'}),
])
def test_adapter_parameter_validation(project, adapter, params):
    data = manifest(adapter)
    (project / data['artifacts'][0]['path']).write_text('{}')
    data['jobs'][0]['params'] = params
    with pytest.raises(motion.ContractError):
        motion.validate_manifest(data, project)


@pytest.mark.parametrize('endpoint', [
    'https://user:password@example.com', 'http://127.0.0.1:8188/?token=secret',
    'file:///tmp/server', 'http://127.0.0.1:bad', 'http://127.0.0.1:0',
    'http://localhost.evil:8188', 'http://192.168.1.5:8188',
    'http://localhost:8188/#token', 'http://localhost:8188/api', 'http://localhost\\@evil'])
def test_endpoint_policy(endpoint):
    with pytest.raises(motion.ContractError):
        motion.MotionConfig(comfy_endpoint=endpoint)


def test_explicit_remote_config():
    assert motion.MotionConfig(comfy_endpoint='https://render.example', allow_remote=True).allow_remote
    with pytest.raises(motion.ContractError):
        motion.MotionConfig(comfy_endpoint='https://user:pass@render.example', allow_remote=True)


def test_bounds_and_cycles(project):
    for field, limit in [('artifacts', motion.MAX_ARTIFACTS), ('jobs', motion.MAX_JOBS)]:
        data = manifest()
        data[field] *= limit + 1
        with pytest.raises(motion.ContractError):
            motion.validate_manifest(data, project)
    data = manifest()
    data['recursive'] = data
    with pytest.raises(motion.ContractError):
        motion.validate_manifest(data, project)
    data = manifest()
    data['project_id'] = 'a' * 5000
    with pytest.raises(motion.ContractError):
        motion.validate_manifest(data, project)


def test_dependencies_and_blocked_status(project, monkeypatch):
    data = manifest()
    next_job = {'id': 'transcribe', 'adapter': 'whisperx', 'stage': 'transcribe',
                'inputs': ['output'], 'outputs': ['captions'],
                'params': {'language': 'pt', 'model': 'small'}}
    data['artifacts'].append({'id': 'captions', 'kind': 'captions', 'path': 'render.json',
                             'provenance': {'source': 'planned', 'job_id': 'transcribe', 'inputs': ['output']}})
    data['jobs'].append(next_job)
    monkeypatch.setattr(motion.shutil, 'which', lambda name: '/local/whisperx' if name == 'whisperx' else None)
    plans = motion.plan_jobs(data, project)
    assert [p.status for p in plans] == ['unavailable', 'blocked']
    data['jobs'].reverse()
    with pytest.raises(motion.ContractError, match='dependency order'):
        motion.validate_manifest(data, project)


def test_inventory_no_execution_or_version_guessing(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('process executed'))
    monkeypatch.setattr(motion.shutil, 'which', lambda name: '/local/' + name)
    monkeypatch.setattr(motion.importlib.metadata, 'version', lambda name: '3.1.0')
    result = motion.capability_inventory()
    assert result['whisperx']['version'] == '3.1.0'
    assert result['ffmpeg']['version'] is None
    assert not result['comfyui_wan']['installed']
    assert all(v['contract_implemented'] and not v['execution_supported'] and v['service_status'] == 'pending' for v in result.values())


def test_no_execution_and_detached_manifest(project, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('process executed'))
    data = manifest()
    validated = motion.validate_manifest(data, project)
    validated['jobs'][0]['params']['profile'] = 'changed'
    assert data['jobs'][0]['params']['profile'] == 'h264'
    motion.plan_jobs(data, project)
    assert sorted(p.name for p in project.iterdir()) == ['clip.mp4']


def test_root_alias_rejected(project):
    with pytest.raises(motion.ContractError):
        motion.scoped_path(str(project / '..' / project.name), 'render.mp4', output=True)


def test_reparse_detection_without_symlink_privilege():
    from types import SimpleNamespace
    path = SimpleNamespace(is_symlink=lambda: False,
                           lstat=lambda: SimpleNamespace(st_file_attributes=0x400))
    assert motion._reparse(path)


def test_input_hardlink_rejected(project):
    import os
    try:
        os.link(project / 'clip.mp4', project / 'alias.mp4')
    except OSError:
        pytest.skip('hard links not supported')
    with pytest.raises(motion.ContractError, match='unlinked'):
        motion.validate_manifest(manifest(), project)


def test_wrong_artifact_kind_and_whisperx_output(project):
    data = manifest('whisperx')
    data['artifacts'][1]['path'] = 'wrong.json'
    with pytest.raises(motion.ContractError, match='input stem'):
        motion.validate_manifest(data, project)
    data = manifest()
    data['artifacts'][0]['kind'] = 'captions'
    data['artifacts'][0]['path'] = 'captions.json'
    (project / 'captions.json').write_text('{}')
    with pytest.raises(motion.ContractError, match='artifact kinds'):
        motion.validate_manifest(data, project)


def test_orphan_and_duplicate_job_rejected(project):
    data = manifest()
    orphan = copy.deepcopy(data['artifacts'][1])
    orphan.update(id='orphan', path='orphan.mp4')
    data['artifacts'].append(orphan)
    with pytest.raises(motion.ContractError, match='orphan'):
        motion.validate_manifest(data, project)
    data = manifest()
    data['jobs'].append(copy.deepcopy(data['jobs'][0]))
    with pytest.raises(motion.ContractError, match='identity'):
        motion.validate_manifest(data, project)


def test_manifest_byte_limit(project):
    data = manifest()
    # Valid JSON graph below node/depth limits, but above the serialized byte cap.
    data['padding'] = ['a' * 4000 for _ in range(70)]
    with pytest.raises(motion.ContractError, match='size limit'):
        motion.validate_manifest(data, project)


@pytest.mark.parametrize('value', ['token=private', 'Bearer private', 'sk-abcdefghijk', 'https://host'])
def test_credential_and_endpoint_text_is_not_echoed(project, value):
    data = manifest()
    data['project_id'] = value
    with pytest.raises(motion.ContractError) as exc:
        motion.validate_manifest(data, project)
    assert value not in str(exc.value)
