"""Tool safety and autonomous repair integration tests. No real external AI."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from central.database import Database, utcnow
from central.computer_access import set_policy, policy
from central.workspace_tools import preview, execute, agent_action, decide, validation_commands
from central.agent_autonomy import autonomous_worker, parse_tool
from central.providers import ProviderError


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    # Use exact bytes: Path.write_text translates LF to CRLF on Windows.
    # Hashes represent actual on-disk bytes, not platform-translated text.
    (root / 'hello.py').write_bytes(b"print('old')\n")
    (root / 'notes.md').write_text('Projeto sob controle.', encoding='utf-8')
    db = Database(':memory:')
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('user','u@example.com','hash',utcnow()))
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
               ('convo','user','Teste',None,utcnow(),utcnow()))
    db.execute('''INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?)''',
               ('run','user','convo','Corrigir', 'running','manual','[]','[]',utcnow(),utcnow()))
    db.execute('''INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?)''',
               ('step','run',None,'agent','Programador','[]','running',utcnow(),utcnow()))
    yield db, root
    db.close()


def h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_blocked_by_default_and_scoped_write_requires_prior_read(workspace):
    db, root = workspace
    with pytest.raises(HTTPException):
        execute(str(root), {'action':'write','path':'../outside.py','content':'malicious'})
    with pytest.raises(HTTPException) as ex:
        preview(str(root), {'action':'replace','path':'hello.py','old':"print('old')",
                            'new':"print('new')",'expected_sha256':'wrong'})
    assert ex.value.status_code == 409
    with pytest.raises(HTTPException):
        execute(str(root), {'action':'write','path':'.env','content':'secret'})
    assert policy(db, 'user')['mode'] == 'blocked'


def test_replace_diff_revision_and_no_unapproved_directory_creation(workspace):
    db, root = workspace
    before = "print('old')\n"
    change = {'action':'replace','path':'hello.py','old':"print('old')",
              'new':"print('new')",'expected_sha256':h(before)}
    assert "print('new')" in preview(str(root), change)['diff']
    result = execute(str(root), change)
    assert result['sha256'] == h("print('new')\n")
    assert (root / 'hello.py').read_text() == "print('new')\n"
    with pytest.raises(HTTPException) as ex:
        execute(str(root), change)
    assert ex.value.status_code == 409
    with pytest.raises(HTTPException):
        execute(str(root), {'action':'write','path':'missing/new.py','content':'x'})
    assert not (root/'missing').exists()


def test_run_command_is_not_arbitrary_shell(workspace):
    db, root = workspace
    for shell in ('powershell', 'cmd', 'rm', 'python -c', 'curl'):
        with pytest.raises(HTTPException):
            preview(str(root), {'action':'command','command': shell})
    with pytest.raises(HTTPException):
        preview(str(root), {'action':'command','command':'npm_install',
                            'package': 'x && del everything'})
    with pytest.raises(HTTPException):
        preview(str(root), {'action':'command','command':'pip_package',
                            'package': 'requests;rm -rf /'})
    assert validation_commands(str(root))[0]['command'] == 'python_compile'


def test_full_policy_rechecks_scope_for_agent(workspace):
    db, root = workspace
    events=[]
    with pytest.raises(HTTPException):
        asyncio.run(agent_action(db,'user','run','step',
                                 {'action':'list','path':''},lambda *a:events.append(a)))
    set_policy(db,'user','full',str(root))
    result=asyncio.run(agent_action(db,'user','run','step',
                                   {'action':'read','path':'hello.py'},lambda *a:events.append(a)))
    assert result['content'] == "print('old')\n"
    assert 'sha256' in result
    assert any(e[1] == 'workspace_action_result' for e in events)


def test_browser_tool_waits_for_explicit_approval(workspace, monkeypatch):
    import central.browser_mcp as browser_mcp
    db, root = workspace
    set_policy(db, 'user', 'full', str(root))
    called = []

    async def fake_browser(db_arg, user_id, run_id, request):
        called.append((user_id, run_id, request['tool']))
        return {'success': True, 'output': 'snapshot local'}

    monkeypatch.setattr(browser_mcp, 'execute', fake_browser)

    async def scenario():
        events = []
        task = asyncio.create_task(agent_action(
            db, 'user', 'run', 'step',
            {'action': 'browser_tool', 'tool': 'take_snapshot',
             'arguments': {'pageId': 1}},
            lambda *event: events.append(event)))
        for _ in range(30):
            await asyncio.sleep(0.02)
            approval = db.one(
                "SELECT id FROM workspace_action_approvals "
                "WHERE run_id=? AND status='pending'", ('run',))
            if approval:
                break
        assert approval
        assert not called
        decide(db, 'user', 'run', approval['id'], True)
        result = await task
        assert result['success']
        assert called == [('user', 'run', 'take_snapshot')]
        assert any(event[1] == 'workspace_approval_required' for event in events)

    asyncio.run(scenario())


def test_reference_search_waits_for_approval_before_sending_query(workspace, monkeypatch):
    import central.reference_search as reference_search
    db, root = workspace
    set_policy(db, 'user', 'full', str(root))
    calls = []

    def fake_search(query):
        calls.append(query)
        return {'success': True, 'source': 'test', 'references': [],
                'output': 'test references'}

    monkeypatch.setattr(reference_search, 'search', fake_search)

    async def scenario():
        events = []
        task = asyncio.create_task(agent_action(
            db, 'user', 'run', 'step',
            {'action': 'reference_search', 'query': 'React official docs'},
            lambda *event: events.append(event)))
        for _ in range(30):
            await asyncio.sleep(0.02)
            approval = db.one(
                "SELECT id FROM workspace_action_approvals "
                "WHERE run_id=? AND status='pending'", ('run',))
            if approval:
                break
        assert approval
        assert calls == []
        decide(db, 'user', 'run', approval['id'], True)
        result = await task
        assert result['success']
        assert calls == ['React official docs']
        assert any(event[1] == 'workspace_approval_required' for event in events)
        assert any(event[1] == 'workspace_action_result' and
                   event[2]['references'] == [] for event in events)

    asyncio.run(scenario())


def test_ask_mode_requires_user_decision_and_revocation(workspace):
    db, root=workspace
    set_policy(db,'user','ask',str(root))
    events=[]
    async def scenario():
        task=asyncio.create_task(agent_action(db,'user','run','step',
                    {'action':'read','path':'hello.py'},lambda *v:events.append(v)))
        for _ in range(30):
            await asyncio.sleep(0.02)
            row=db.one("SELECT id FROM workspace_action_approvals WHERE user_id=? AND status='pending'",
                       ('user',))
            if row: break
        assert row
        assert decide(db,'user','run',row['id'],True)['approved']
        return await asyncio.wait_for(task, 3)
    done=asyncio.run(scenario())
    assert done['content'] == "print('old')\n"
    pending=db.one('SELECT status FROM workspace_action_approvals LIMIT 1')
    assert pending['status']=='approved'
    set_policy(db,'user','blocked','')
    with pytest.raises(HTTPException):
        asyncio.run(agent_action(db,'user','run','step',
            {'action':'list','path':''},lambda *a:None))


class FakeModel:
    def __init__(self, answers):
        self.answers=list(answers)
        self.seen=[]
    async def stream(self, provider, key, model, system, messages):
        self.seen.append((system,messages))
        reply=self.answers.pop(0)
        yield reply


def test_worker_patches_file_and_validates_actual_python(workspace):
    db, root = workspace
    set_policy(db,'user','full',str(root))
    before="print('old')\n"
    model=FakeModel([
        json.dumps({'action':'read','path':'hello.py'}),
        json.dumps({'action':'replace','path':'hello.py','old':"print('old')",
                    'new':"print('new')",'expected_sha256':h(before)}),
        json.dumps({'action':'finish','message':'Atualizei hello.py.'}),
    ])
    events=[]
    answer=asyncio.run(autonomous_worker(
        model,db,'user','run','step',{'kind':'openai','name':'fake'},'fake','mock',
        'Você é programador.',[{'role':'user','content':'Corrija hello.py'}],
        lambda *args:events.append(args)))
    assert (root/'hello.py').read_text() == "print('new')\n"
    assert 'python_compile' in answer
    assert any(e[1]=='workspace_validation' and e[2]['passed'] for e in events)


def test_worker_stops_after_repeating_the_same_failed_action(workspace, monkeypatch):
    db, root = workspace
    set_policy(db, 'user', 'full', str(root))
    model = FakeModel([
        json.dumps({'action': 'read', 'path': 'missing.md'}),
        json.dumps({'action': 'read', 'path': 'missing.md'}),
        json.dumps({'action': 'finish', 'message': 'Não concluído'}),
    ])
    calls = []

    async def failed_action(*args):
        calls.append(args[4])
        return {'success': False, 'error': 'Arquivo não encontrado'}

    monkeypatch.setattr('central.agent_autonomy.agent_action', failed_action)

    with pytest.raises(RuntimeError, match='falhou 2 vezes'):
        asyncio.run(autonomous_worker(
            model, db, 'user', 'run', 'step', {'kind': 'openai'}, 'key',
            'mock', '', [{'role': 'user', 'content': 'Leia o arquivo'}],
            lambda *args: None))

    from central.worker_checkpoint import checkpoint_summary
    checkpoint = checkpoint_summary(db, 'user', 'run')[0]
    assert len(calls) == 2
    assert checkpoint['state'] == 'blocked'
    assert 'Arquivo não encontrado' in checkpoint['last_result']


def test_untrusted_model_cannot_inject_raw_shell_or_unscoped_file(workspace):
    db, root=workspace
    set_policy(db,'user','full',str(root))
    model=FakeModel([
        '{"action":"command","command":"powershell","script":"Remove-Item C:/"}',
        '{"action":"read","path":"../outside.py"}',
        '{"action":"finish","message":"Sem alterações."}',
    ])
    answer=asyncio.run(autonomous_worker(
        model,db,'user','run','step',{'kind':'openai'},'key','mock','',
        [{'role':'user','content':'Teste'}],lambda *args:None))
    assert 'Validações executadas' in answer
    assert not (root.parent/'outside.py').exists()


def test_invalid_model_json_is_rejected():
    with pytest.raises(ValueError):
        parse_tool('execute bash -c rm')
    with pytest.raises(ValueError):
        parse_tool(json.dumps({'action':'delete','path':'notes.md'}))


def test_repeated_invalid_responses_trigger_provider_failover(workspace):
    db, root = workspace
    set_policy(db, 'user', 'full', str(root))
    model = FakeModel(['```json\nNo actions provided.\n```'] * 3)
    with pytest.raises(ProviderError, match='três respostas consecutivas') as error:
        asyncio.run(autonomous_worker(
            model, db, 'user', 'run', 'step', {'kind': 'ollama'},
            '', 'local', '', [{'role': 'user', 'content': 'Planeje o projeto.'}],
            lambda *args: None, planning_only=True))
    assert error.value.category == 'response'
    assert not error.value.retryable
    row = db.one('SELECT rounds_total,actions_total,last_action FROM worker_checkpoints WHERE step_id=?', ('step',))
    assert row['rounds_total'] == 3
    assert row['actions_total'] == 0
    assert row['last_action'] == 'resposta_invalida'
    assert (root / 'hello.py').read_text() == "print('old')\n"


def test_valid_action_resets_invalid_response_streak(workspace):
    db, root = workspace
    set_policy(db, 'user', 'full', str(root))
    model = FakeModel([
        'invalid', 'invalid', json.dumps({'action': 'list', 'path': ''}),
        'invalid', json.dumps({'action': 'finish', 'message': 'Plano pronto.'}),
    ])
    result = asyncio.run(autonomous_worker(
        model, db, 'user', 'run', 'step', {'kind': 'ollama'},
        '', 'local', '', [{'role': 'user', 'content': 'Planeje o projeto.'}],
        lambda *args: None, planning_only=True, validate_at_finish=False))
    assert 'Plano pronto.' in result



def test_can_create_nested_folders_but_cannot_leave_workspace(workspace):
    db, root = workspace
    made = execute(str(root), {'action': 'mkdir', 'path': 'src'})
    assert made['created'] and (root / 'src').is_dir()
    execute(str(root), {'action': 'mkdir', 'path': 'src/components'})
    created = execute(str(root), {'action': 'write', 'path': 'src/components/view.tsx',
                                  'content': 'export default function View() { return null }\n',
                                  'expected_sha256': None})
    assert created['bytes'] > 0
    with pytest.raises(HTTPException):
        execute(str(root), {'action': 'mkdir', 'path': '../../outside'})


def test_sequential_workers_share_persisted_outputs_and_validate(workspace):
    from central.engine import Engine
    db, root = workspace
    set_policy(db, 'user', 'full', str(root))
    agents = []
    for specialty, name in [('architecture', 'Arquiteto'),
                            ('code', 'Programador'), ('review', 'Revisor')]:
        agent_id = specialty
        db.execute('''INSERT INTO agents
          (id,user_id,name,specialty,instructions,avatar,created_at)
          VALUES(?,?,?,?,?,?,?)''',
          (agent_id, 'user', name, specialty, 'Trabalhe com cuidado.', '✦', utcnow()))
        agents.append(agent_id)
    db.execute('''INSERT INTO providers
        (id,user_id,name,kind,base_url,model,api_key_enc,created_at)
        VALUES(?,?,?,?,?,?,?,?)''',
        ('prov', 'user', 'Mock', 'openai', 'https://fake.test/v1',
         'test-model', 'encrypted', utcnow()))
    class FakeSecurity:
        def decrypt(self, value):
            return 'fake-key'
    # An implementation run must have real edits; a text-only coder is rejected.
    model = FakeModel([
        json.dumps({'action': 'finish', 'message': 'Planejamento definido.'}),
        json.dumps({'action': 'read', 'path': 'hello.py'}),
        json.dumps({'action': 'replace', 'path': 'hello.py',
                    'old': "print('old')", 'new': "print('new')",
                    'expected_sha256': h("print('old')\n")}),
        json.dumps({'action': 'finish', 'message': 'Implementação pronta.'}),
        json.dumps({'action': 'read', 'path': 'hello.py'}),
        json.dumps({'action': 'finish', 'message': 'Revisão concluída.'}),
    ])
    engine = Engine(db, FakeSecurity(), model)
    async def run():
        rid = engine.create_run('user', 'convo', 'Desenvolva um módulo com testes',
                                'team', autonomous=True)
        for _ in range(120):
            row = db.one('SELECT status,error FROM runs WHERE id=?', (rid,))
            if row['status'] in ('completed', 'failed'):
                return rid, row
            await asyncio.sleep(0.05)
        raise AssertionError('Execução não concluiu.')
    rid, result = asyncio.run(run())
    assert result['status'] == 'completed', result.get('error')
    steps = db.all('SELECT * FROM steps WHERE run_id=? ORDER BY rowid', (rid,))
    assert len(steps) == 3
    assert json.loads(steps[1]['deps']) == [steps[0]['id']]
    assert json.loads(steps[2]['deps']) == [steps[1]['id']]
    assert all(step['status'] == 'completed' for step in steps)
    assert 'Planejamento definido.' in model.seen[1][1][-1]['content']
    assert 'Implementação pronta.' in model.seen[4][1][-1]['content']
    assert (root / 'hello.py').read_text() == "print('new')\n"
    events = db.all("SELECT payload FROM events WHERE run_id=? AND event='workspace_validation'", (rid,))
    assert len(events) == 2
    assert all(json.loads(event['payload'])['passed'] for event in events)


def test_windows_crlf_uses_raw_file_checksum_and_preserves_existing_line_endings(workspace):
    """The agent must read the real bytes and apply a patch without changing CRLF."""
    db, root = workspace
    original = b"print('old')\r\nprint('keep')\r\n"
    path = root / 'hello.py'
    path.write_bytes(original)
    read = execute(str(root), {'action': 'read', 'path': 'hello.py'})
    assert read['content'] == original.decode('utf-8')
    assert read['sha256'] == hashlib.sha256(original).hexdigest()
    request = {'action': 'replace', 'path': 'hello.py',
               'old': "print('old')", 'new': "print('new')",
               'expected_sha256': read['sha256']}
    result = execute(str(root), request)
    expected = b"print('new')\r\nprint('keep')\r\n"
    assert path.read_bytes() == expected
    assert result['sha256'] == hashlib.sha256(expected).hexdigest()
    with pytest.raises(HTTPException) as error:
        execute(str(root), request)
    assert error.value.status_code == 409


def test_programming_agent_cannot_finish_from_generic_prose_without_edits(workspace):
    db, root = workspace
    set_policy(db, 'user', 'full', str(root))
    model = FakeModel([json.dumps({'action': 'finish', 'message': 'Está pronto.'})
                       for _ in range(2)])
    with pytest.raises(ProviderError, match='repetiu a finalização') as error:
        asyncio.run(autonomous_worker(
            model, db, 'user', 'run', 'step', {'kind': 'openai'},
            'key', 'mock', '', [{'role':'user','content':'Desenvolva o site.'}],
            lambda *args: None, require_code_changes=True))
    assert error.value.category == 'response'
    assert not error.value.retryable
    assert (root / 'hello.py').read_text() == "print('old')\n"
    from central.worker_checkpoint import checkpoint_summary
    checkpoint = checkpoint_summary(db, 'user', 'run')[0]
    assert checkpoint['rounds_total'] == 2
    assert checkpoint['last_action'] == 'finish_sem_alteracoes'
    assert 'repetiu a finalização' in checkpoint['last_result']
