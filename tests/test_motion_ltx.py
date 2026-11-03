import hashlib
import json
import base64
import uuid

import pytest
from fastapi.testclient import TestClient

from central.comfy_motion import prepare_workflow
from central.motion_contracts import ContractError, MotionConfig, validate_manifest
from central.motion_ltx import ENCODER, MODEL, ltx_workflow
from central.computer_access import set_policy
from central.main import DB, MOTION, app


def test_ltx_scene_keeps_reference_as_local_input_and_flattens_video_format(tmp_path):
    comfy = tmp_path / 'comfy'
    image_name = 'central_ltx_' + 'a' * 32 + '.jpg'
    for folder, name in (('models/checkpoints', MODEL), ('models/text_encoders', ENCODER)):
        path = comfy / folder / name
        path.parent.mkdir(parents=True)
        path.write_bytes(b'model')
    image = comfy / 'input' / image_name
    image.parent.mkdir()
    image.write_bytes(b'\xff\xd8\xff' + b'image')
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    workflow = tmp_path / 'scene.json'
    workflow.write_text(json.dumps(ltx_workflow('Lara turns', image_name, 7, 81, 16, 'scene')))
    params = {'model': 'ltxv', 'seed': 7, 'frames': 81, 'fps': 16, 'prompt': 'Lara turns', 'image_sha256': digest, 'scene_number': 3}
    graph, models, _ = prepare_workflow(workflow, params, 'owned_scene', MotionConfig(comfy_root=str(comfy), comfy_endpoint='http://127.0.0.1:8188'))
    assert graph['13']['inputs']['format'] == 'mp4'
    assert graph['13']['inputs']['format.codec'] == 'h264'
    assert graph['6']['inputs']['image'] == ['5', 0]
    assert len(models) == 2

    reference = tmp_path / 'reference.jpg'
    reference.write_bytes(image.read_bytes())
    manifest = {
        'schema_version': 1, 'project_id': 'motion-pilot',
        'artifacts': [
            {'id': 'workflow', 'kind': 'workflow', 'path': workflow.name, 'provenance': {'source': 'local'}},
            {'id': 'reference', 'kind': 'image', 'path': reference.name, 'provenance': {'source': 'local', 'sha256': digest}},
            {'id': 'video', 'kind': 'video', 'path': 'scene.mp4', 'provenance': {'source': 'planned', 'job_id': 'generate', 'inputs': ['workflow', 'reference']}},
        ],
        'jobs': [{'id': 'generate', 'adapter': 'comfyui_wan', 'stage': 'generate', 'inputs': ['workflow', 'reference'], 'outputs': ['video'], 'params': params}],
    }
    assert validate_manifest(manifest, tmp_path)['jobs'][0]['params']['model'] == 'ltxv'
    image.write_bytes(b'changed')
    with pytest.raises(ContractError, match='input_changed'):
        prepare_workflow(workflow, params, 'owned_scene', MotionConfig(comfy_root=str(comfy), comfy_endpoint='http://127.0.0.1:8188'))


def test_ltx_endpoint_queues_owned_reference_and_rejects_invalid_image(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_MOTION_WORKER', '0')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr('central.comfy_runtime.COMFY_RUNTIME.ensure_started', lambda config: 'running')
    media = tmp_path / 'media'
    media.mkdir()
    comfy = tmp_path / 'comfy'
    (comfy / 'main.py').parent.mkdir()
    (comfy / 'main.py').write_text('fixture')
    (comfy / 'input').mkdir()
    for folder, name in (('checkpoints', MODEL), ('text_encoders', ENCODER)):
        path = comfy / 'models' / folder / name
        path.parent.mkdir(parents=True)
        path.write_bytes(b'model')
    image = b'\xff\xd8\xff' + b'x' * 125
    payload = {'project_id': 'lara-pilot', 'episode': 1, 'scene': 3,
               'prompt': 'Lara turns toward the doorway.', 'seed': 42,
               'frames': 81, 'fps': 16,
               'image_data': 'data:image/jpeg;base64,' + base64.b64encode(image).decode()}
    headers = {'X-Central-Request': '1'}
    with TestClient(app) as client:
        response = client.post('/api/register', headers=headers,
                               json={'email': f'{uuid.uuid4().hex}@example.test', 'password': 'LocalTestPassword123!'})
        assert response.status_code == 200
        user = response.json()['id']
        set_policy(DB, user, 'full', str(media))
        configured = client.post('/api/motion/tools', headers=headers,
                                 json={'comfy_endpoint': 'http://127.0.0.1:8188', 'comfy_root': str(comfy), 'executables': {}})
        assert configured.status_code == 200
        queued = client.post('/api/motion/ltx/scenes', headers=headers, json=payload)
        assert queued.status_code == 200, queued.text
        run = queued.json()
        manifest = json.loads(DB.one('SELECT manifest FROM motion_runs WHERE id=?', (run['id'],))['manifest'])
        assert [item['kind'] for item in manifest['artifacts']] == ['workflow', 'image', 'video']
        assert manifest['jobs'][0]['params']['image_sha256'] == hashlib.sha256(image).hexdigest()
        assert client.post('/api/motion/ltx/scenes', headers=headers,
                           json={**payload, 'image_data': 'data:image/jpeg;base64,bad'}).status_code == 422
        MOTION.cancel(user, run['id'])
