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


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'hello.py').write_text("print('old')\n", encoding='utf-8')
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
