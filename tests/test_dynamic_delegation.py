"""Real SQLite transactions for dynamic DAG delegation, not mocked agent replies."""
import json

import pytest

from central.agent_autonomy import parse_tool
from central.computer_access import set_policy
from central.database import Database, utcnow
from central.dynamic_delegation import MAX_DYNAMIC_STEPS, delegate
from central.workspace_guard import bind_run


@pytest.fixture
def setup(tmp_path):
    folder = tmp_path / 'workspace'
    folder.mkdir()
    db = Database(tmp_path / 'delegation.sqlite')
    now = utcnow()
    for user in ('u', 'foreign'):
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, user + '@example.test', 'hash', now))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                   (user, user, 'Chat', None, now, now))
    stages = [
        ('architect', 'architecture', 'running', []),
        ('coder', 'code', 'queued', ['architect']),
        ('reviewer', 'review', 'queued', ['coder']),
    ]
    for agent, role, status, deps in stages:
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
                   (agent, 'u', agent, role, 'Do work', now))
    for agent, role in [('backend', 'backend'), ('frontend', 'frontend'),
                        ('foreign-agent', 'backend')]:
        owner = 'foreign' if agent == 'foreign-agent' else 'u'
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
                   (agent, owner, agent, role, 'Do work', now))
    plan = [
        {'id': agent, 'agent_id': agent, 'name': agent, 'kind': 'agent',
         'deps': deps, 'instructions': ''}
        for agent, role, status, deps in stages]
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at,autonomous) '
               'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
               ('r', 'u', 'u', 'Crie uma aplicação web', 'running', 'team',
                '[]', json.dumps(plan), now, now, 1))
    for agent, role, status, deps in stages:
        db.execute('INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?,?)',
                   (agent, 'r', agent, 'agent', agent, json.dumps(deps), status, now, now))
    set_policy(db, 'u', 'full', str(folder))
    bind_run(db, 'u', 'r')
    yield db
    db.close()


def request(**kwargs):
    command = {'action': 'delegate_task', 'recipient_agent_id': 'backend',
               'title': 'Criar a API', 'instructions': 'Implemente a API local, com testes reais.',
               'request_id': 'api-backend-v1'}
    command.update(kwargs)
    return command


def dispatch(db, command=None, *, user='u', source='architect'):
    return delegate(db, user, 'r', source, request() if command is None else command,
                    lambda *args: None)


def test_dynamic_step_persists_and_reviewer_waits(setup):
    result = dispatch(setup)
    assert result['created'] and result['success']
    step = setup.one('SELECT * FROM steps WHERE id=?', (result['step_id'],))
    assert step['agent_id'] == 'backend' and step['status'] == 'queued'
    assert set(json.loads(step['deps'])) == {'architect', 'coder'}
    review = setup.one('SELECT deps FROM steps WHERE id=?', ('reviewer',))
    assert result['step_id'] in json.loads(review['deps'])
    plan = json.loads(setup.one('SELECT plan FROM runs WHERE id=?', ('r',))['plan'])
    assert any(item['id'] == result['step_id'] for item in plan)
    assert next(item for item in plan if item['id'] == 'reviewer')['deps'] == json.loads(review['deps'])
    message = setup.one("SELECT * FROM agent_messages WHERE run_id='r' AND message_type='task_request'")
    assert message['recipient_agent_id'] == 'backend'
    assert message['content'] == request()['instructions']
    assert setup.one("SELECT COUNT(*) n FROM events WHERE event='dynamic_step_registered'")['n'] == 1


def test_idempotent_replay_never_creates_another_step_or_message(setup):
    one = dispatch(setup)
    two = dispatch(setup)
    assert two['step_id'] == one['step_id'] and two['created'] is False
    assert setup.one("SELECT COUNT(*) n FROM dynamic_step_requests")['n'] == 1
    assert setup.one("SELECT COUNT(*) n FROM agent_messages")['n'] == 1
    with pytest.raises(ValueError, match='request_id reutilizado'):
        dispatch(setup, request(instructions='Tarefa diferente com o mesmo identificador.'))


@pytest.mark.parametrize('change', [
    {'recipient_agent_id': 'foreign-agent'},
    {'recipient_agent_id': 'architect'},
    {'recipient_agent_id': 'reviewer'},
    {'recipient_agent_id': 'missing'},
])
def test_reject_unavailable_or_forbidden_recipient(setup, change):
    with pytest.raises(ValueError):
        dispatch(setup, request(**change))
    assert setup.one('SELECT COUNT(*) n FROM dynamic_step_requests')['n'] == 0


