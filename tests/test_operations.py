"""Privacy-first operations, explicit policies, tenant-scoped reads and audit tests."""
import json
import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from central.database import Database, utcnow
from central.ops import audit, audit_history, overview
from central.run_policy import classify_task, validate_run_policy
from central.observability import correlation_id, log_event, request_context
from central.main import app

HEADERS = {'X-Central-Request': '1'}


def account(client):
    result = client.post('/api/register', headers=HEADERS, json={
        'email': uuid.uuid4().hex + '@example.org',
        'password': 'strongtestpassword'})
    assert result.status_code == 200, result.text
    return result.json()['id']


def test_classification_policies_are_explicit_and_never_grant_access():
    code = classify_task('Desenvolva uma landing page React com testes', True)
    assert code['task_type'] == 'code'
    assert code['policy_version'] == 1
    assert code['required_checks'] == ['actual_file_change', 'build_or_test_after_change']
    assert code['recommended_review']
    inspect = classify_task('Leia os arquivos do repositório', True)
    assert inspect['task_type'] == 'inspection'
    assert inspect['required_checks'] == ['recorded_read_or_listing']
    assert classify_task('Me dê um prompt para criar uma API')['task_type'] == 'conversation'
    assert classify_task('Explique os conceitos de API')['task_type'] == 'conversation'
    try:
        validate_run_policy(classify_task('Crie uma interface web', False), False)
    except ValueError:
        pass
    else:
        raise AssertionError('Workspace policy cannot bypass autonomy')


def test_structured_logs_never_include_arbitrary_secrets_or_request_content(monkeypatch):
    import central.observability as obs
    lines = []
    monkeypatch.setattr(obs._logger, 'info', lambda value: lines.append(value))
    assert correlation_id('mine-123') == 'mine-123'
    assert correlation_id('not valid: token=secret123') != 'not valid: token=secret123'
    marker = request_context.set('request-123')
    try:
        log_event('run_event', run_id='r-1', status='completed',
                  prompt='PRIVATE_PROMPT_ABC',
                  api_key='sk-private',
                  contents='PRIVATE_CONTENT',
                  category='ok')
    finally:
        request_context.reset(marker)
    result = json.loads(lines[-1])
    assert result['request_id'] == 'request-123'
    assert result['run_id'] == 'r-1'
    assert result['status'] == 'completed'
    assert 'PRIVATE_PROMPT_ABC' not in lines[-1]
    assert 'PRIVATE_CONTENT' not in lines[-1]
    assert 'sk-private' not in lines[-1]
    assert 'api_key' not in result


def test_aggregation_and_audit_never_mix_user_accounts():
    db = Database(':memory:')
    try:
        for user_id in ('u1', 'u2'):
            db.execute('INSERT INTO users VALUES(?,?,?,?)',
                       (user_id, user_id + '@example.com', 'hash', utcnow()))
            db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                       ('c-' + user_id, user_id, 'Title', None, utcnow(), utcnow()))
            db.execute(
                'INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,'
                'total_cost,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                ('run-' + user_id, user_id, 'c-' + user_id,
                 'Private task', 'failed' if user_id == 'u1' else 'completed',
                 'auto', '[]', '[]', 0.75 if user_id == 'u1' else 300,
                 utcnow(), utcnow()))
            db.execute(
                'INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) '
                'VALUES(?,?,?,?,?,?,?)',
                ('p-' + user_id, user_id, 'Provider ' + user_id, 'openai',
                 'https://example.org/v1', 'model', utcnow()))
        db.execute(
            'INSERT INTO provider_attempts(provider_id,model,success,category,'
            'http_status,latency_ms,run_id,step_id,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?)',
            ('p-u1', 'model', 0, 'timeout', 504, 123, 'run-u1', None, utcnow()))
        db.execute(
            'INSERT INTO provider_attempts(provider_id,model,success,category,'
            'http_status,latency_ms,run_id,step_id,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?)',
            ('p-u2', 'model', 1, None, 200, 456, 'run-u2', None, utcnow()))
        audit(db, 'u1', 'run_resumed', 'run', 'run-u1')
        audit(db, 'u2', 'run_created', 'run', 'run-u2')
        one = overview(db, 'u1')
        assert one['last_24h']['total'] == 1
        assert one['last_24h']['failed'] == 1
        assert one['last_24h']['estimated_cost_usd'] == .75
        assert len(one['providers']) == 1
        assert one['providers'][0]['name'] == 'Provider u1'
        assert one['providers'][0]['success_rate'] == 0
        assert one['provider_failure_categories'][0]['category'] == 'timeout'
        assert audit_history(db, 'u1')[0]['target_id'] == 'run-u1'
        assert len(audit_history(db, 'u1')) == 1
    finally:
        db.close()


def test_live_operations_routes_are_private_and_requests_have_safe_ids():
    with TestClient(app) as first, TestClient(app) as second:
        first_id = account(first)
        account(second)
        identified = first.get('/api/health/ready', headers={'X-Request-ID': 'ops-123'})
        assert identified.status_code == 200
        assert identified.headers['X-Request-ID'] == 'ops-123'
        assert identified.json()['distributed_queue'] is False
        assert first.get('/api/operations/overview').status_code == 200
        assert first.get('/api/operations/audit').json() == []
        assert second.get('/api/operations/audit').json() == []
        convo = first.post('/api/conversations', headers=HEADERS,
                           json={'title':'Run for classification'})
        assert convo.status_code == 200
        started = first.post('/api/runs', headers=HEADERS, json={
            'conversation_id':convo.json()['id'], 'prompt':'Explique este conceito de IA',
            'mode':'auto'})
        assert started.status_code == 200, started.text
        rid = started.json()['id']
        policy = first.get('/api/runs/' + rid + '/classification')
        assert policy.status_code == 200
        assert policy.json()['task_type'] == 'conversation'
        assert second.get('/api/runs/' + rid + '/classification').status_code == 404
        own_audit = first.get('/api/operations/audit').json()
        assert any(item['action']=='run_created' and item['target_id']==rid
                   for item in own_audit)
        assert second.get('/api/operations/audit').json() == []
        assert first.get('/api/operations/overview').json()['last_24h']['total'] >= 1
