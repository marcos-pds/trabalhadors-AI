import asyncio
import json
import os

import pytest
from fastapi import HTTPException

from central.workspace_tools import resolve_command_context,agent_action
from central.computer_access import set_policy
from central.workspace_guard import bind_run
from test_agent_autonomy import workspace


def test_missing_python_cwd_uses_unique_project_but_never_changes_explicit_root(tmp_path):
    (tmp_path/'.venv').mkdir()
    backend=tmp_path/'backend';backend.mkdir();(backend/'requirements.txt').write_text('fastapi')
    request={'action':'command','command':'pip_requirements'}
    assert resolve_command_context(str(tmp_path),request)['cwd']=='backend'
    assert 'cwd' not in request
    explicit=dict(request,cwd='')
    assert resolve_command_context(str(tmp_path),explicit) is explicit
    (tmp_path/'main.py').write_text('root project')
    assert resolve_command_context(str(tmp_path),request) is request


def test_ambiguous_projects_require_choice_and_npm_is_not_reinterpreted(tmp_path):
    for folder in ('backend','worker'):
        path=tmp_path/folder;path.mkdir();(path/'requirements.txt').write_text('fastapi')
    with pytest.raises(HTTPException) as error:
        resolve_command_context(str(tmp_path),{'action':'command','command':'python_test'})
    assert error.value.status_code==422 and 'cwd' in error.value.detail
    request={'action':'command','command':'npm_build'}
    assert resolve_command_context(str(tmp_path),request) is request


def test_effective_cwd_is_recorded_before_approval_and_reused_for_execution(workspace,monkeypatch):
    db,root=workspace
    (root/'hello.py').unlink()  # This fixture now represents a JS root with one Python service.
    backend=root/'backend';backend.mkdir();(backend/'requirements.txt').write_text('fastapi')
    binary=backend/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture')
    set_policy(db,'user','full',str(root));bind_run(db,'user','run')
    calls=[]
    def emit(rid,event,payload):
        if event!='workspace_approval_required':return
        from central.approval_engine import decide
        stored=json.loads(db.one('SELECT request_json FROM workspace_action_approvals WHERE id=?',(payload['approval_id'],))['request_json'])
        assert stored['cwd']=='backend'
        decide(db,'user','run',payload['approval_id'],True)
    def execute(folder,request,*args):
        calls.append(request)
        return {'success':True,'exit_code':0,'output':'fixture'}
    monkeypatch.setattr('central.workspace_tools.execute',execute)
    result=asyncio.run(agent_action(db,'user','run','step',{'action':'command','command':'pip_requirements'},emit))
    assert result['success'] is True and calls[0]['cwd']=='backend'


def test_reviewed_install_recipe_changes_with_file_or_step(workspace):
    from examples.validate_api_tasklab import pip_recipe
    _,root=workspace
    (root/'requirements.txt').write_text('fastapi')
    request={'action':'command','command':'pip_requirements','cwd':''}
    first=pip_recipe(str(root),'step',request)
    assert first==pip_recipe(str(root),'step',request)
    assert first!=pip_recipe(str(root),'another',request)
    (root/'requirements.txt').write_text('fastapi\nuvicorn')
    assert first!=pip_recipe(str(root),'step',request)
    assert pip_recipe(str(root),'step',{'action':'command','command':'npm_install'}) is None
