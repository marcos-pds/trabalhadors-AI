"""Workspace/tenant binding and explicit high-impact tool approval.

Does not claim Windows scripts are in a real sandbox.
"""
import asyncio
import json
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from central.database import Database, utcnow
from central.computer_access import set_policy
from central.organizations import create_organization
from central.workspace_guard import bind_run, enforce_run_scope, enforce_host_command_policy
from central.workspace_tools import agent_action, decide


@pytest.fixture
def db(tmp_path):
    store = Database(tmp_path / 'db.sqlite3')
    for name in ('a','b'):
        store.execute('INSERT INTO users VALUES(?,?,?,?)',
                      (name,name+'@example.org','hash',utcnow()))
        store.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                      ('chat-'+name,name,'Teste',None,utcnow(),utcnow()))
    yield store
    store.close()


def add_run(db,user,rid,org=None,autonomous=1):
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,'
               'created_at,updated_at,autonomous) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
               (rid,user,'chat-'+user,'Trabalhe','running','auto','[]','[]',
                utcnow(),utcnow(),autonomous))
    db.execute('INSERT INTO steps(id,run_id,kind,name,deps,status,created_at,updated_at) '
               'VALUES(?,?,?,?,?,?,?,?)',
               ('step-'+rid,rid,'agent','Programador','[]','running',utcnow(),utcnow()))
    if org:
        db.execute('INSERT INTO organization_runs(run_id,organization_id) VALUES(?,?)',
                   (rid,org))


def test_bind_scopes_cross_tenant_and_refuses_changed_folder(db,tmp_path):
    project = tmp_path/'project'
    project.mkdir()
    inner = project/'frontend'
    inner.mkdir()
    sibling = tmp_path/'another-project'
    sibling.mkdir()
    org1 = create_organization(db,'a','Empresa A')
    org2 = create_organization(db,'b','Empresa B')
    add_run(db,'a','run-a',org1)
    add_run(db,'b','run-b',org2)
    set_policy(db,'a','full',str(project))
    record=bind_run(db,'a','run-a',org1)
    assert record['folder']==str(project.resolve())
    assert enforce_run_scope(db,'a','run-a',write=True)==str(project.resolve())
    set_policy(db,'b','full',str(inner))
    with pytest.raises(HTTPException,match='outra organização') as ex:
        bind_run(db,'b','run-b',org2)
    assert ex.value.status_code==409
    set_policy(db,'b','full',str(sibling))
    assert bind_run(db,'b','run-b',org2)['folder']==str(sibling.resolve())
    # Immutable ownership: valid new grant cannot silently migrate an active run.
    set_policy(db,'a','full',str(sibling))
    with pytest.raises(HTTPException,match='workspace mudou'):
        enforce_run_scope(db,'a','run-a')
    with pytest.raises(HTTPException,match='original'):
        bind_run(db,'a','run-a',org1)
    set_policy(db,'a','full',str(project))
    db.execute("UPDATE runs SET status='cancelled' WHERE id='run-a'")
    with pytest.raises(HTTPException) as ex:
        enforce_run_scope(db,'a','run-a')
    assert ex.value.status_code==409


def test_team_command_requires_admin_opt_in(db,tmp_path):
    folder=tmp_path/'code'
    folder.mkdir()
    org=create_organization(db,'a','Empresa Dev')
    add_run(db,'a','work',org)
    set_policy(db,'a','full',str(folder))
    bind_run(db,'a','work',org)
    with pytest.raises(HTTPException,match='administrador') as ex:
        enforce_host_command_policy(db,'a','work')
    assert ex.value.status_code==403
    db.execute('UPDATE organizations SET host_commands_enabled=1 WHERE id=?',(org,))
    enforce_host_command_policy(db,'a','work')
    db.execute('UPDATE organizations SET host_commands_enabled=0 WHERE id=?',(org,))
    with pytest.raises(HTTPException):
        enforce_host_command_policy(db,'a','work')


