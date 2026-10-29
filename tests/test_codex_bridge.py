"""Real subprocess/SQLite bridge tests with a fake native protocol, NOT live model proof."""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from central import codex_bridge as bridge
from central.database import Database, utcnow
from central.providers import ProviderError


NATIVE_FIXTURE = r'''
import json, sys, time
mode, log, version = sys.argv[1:]
def send(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    with open(log, 'a', encoding='utf-8') as output:
        output.write(json.dumps(request) + '\n')
    method = request.get('method')
    if method == 'initialized':
        continue
    if method == 'initialize':
        result = {'userAgent': 'codex/' + ('wrong-version' if mode == 'version' else version)}
    elif method == 'account/read':
        result = {'account': {'type': 'apiKey' if mode == 'apikey' else 'chatgpt',
                              'email': 'changed@example.test' if mode == 'changed' else 'owner@example.test'}}
    elif method in ('thread/start', 'thread/resume'):
        result = {'thread': {'id': 'native-thread-1'}}
    elif method == 'turn/start':
        result = {'turn': {'id': 'turn-1'}}
    else:
        raise RuntimeError('Unexpected request')
    send({'id': request['id'], 'result': result})
    if method != 'turn/start':
        continue
    if mode == 'hang':
        time.sleep(60)
        continue
    for kind in ('userMessage', 'reasoning', 'plan', 'contextCompaction'):
        for event in ('item/started', 'item/completed'):
            send({'method': event, 'params': {'threadId': 'native-thread-1', 'item': {'type': kind}}})
    if mode in ('tool', 'completed_tool'):
        send({'method': 'item/started' if mode == 'tool' else 'item/completed',
              'params': {'threadId': 'native-thread-1', 'item': {'type': 'commandExecution'}}})
    send({'method': 'item/completed', 'params': {'threadId': 'native-thread-1',
          'item': {'type': 'agentMessage', 'text': json.dumps({'action_json': '{"action":"finish","message":"fixture only"}'})}}})
    send({'method': 'turn/completed', 'params': {'threadId': 'native-thread-1',
          'turn': {'id': 'turn-1', 'status': 'completed'}}})
'''


