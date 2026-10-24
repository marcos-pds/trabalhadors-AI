"""Live execution activity, mid-run feedback, preview discovery and stop safeguards."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from central.computer_access import set_policy
from central.database import Database, utcnow
from central.agent_autonomy import consume_run_feedback
from central.live_preview import candidates
from central.workspace_tools import stop_run_commands, reset_run_commands


def test_adjustments_are_persistent_scoped_and_consumed_once(monkeypatch, tmp_path):
    from central.main import app, DB, ENGINE
    import uuid
    headers = {'X-Central-Request': '1'}
    folder = tmp_path / 'sandbox'
    folder.mkdir()
    with TestClient(app) as client, TestClient(app) as other:
        def reg(c):
            result = c.post('/api/register', headers=headers, json={
                'email': uuid.uuid4().hex + '@example.com', 'password': 'supersecretpassword'})
            assert result.status_code == 200, result.text
            return result.json()['id']
        user = reg(client)
        reg(other)
        set_policy(DB, user, 'full', str(folder))
        # Don't schedule external provider calls in this endpoint test.
        monkeypatch.setattr(ENGINE, 'schedule', lambda run_id: None)
        cid = client.post('/api/conversations', headers=headers,
                          json={'title': 'Live coding'}).json()['id']
        created = client.post('/api/runs', headers=headers, json={
            'conversation_id': cid,
            'prompt': 'Desenvolva uma landing page React real',
            'mode': 'team', 'autonomous': True})
        assert created.status_code == 200, created.text
        rid = created.json()['id']
        assert other.get('/api/runs/' + rid + '/activity').status_code == 404
        assert other.post('/api/runs/' + rid + '/feedback', headers=headers,
                          json={'message': 'Mudar o botão'}).status_code == 404
        response = client.post('/api/runs/' + rid + '/feedback', headers=headers,
                               json={'message': 'Troque a cor do botão para azul.'})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'queued'
        assert client.post('/api/runs/' + rid + '/feedback',
                           json={'message': 'Outro ajuste'}).status_code == 403
        assert client.post('/api/runs/' + rid + '/feedback', headers=headers,
                           json={'message': 'x' * 1801}).status_code == 422
        activity = client.get('/api/runs/' + rid + '/activity')
        assert activity.status_code == 200
        assert any(e['event'] == 'workspace_feedback_received'
                   for e in activity.json()['events'])
        assert consume_run_feedback(DB, user, rid) == ['Troque a cor do botão para azul.']
        assert consume_run_feedback(DB, user, rid) == []
        stopped = client.post('/api/runs/' + rid + '/cancel')
        assert stopped.status_code == 200, stopped.text
        saved_status = DB.one('SELECT status FROM runs WHERE id=?', (rid,))['status']
        assert saved_status == 'cancelled', saved_status
        assert client.post('/api/runs/' + rid + '/feedback', headers=headers,
                           json={'message': 'Mudança após cancelar'}).status_code == 409


def test_preview_discovery_stays_in_granted_folder(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    app = root / 'apps' / 'web'
    app.mkdir(parents=True)
    (app / 'package.json').write_text(json.dumps({
        'name': 'new-landing-page', 'scripts': {'dev': 'vite'}}), encoding='utf-8')
    (root / 'package.json').write_text(json.dumps({'name': 'no-dev'}), encoding='utf-8')
    (root / 'node_modules').mkdir()
    (root / 'node_modules' / 'package.json').write_text(json.dumps({
        'scripts': {'dev': 'blocked'}}), encoding='utf-8')
    found = candidates(str(root))
    assert found == [{'cwd': 'apps/web', 'name': 'new-landing-page'}]


def test_cancel_registry_prevents_late_command_start(monkeypatch, tmp_path):
    from central import workspace_tools as tools
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'hello.py').write_text('print(1)', encoding='utf-8')
    called = []
    monkeypatch.setattr(tools, 'command_spec', lambda folder, request: {
        'cwd': '', 'root': root, 'argv': ['fake'],
        'label': 'fake test'})
    monkeypatch.setattr(tools.subprocess, 'Popen', lambda *args, **kwargs: called.append(1))
    rid = 'cancelled-task'
    stop_run_commands(rid)
    try:
        outcome = tools.execute(str(root), {'action': 'command', 'command': 'python_test'},
                                run_id=rid)
        assert outcome['success'] is False
        assert 'cancelada' in outcome['output']
        assert not called
    finally:
        reset_run_commands(rid)