def test_installation_in_full_mode_waits_for_one_time_approval(db,tmp_path,monkeypatch):
    folder=tmp_path/'repo'
    folder.mkdir()
    set_policy(db,'a','full',str(folder))
    add_run(db,'a','install',autonomous=0)
    events=[]
    executed=[]
    import central.workspace_tools as tools
    # Avoid spawning installer in test while exercising the approval flow.
    def command_preview(folder, request):
        return {'action':'command','description':'Instalar pacotes','path':''}
    monkeypatch.setattr(tools,'preview',command_preview)
    monkeypatch.setattr(tools,'execute',lambda *a: executed.append(a) or
                        {'success':True,'output':'simulated'})
    async def scenario():
        task=asyncio.create_task(agent_action(
            db,'a','install','step-install',
            {'action':'command','command':'pip_package','package':'requests'},
            lambda *args:events.append(args)))
        approval=None
        for _ in range(150):
            await asyncio.sleep(.01)
            approval=db.one(
                "SELECT id FROM workspace_action_approvals WHERE run_id=? "
                "AND status='pending'",('install',))
            if approval:
                break
        assert approval, 'No required installation approval was requested'
        assert not executed
        approved=decide(db,'a','install',approval['id'],True)
        assert approved['approved'] is True
        with pytest.raises(HTTPException):
            decide(db,'a','install',approval['id'],True)
        return await asyncio.wait_for(task,3)
    result=asyncio.run(scenario())
    assert result['success']
    assert len(executed)==1
    assert any(x[1]=='workspace_approval_required' for x in events)


def test_revoke_and_cancel_invalidates_pending_high_risk_install(db,tmp_path,monkeypatch):
    folder=tmp_path/'work'
    folder.mkdir()
    set_policy(db,'a','full',str(folder))
    add_run(db,'a','revoked',autonomous=0)
    import central.workspace_tools as tools
    monkeypatch.setattr(tools,'preview',
                        lambda *args: {'action':'command','description':'Pip install','path':''})
    pending=tools.issue_approval(db,'a','revoked','step-revoked',str(folder),
                                 {'action':'command','command':'pip_package','package':'requests'}, {})
    db.execute("UPDATE runs SET status='cancelled' WHERE id='revoked'")
    with pytest.raises(HTTPException):
        decide(db,'a','revoked',pending,True)


def test_team_host_policy_api_requires_local_admin_and_confirmation():
    from central.main import app
    HEADERS={'X-Central-Request':'1'}
    with TestClient(app) as admin,TestClient(app) as other:
        emails=[uuid.uuid4().hex+'@example.com' for _ in range(2)]
        for client,email in zip((admin,other),emails):
            res=client.post('/api/register',headers=HEADERS,
                            json={'email':email,'password':'longstrongpassword'})
            assert res.status_code==200,res.text
        org=admin.post('/api/organizations',headers=HEADERS,
                       json={'name':'Equipe Segura'}).json()['id']
        uri=f'/api/organizations/{org}/host-commands'
        assert admin.put(uri,json={'enabled':True,'confirmation':'AUTORIZO EXECUCAO LOCAL'}).status_code==403
        assert admin.put(uri,headers=HEADERS,json={
            'enabled':True,'confirmation':'nao'}).status_code==422
        assert other.put(uri,headers=HEADERS,json={
            'enabled':True,'confirmation':'AUTORIZO EXECUCAO LOCAL'}).status_code==404
        approved=admin.put(uri,headers=HEADERS,json={
            'enabled':True,'confirmation':'AUTORIZO EXECUCAO LOCAL'})
        assert approved.status_code==200,approved.text
        orgs=admin.get('/api/organizations').json()
        assert next(item for item in orgs if item['id']==org)['host_commands_enabled']==1
        denied=admin.put(uri,headers=HEADERS,json={'enabled':False})
        assert denied.status_code==200,denied.text



def test_command_streams_only_bounded_tail_even_for_megabyte_of_output(tmp_path,monkeypatch):
    import sys
    from central import workspace_tools as tools
    folder=tmp_path/'bounded'
    folder.mkdir()
    monkeypatch.setattr(tools,'command_spec',lambda *a:{
        'cwd':'','root':folder,'argv':[sys.executable,'-c',
               'import sys;sys.stdout.write("x"*1000000)'],
        'label':'bounded-output'})
    result=tools.execute(str(folder),{'action':'command','command':'python_test'},
                         run_id='logs-1')
    assert result['success'] is True, result
    assert result['output_truncated'] is True
    assert 0<len(result['output'])<=tools.MAX_OUTPUT
    assert set(result['output'])=={'x'}


def test_global_local_process_slots_fail_closed(tmp_path,monkeypatch):
    from central import workspace_tools as tools
    folder=tmp_path/'limited'
    folder.mkdir()
    monkeypatch.setattr(tools,'command_spec',lambda *a:{
        'cwd':'','root':folder,'argv':['no-spawn'],
        'label':'not-spawned'})
    assert tools._command_slots.acquire(blocking=False)
    assert tools._command_slots.acquire(blocking=False)
    try:
        outcome=tools.execute(str(folder),
            {'action':'command','command':'python_compile'},run_id='at-capacity')
        assert outcome['success'] is False
        assert 'simultâneos' in outcome['output']
    finally:
        tools._command_slots.release()
        tools._command_slots.release()