@pytest.fixture
def owned(tmp_path):
    db = Database(tmp_path / 'bridge.sqlite')
    now = utcnow()
    for owner in ('alice', 'bob'):
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (owner, owner + '@example.test', 'hash', now))
        db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) VALUES(?,?,?,?,?,?,?)',
                   (owner, owner, 'local', 'codex_cli', '', 'fixture-model', now))
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
                   (owner, owner, 'worker', 'code', 'test', now))
        db.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',
                   (owner, owner, 'test', now, now))
        db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?)', (owner, owner, owner, 'test', 'running', 'auto', '[]', '{}', now, now))
        db.execute('INSERT INTO steps(id,run_id,agent_id,name,deps,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                   (owner, owner, owner, 'test', '[]', 'running', now, now))
    context = dict(db=db, user_id='alice', run_id='alice', step_id='alice')
    provider = dict(id='alice', _structured_actions=True, _runtime_context=context)
    yield db, provider, context
    db.close()


@pytest.fixture
def native(monkeypatch, tmp_path):
    script = tmp_path / 'native_fixture.py'
    script.write_text(NATIVE_FIXTURE, encoding='utf-8')
    log = tmp_path / 'requests.jsonl'
    clients = []
    launched = threading.Event()
    original = bridge._Client
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')

    def real_client(*args, **kwargs):
        client = original(*args, **kwargs)
        client.fixture_launch_options = kwargs
        clients.append(client)
        launched.set()
        return client

    monkeypatch.setattr(bridge, '_Client', real_client)

    def configure(mode='normal'):
        monkeypatch.setattr(bridge, 'cli_arguments', lambda: [
            sys.executable, '-u', str(script), mode, str(log), bridge.CERTIFIED_VERSION])

    configure()
    yield configure, clients, launched, log
    # Assert bridge cleanup before performing defensive fixture cleanup.
    try:
        assert all(c.process.poll() is not None for c in clients)
        assert all(not c.reader.is_alive() and not c.writer.is_alive() for c in clients)
    finally:
        for client in clients:
            if client.process.poll() is None:
                client.close()


MESSAGES = [dict(role='user', content='fixture request')]


def run(owned, messages=None, cancel=None, timeout=4):
    _, provider, context = owned
    return bridge._run_turn(provider, 'fixture-model', 'Central instructions',
                            MESSAGES if messages is None else messages, context,
                            cancel or threading.Event(), timeout)


def requests(native):
    log = native[3]
    return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []


def session(db):
    return db.one("SELECT * FROM codex_step_sessions WHERE step_id='alice'")


def test_start_resume_delta_and_claims_persist(owned, native):
    db, _, _ = owned
    text = run(owned)
    assert json.loads(text) == {'action': 'finish', 'message': 'fixture only'}
    assert 'action_json' not in json.loads(text)
    first = session(db)
    assert first['state'] == 'ready' and first['lease_until'] == 0
    assert first['thread_id'] == 'native-thread-1'
    assert first['user_id'] == first['provider_id'] == first['run_id'] == first['step_id'] == 'alice'
    assert first['model'] == 'fixture-model'
    assert first['account_hash'] == bridge._digest('owner@example.test')
    assert first['system_hash'] == bridge._digest('Central instructions')
    assert first['last_input_hash'] == bridge._digest(MESSAGES[-1])
    assert first['last_output_hash'] == bridge._digest(text)
    followup = dict(role='user', content='next delta')
    assert run(owned, MESSAGES + [dict(role='assistant', content=text), followup]) == text
    second = session(db)
    assert second['lease_token'] != first['lease_token']
    assert second['last_input_hash'] == bridge._digest(followup)
    calls = requests(native)
    assert [r['method'] for r in calls].count('thread/start') == 1
    assert [r['method'] for r in calls].count('thread/resume') == 1
    turn = [r for r in calls if r['method'] == 'turn/start'][-1]
    assert json.loads(turn['params']['input'][0]['text'].split('\n', 1)[1]) == [followup]
    assert turn['params']['outputSchema'] == bridge.ACTION_ENVELOPE_SCHEMA
    for request in calls:
        if request['method'] in ('thread/start', 'thread/resume'):
            assert request['params']['sandbox'] == 'read-only'
            assert request['params']['approvalPolicy'] == 'never'
            assert request['params']['config']['mcp_servers'] == {}
        if request['method'] == 'account/read':
            assert request['params'] == {'refreshToken': False}
    reopened = Database(db.one('PRAGMA database_list')['file'])
    try:
        assert session(reopened) == second
    finally:
        reopened.close()
    for client in native[1]:
        neutral = Path(client.fixture_launch_options['cwd'])
        assert neutral.name.startswith('central-codex-neutral-')
        assert not neutral.exists()


def test_child_environment_strips_credentials(owned, native, monkeypatch):
    for name in ('OPENAI_API_KEY', 'SAMPLE_TOKEN', 'SAMPLE_SECRET', 'SAMPLE_PASSWORD',
                 'OPENAI_BASE_URL', 'OPENAI_API_BASE'):
        monkeypatch.setenv(name, 'fixture-private-value')
    monkeypatch.setenv('CENTRAL_FIXTURE_HARMLESS', 'keep-me')
    run(owned)
    env = native[1][0].fixture_launch_options['env']
    assert env['CENTRAL_FIXTURE_HARMLESS'] == 'keep-me'
    assert 'fixture-private-value' not in env.values()


@pytest.mark.parametrize('change', ['user', 'run', 'step', 'provider', 'disabled', 'inactive', 'kind'])
def test_scope_denial_before_launch(owned, native, change):
    db, provider, context = owned
    if change in ('user', 'run', 'step'):
        context[change + '_id'] = 'bob'
    elif change == 'provider':
        provider['id'] = 'bob'
    elif change == 'disabled':
        db.execute("UPDATE providers SET enabled=0 WHERE id='alice'")
    elif change == 'inactive':
        db.execute("UPDATE runs SET status='completed' WHERE id='alice'")
    else:
        db.execute("UPDATE providers SET kind='openai' WHERE id='alice'")
    with pytest.raises(ProviderError) as error:
        run(owned)
    assert error.value.category == 'permission'
    assert native[1] == []
    assert db.all('SELECT * FROM codex_step_sessions') == []


def test_server_mode_denied_before_launch(owned, native, monkeypatch):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'server')
    with pytest.raises(ProviderError) as error:
        run(owned)
    assert error.value.category == 'permission'
    assert native[1] == [] and session(owned[0]) is None


@pytest.mark.parametrize('mode,reason', [('apikey', 'chatgpt_login_required'),
    ('version', 'unsupported_cli_version'), ('tool', 'unexpected_native_tool')])
def test_native_fail_closed_and_release(owned, native, mode, reason):
    native[0](mode)
    with pytest.raises(ProviderError, match=reason):
        run(owned)
    assert session(owned[0])['state'] == 'failed'
    assert session(owned[0])['lease_until'] == 0
    if mode != 'tool':
        assert not any(r['method'].startswith('thread/') for r in requests(native))