def test_scope_and_run_status_are_enforced(setup):
    with pytest.raises(Exception):
        dispatch(setup, user='foreign')
    setup.execute("UPDATE runs SET status='cancelled' WHERE id='r'")
    with pytest.raises(Exception):
        dispatch(setup)
    assert setup.one('SELECT COUNT(*) n FROM dynamic_step_requests')['n'] == 0


def test_no_review_reordering_after_reviewer_has_started(setup):
    setup.execute("UPDATE steps SET status='running' WHERE id='reviewer'")
    with pytest.raises(ValueError, match='Revisor'):
        dispatch(setup)


def test_dynamic_task_count_is_bounded_with_no_partial_mutation(setup):
    for i in range(MAX_DYNAMIC_STEPS):
        res = dispatch(setup, request(request_id=f'api-subtask-{i:03d}'))
        assert res['created']
    with pytest.raises(ValueError, match='Limite'):
        dispatch(setup, request(request_id='too-many-steps'))
    assert setup.one('SELECT COUNT(*) n FROM dynamic_step_requests')['n'] == MAX_DYNAMIC_STEPS
    assert not setup.conn.in_transaction


def test_creation_rolls_back_if_review_dependency_update_fails(setup):
    setup.execute("""
        CREATE TRIGGER deny_review_edit BEFORE UPDATE OF deps ON steps
        WHEN NEW.id = 'reviewer'
        BEGIN SELECT RAISE(ABORT, 'review locked'); END
    """)
    with pytest.raises(Exception, match='review locked'):
        dispatch(setup)
    assert setup.one('SELECT COUNT(*) n FROM dynamic_step_requests')['n'] == 0
    assert setup.one("SELECT COUNT(*) n FROM agent_messages")['n'] == 0
    assert setup.one("SELECT COUNT(*) n FROM steps WHERE agent_id='backend'")['n'] == 0
    assert not setup.conn.in_transaction


def test_model_schema_rejects_untrusted_fields_before_execution():
    command = request()
    assert parse_tool(json.dumps(command)) == command
    for invalid in (request(request_id='x'),
                    request(organization_id='other'),
                    request(instructions='x')):
        with pytest.raises(ValueError):
            parse_tool(json.dumps(invalid))


def test_replay_after_requester_completed_preserves_scope(setup):
    first = dispatch(setup)
    setup.execute("UPDATE steps SET status='completed' WHERE id='architect'")
    assert dispatch(setup)['step_id'] == first['step_id']
    with pytest.raises(ValueError, match='request_id reutilizado'):
        dispatch(setup, request(title='Different task'))
    with pytest.raises(ValueError, match='ativo'):
        dispatch(setup, request(request_id='new-request'))
    set_policy(setup, 'u', 'blocked', '')
    with pytest.raises(Exception):
        dispatch(setup)
    assert setup.one('SELECT COUNT(*) n FROM dynamic_step_requests')['n'] == 1


@pytest.mark.parametrize('deps', ['["coder"]', '["missing"]', '{}', '[3]', 'invalid'])
def test_reject_corrupt_prerequisites_without_partial_mutation(setup, deps):
    # coder -> architect -> architect/coder is a cycle below the review root.
    setup.execute("UPDATE steps SET deps=? WHERE id='architect'", (deps,))
    before = setup.one("SELECT plan FROM runs WHERE id='r'")['plan']
    with pytest.raises(ValueError):
        dispatch(setup)
    assert setup.one('SELECT COUNT(*) n FROM steps')['n'] == 3
    assert setup.one('SELECT COUNT(*) n FROM agent_messages')['n'] == 0
    assert setup.one("SELECT plan FROM runs WHERE id='r'")['plan'] == before
    assert not setup.conn.in_transaction


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'deps', 'kind', 'agent', 'scalar'])
def test_reject_inconsistent_plan_without_partial_mutation(setup, mutation):
    plan = json.loads(setup.one("SELECT plan FROM runs WHERE id='r'")['plan'])
    if mutation == 'missing':
        plan.pop()
    elif mutation == 'duplicate':
        plan[-1] = plan[0]
    elif mutation == 'scalar':
        plan[-1] = None
    else:
        plan[-1][{'deps': 'deps', 'kind': 'kind', 'agent': 'agent_id'}[mutation]] = 'wrong'
    setup.execute("UPDATE runs SET plan=? WHERE id='r'", (json.dumps(plan),))
    with pytest.raises(ValueError, match='Plano persistido'):
        dispatch(setup)
    assert setup.one('SELECT COUNT(*) n FROM steps')['n'] == 3
    assert setup.one('SELECT COUNT(*) n FROM agent_messages')['n'] == 0
    assert not setup.conn.in_transaction


