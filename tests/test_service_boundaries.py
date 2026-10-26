from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from central.database import Database, utcnow
from central.agent_registry import AgentRegistry
from central.engine import Engine, RunOrchestrator
from central.workspace_executor import WorkspaceExecutor
from central.security import Security
from test_memory import user, convo


def test_orchestrator_accepts_explicit_server_side_dependencies(tmp_path):
    db = Database(':memory:')
    dependencies = [object(), SimpleNamespace(health=object()), object(), object()]
    workspace, providers, registry, queue = dependencies
    engine = RunOrchestrator(db, Security(db, tmp_path), workspace_executor=workspace,
                             provider_manager=providers, agent_registry=registry, queue=queue)
    assert Engine is RunOrchestrator
    assert engine.workspace is workspace and engine.providers is providers
    assert engine.registry is registry and engine.queue is queue
    db.close()


def test_registry_lookup_and_selection_remain_owner_scoped():
    db = Database(':memory:'); user(db, 'alice'); user(db, 'bob')
    db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
               ('alice-agent', 'alice', 'Custom', 'code', 'instructions', utcnow()))
    registry = AgentRegistry(db)
    assert registry.get('bob', 'alice-agent') is None
    assert registry.enabled('bob') == []
    assert registry.select(registry.enabled('alice'), 'code')[0]['id'] == 'alice-agent'
    db.close()


def test_injected_runner_is_not_called_before_workspace_authorization():
    db = Database(':memory:'); user(db, 'alice'); convo(db, 'alice', 'chat')
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) '
               'VALUES(?,?,?,?,?,?,?,?,?,?)',
               ('run', 'alice', 'chat', 'test', 'running', 'auto', '[]', '[]', utcnow(), utcnow()))
    invoked = []
    service = WorkspaceExecutor(db, runner=lambda *args: invoked.append(args))
    coroutine = service.action(db, 'alice', 'run', 'step', {'action': 'list', 'path': ''}, lambda *_: None)
    try:
        with pytest.raises(HTTPException):
            coroutine.send(None)
    finally:
        coroutine.close()
    assert invoked == []
    db.close()


def test_workspace_service_rejects_accidental_cross_database_use():
    first, second = Database(':memory:'), Database(':memory:')
    service = WorkspaceExecutor(first)
    coroutine = service.action(second, 'user', 'run', 'step', {'action': 'list'}, lambda *_: None)
    try:
        with pytest.raises(ValueError, match='another database'):
            coroutine.send(None)
    finally:
        coroutine.close()
        first.close(); second.close()


def test_concurrent_approval_decisions_have_only_one_winner(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from central import approval_engine as approvals
    db = Database(':memory:'); user(db, 'alice'); convo(db, 'alice', 'chat')
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) '
               'VALUES(?,?,?,?,?,?,?,?,?,?)',
               ('run', 'alice', 'chat', 'test', 'running', 'auto', '[]', '[]', utcnow(), utcnow()))
    db.execute('INSERT INTO steps(id,run_id,name,deps,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
               ('step', 'run', 'Step', '[]', 'running', utcnow(), utcnow()))
    token = approvals.issue_approval(db, 'alice', 'run', 'step', 'folder', {'action': 'list'}, {})
    monkeypatch.setattr(approvals, 'policy', lambda *_: {'mode': 'ask', 'folder': 'folder'})
    monkeypatch.setattr(approvals, 'enforce_run_scope', lambda *args, **kwargs: 'folder')
    original = db.execute
    barrier = threading.Barrier(2)
    def execute(query, args=()):
        if query.startswith('UPDATE workspace_action_approvals'):
            barrier.wait(timeout=3)
        return original(query, args)
    monkeypatch.setattr(db, 'execute', execute)
    def decide(value):
        try:
            approvals.decide(db, 'alice', 'run', token, value)
            return 'accepted'
        except HTTPException as exc:
            assert exc.status_code == 409
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(decide, [True, False])) == ['accepted', 'conflict']
    db.close()


def test_replayed_workspace_action_reuses_only_its_pending_approval():
    from central.approval_engine import issue_approval
    db = Database(':memory:'); user(db, 'alice'); convo(db, 'alice', 'chat')
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) '
               'VALUES(?,?,?,?,?,?,?,?,?,?)',
               ('run', 'alice', 'chat', 'test', 'running', 'auto', '[]', '[]', utcnow(), utcnow()))
    db.execute('INSERT INTO steps(id,run_id,name,deps,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
               ('step', 'run', 'Step', '[]', 'running', utcnow(), utcnow()))
    request = {'action': 'command', 'command': 'npm install --ignore-scripts package'}
    first = issue_approval(db, 'alice', 'run', 'step', 'folder', request, {})
    replay = issue_approval(
        db, 'alice', 'run', 'step', 'folder',
        {'command': 'npm install --ignore-scripts package', 'action': 'command'}, {})
    assert replay == first
    assert db.one('SELECT COUNT(*) AS count FROM workspace_action_approvals')['count'] == 1

    original = db.one('SELECT * FROM workspace_action_approvals WHERE id=?', (first,))
    db.execute('''INSERT INTO workspace_action_approvals
        (id,user_id,run_id,step_id,folder,request_json,status,expires_at,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)''',
        ('stale-copy', 'alice', 'run', 'step', 'folder', original['request_json'],
         'pending', original['expires_at'], '9999-01-01T00:00:00+00:00'))
    current = issue_approval(db, 'alice', 'run', 'step', 'folder', request, {})
    assert current == 'stale-copy'
    assert db.one('SELECT status FROM workspace_action_approvals WHERE id=?',
                  (first,))['status'] == 'denied'
    assert db.one("SELECT COUNT(*) AS count FROM workspace_action_approvals WHERE status='pending'")['count'] == 1

    db.execute("UPDATE workspace_action_approvals SET status='denied' WHERE id=?", (current,))
    next_request = issue_approval(db, 'alice', 'run', 'step', 'folder', request, {})
    assert next_request != current
    db.close()