def test_account_fingerprint_change_denied(owned, native):
    text = run(owned)
    before = session(owned[0])
    count = len(requests(native))
    native[0]('changed')
    with pytest.raises(ProviderError, match='account_changed'):
        run(owned, MESSAGES + [dict(role='assistant', content=text), dict(role='user', content='continue')])
    after = session(owned[0])
    assert after['account_hash'] == before['account_hash']
    assert after['state'] == 'failed' and after['lease_until'] == 0
    assert [r['method'] for r in requests(native)[count:]] == ['initialize', 'initialized', 'account/read']


@pytest.mark.parametrize('cancelled', [False, True])
def test_timeout_cancel_cleanup(owned, native, cancelled):
    native[0]('hang')
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(run, owned, cancel=cancel, timeout=2)
        assert native[2].wait(2)
        if cancelled:
            cancel.set()
        with pytest.raises(ProviderError, match='cancelled' if cancelled else 'timeout'):
            task.result(timeout=6)
    row = session(owned[0])
    assert row['state'] == ('cancelled' if cancelled else 'failed')
    assert row['lease_until'] == 0
    assert native[1][0].process.poll() is not None


def test_session_lease_blocks_second_connection_before_launch(owned, native):
    db, provider, context = owned
    native[0]('hang')
    cancel = threading.Event()
    other = Database(db.one('PRAGMA database_list')['file'])
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(run, owned, cancel=cancel)
            try:
                assert native[2].wait(2)
                claimed = session(other)
                assert claimed['state'] == 'running' and claimed['lease_until'] > 0
                with pytest.raises(ProviderError) as error:
                    bridge._run_turn(provider, 'fixture-model', 'Central instructions', MESSAGES,
                                     dict(context, db=other), threading.Event(), 2)
                assert error.value.category == 'runtime_busy'
                assert len(native[1]) == 1
                assert session(other)['lease_token'] == claimed['lease_token']
            finally:
                cancel.set()
                with pytest.raises(ProviderError, match='cancelled'):
                    task.result(timeout=6)
    finally:
        other.close()


@pytest.mark.parametrize('mode', ['tool', 'completed_tool'])
def test_native_tool_rejection_independent_of_structured_output(owned, native, mode):
    # A native execution notification must abort before any final reply is decoded.
    owned[1]['_structured_actions'] = False
    native[0](mode)
    with pytest.raises(ProviderError, match='unexpected_native_tool') as error:
        run(owned)
    assert error.value.category == 'native_runtime'
    assert session(owned[0])['state'] == 'failed'


def test_revoked_provider_rechecked_before_turn(owned, native):
    db, _, context = owned

    def revoke(run_id, event, payload):
        if event == 'native_session_started':
            db.execute("UPDATE providers SET enabled=0 WHERE id='alice'")

    context['emit'] = revoke
    with pytest.raises(ProviderError) as error:
        run(owned)
    assert error.value.category == 'permission'
    assert not any(r['method'] == 'turn/start' for r in requests(native))
    assert session(db)['state'] == 'failed'
    assert session(db)['lease_until'] == 0


def test_lost_lease_does_not_return_success(owned, native):
    db, provider, context = owned
    provider['_structured_actions'] = False

    def replace_lease(run_id, event, payload):
        if event == 'native_session_started':
            db.execute("UPDATE codex_step_sessions SET lease_token='replacement-owner' WHERE step_id='alice'")

    context['emit'] = replace_lease
    # Simulate another worker taking ownership after the initial session update.
    # This checks fencing independently of action JSON validation.
    with pytest.raises(ProviderError, match='lease_lost'):
        run(owned)
    assert session(db)['lease_token'] == 'replacement-owner'


@pytest.mark.parametrize('change', ['foreign_owner', 'disabled'])
def test_unauthorized_step_agent_denied_before_launch(owned, native, change):
    if change == 'foreign_owner':
        owned[0].execute("UPDATE steps SET agent_id='bob' WHERE id='alice'")
    else:
        owned[0].execute("UPDATE agents SET enabled=0 WHERE id='alice'")
    # Direct authorization check: independent of protocol, schema, and model output.
    with pytest.raises(ProviderError) as error:
        bridge._scope(owned[0], owned[1], owned[2])
    assert error.value.category == 'permission'
    with pytest.raises(ProviderError) as launch_error:
        run(owned)
    assert launch_error.value.category == 'permission'
    assert native[1] == []
    assert session(owned[0]) is None
