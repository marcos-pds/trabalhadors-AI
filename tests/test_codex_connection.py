"""API authorization and native connection persistence; no model calls."""
import uuid
import json

import pytest
from fastapi.testclient import TestClient

from central.codex_bridge import CERTIFIED_VERSION
from central.main import app, DB

HEADERS = {'X-Central-Request': '1'}


def register(client):
    response = client.post('/api/register', headers=HEADERS, json={
        'email': uuid.uuid4().hex + '@example.test', 'password': 'local-test-password-123'})
    assert response.status_code == 200
    return response.json()['id']


@pytest.fixture
def discovery(monkeypatch):
    result = {'status': 'ok', 'authenticated': True, 'auth_type': 'chatgpt',
              'version': CERTIFIED_VERSION, 'models': [{'id': 'test-model', 'name': 'Fixture model'}]}
    monkeypatch.setattr('central.codex_runtime.probe', lambda: result)
    return result


def test_connect_is_explicit_scoped_idempotent_and_contains_no_credentials(discovery):
    with TestClient(app) as first, TestClient(app) as other:
        owner = register(first)
        register(other)
        assert first.post('/api/runtimes/codex/connect', json={'model': 'test-model'}).status_code == 403
        invalid = first.post('/api/runtimes/codex/connect', headers=HEADERS, json={'model': 'unknown'})
        assert invalid.status_code == 422
        created = first.post('/api/runtimes/codex/connect', headers=HEADERS, json={'model': 'test-model'})
        assert created.status_code == 200, created.text
        body = created.json()
        provider = body['provider']
        assert provider['kind'] == provider['auth_type'] == 'codex_cli'
        assert body['generation_tested'] is False
        assert DB.one('SELECT api_key_enc,chatgpt_connection_id FROM providers WHERE id=?', (provider['id'],)) == {
            'api_key_enc': None, 'chatgpt_connection_id': None}
        worker = DB.one('SELECT * FROM agents WHERE id=?', (body['agent_id'],))
        assert worker['user_id'] == owner and worker['provider_id'] == provider['id']
        assert worker['max_concurrency'] == 1
        reviewer = DB.one('SELECT * FROM agents WHERE id=?', (body['reviewer_id'],))
        assert reviewer['specialty'] == 'review' and reviewer['provider_id'] == provider['id']
        repeated = first.post('/api/runtimes/codex/connect', headers=HEADERS, json={'model': 'test-model'}).json()
        assert repeated['agent_id'] == body['agent_id']
        assert repeated['provider']['id'] == provider['id']
        assert repeated['reviewer_id'] == body['reviewer_id']
        assert all(row['id'] != provider['id'] for row in other.get('/api/providers').json())
        assert other.post('/api/providers/' + provider['id'] + '/test', headers=HEADERS).status_code == 404
        assert first.post('/api/providers/' + provider['id'] + '/test', headers=HEADERS).json()['generation_tested'] is False
        assert DB.one('SELECT count(*) n FROM codex_step_sessions')['n'] == 0


@pytest.mark.parametrize('field,value', [('status', 'not_found'), ('auth_type', 'apiKey'), ('version', '0.0.0')])
def test_unverified_runtime_cannot_connect(discovery, field, value):
    discovery[field] = value
    with TestClient(app) as client:
        owner = register(client)
        assert client.post('/api/runtimes/codex/connect', headers=HEADERS, json={'model': 'test-model'}).status_code == 409
        assert not DB.all("SELECT id FROM providers WHERE user_id=? AND kind='codex_cli'", (owner,))


def test_specialist_pack_requires_opt_in_and_preserves_existing_agent(discovery):
    with TestClient(app) as client:
        register(client)
        before = client.get('/api/agents').json()
        preview = client.get('/api/agents/specialist-pack').json()['profiles']
        assert len(preview) == 5
        assert len(client.get('/api/agents').json()) == len(before)
        assert client.post('/api/agents/specialist-pack').status_code == 403
        added = client.post('/api/agents/specialist-pack', headers=HEADERS).json()
        assert len(added['created_ids']) == 5
        assert client.get('/api/agents/specialist-pack').json()['profiles'] == []
        again = client.post('/api/agents/specialist-pack', headers=HEADERS).json()
        assert again['created_ids'] == []
        assert len(client.get('/api/agents').json()) == len(before) + 5
        for previous in before:
            assert DB.one('SELECT instructions FROM agents WHERE id=?', (previous['id'],))['instructions'] == previous['instructions']


def test_single_selected_codex_gets_review_on_same_runtime(discovery, monkeypatch, tmp_path):
    from central.main import ENGINE
    from central.computer_access import set_policy
    monkeypatch.setattr(ENGINE, 'schedule', lambda run_id: None)
    with TestClient(app) as client:
        owner = register(client)
        set_policy(DB, owner, 'full', str(tmp_path))
        connected = client.post('/api/runtimes/codex/connect', headers=HEADERS,
                                json={'model': 'test-model'}).json()
        cid = client.post('/api/conversations', headers=HEADERS, json={'title': 'Native'}).json()['id']
        response = client.post('/api/runs', headers=HEADERS, json={
            'conversation_id': cid, 'prompt': 'Deixe o botão verde.', 'mode': 'manual',
            'agent_ids': [connected['agent_id']], 'autonomous': True})
        assert response.status_code == 200, response.text
        steps = DB.all('SELECT s.id,s.agent_id,s.deps,a.provider_id,a.specialty FROM steps s '
                       'JOIN agents a ON a.id=s.agent_id WHERE s.run_id=? ORDER BY s.rowid',
                       (response.json()['id'],))
        assert [step['specialty'] for step in steps] == ['code', 'review']
        assert steps[1]['agent_id'] == connected['reviewer_id']
        assert json.loads(steps[1]['deps']) == [steps[0]['id']]
        assert all(step['provider_id'] == connected['provider']['id'] for step in steps)
        with pytest.raises(ValueError, match='Revisor'):
            ENGINE.create_run(owner, cid, 'Corrija o botão.', 'manual', autonomous=True,
                              flow={'nodes': [{'id': 'only-code', 'kind': 'agent',
                                               'agent_id': connected['agent_id'], 'name': 'Code', 'deps': []}]})
        assert client.post('/api/runs/' + response.json()['id'] + '/cancel', headers=HEADERS).status_code == 200