def test_independent_connections_serialize_idempotent_requests(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    # Match create_run: assign a personal organization before binding.
    now = utcnow()
    setup.execute('INSERT INTO organizations(id,name,created_by,is_personal,created_at) '
                  'VALUES(?,?,?,?,?)', ('org-u', 'Personal', 'u', 1, now))
    setup.execute('INSERT INTO organization_members VALUES(?,?,?,?)',
                  ('org-u', 'u', 'admin', now))
    setup.execute('INSERT INTO organization_runs VALUES(?,?)', ('r', 'org-u'))
    setup.execute("UPDATE run_workspace_bindings SET organization_id='org-u' WHERE run_id='r'")
    path = setup.one('PRAGMA database_list')['file']
    other = Database(path)
    barrier = Barrier(2)

    def submit(db):
        barrier.wait(timeout=5)
        return dispatch(db)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, db) for db in (setup, other)]
            results = [future.result(timeout=10) for future in futures]
        assert {result['created'] for result in results} == {True, False}
        assert len({result['step_id'] for result in results}) == 1
    finally:
        other.close()
    reopened = Database(path)
    try:
        assert dispatch(reopened)['step_id'] == results[0]['step_id']
        assert reopened.one('SELECT COUNT(*) n FROM agent_messages')['n'] == 1
        assert reopened.one("SELECT COUNT(*) n FROM events WHERE event='dynamic_step_registered'")['n'] == 1
    finally:
        reopened.close()


def test_scheduler_reloads_nested_delegation_before_review(setup):
    import asyncio
    from central.engine import RunOrchestrator

    setup.execute("UPDATE runs SET prompt='Organize tarefas' WHERE id='r'")
    setup.execute("UPDATE steps SET status='queued' WHERE id='architect'")
    engine = RunOrchestrator.__new__(RunOrchestrator)
    engine.db = setup
    engine.emit = lambda *args: None
    order = []

    async def execute(run, step):
        setup.execute("UPDATE steps SET status='running' WHERE id=?", (step['id'],))
        order.append(step['agent_id'])
        if step['agent_id'] == 'architect':
            dispatch(setup)
        elif step['agent_id'] == 'backend':
            dispatch(setup, request(recipient_agent_id='frontend', request_id='nested-frontend'),
                     source=step['id'])
        if step['agent_id'] == 'reviewer':
            assert setup.one("SELECT COUNT(*) n FROM steps WHERE status!='completed' AND id!='reviewer'")['n'] == 0
        setup.execute("UPDATE steps SET status='completed',output='done' WHERE id=?", (step['id'],))

    engine.execute_step = execute
    asyncio.run(engine.process('r'))
    assert order == ['architect', 'coder', 'backend', 'frontend', 'reviewer']
    assert setup.one("SELECT status FROM runs WHERE id='r'")['status'] == 'completed'
    assert setup.one('SELECT MAX(depth) n FROM dynamic_step_requests')['n'] == 2


def test_shared_prerequisites_are_not_mistaken_for_cycles():
    from central.dynamic_delegation import _ancestors

    steps = {name: {'deps': json.dumps(deps)} for name, deps in {
        'root': [], 'left': ['root'], 'right': ['root'],
        'join': ['left', 'right'],
    }.items()}
    assert _ancestors('join', steps) == {'root', 'left', 'right'}


def test_scope_revocation_between_precheck_and_transaction_rolls_back(setup, monkeypatch):
    from central import dynamic_delegation

    original = dynamic_delegation.enforce_run_scope
    checks = []

    def revoke_after_precheck(*args, **kwargs):
        result = original(*args, **kwargs)
        checks.append(True)
        if len(checks) == 1:
            set_policy(setup, 'u', 'blocked', '')
        return result

    monkeypatch.setattr(dynamic_delegation, 'enforce_run_scope', revoke_after_precheck)
    with pytest.raises(Exception) as error:
        dispatch(setup)
    assert error.value.status_code == 403
    assert setup.one('SELECT COUNT(*) n FROM steps')['n'] == 3
    assert setup.one('SELECT COUNT(*) n FROM agent_messages')['n'] == 0
    assert not setup.conn.in_transaction
