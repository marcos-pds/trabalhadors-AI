"""Docker sandbox config, no host fallback, scoped paths and lifecycle tests.

These tests do not require Docker on the CI runner: Docker's process boundary
must also be assessed manually before public / multitenant deployment.
"""
import io
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from central import sandbox_executor as sb
from central import workspace_tools as tools


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / 'isolated'
    folder.mkdir()
    (folder / 'package.json').write_text(
        '{"scripts":{"build":"vite build","test":"vitest run"}}',
        encoding='utf-8')
    (folder / 'hello.py').write_text('print(1)',encoding='utf-8')
    return folder


def mock_docker(monkeypatch):
    monkeypatch.setattr(sb.shutil,'which',
                        lambda name: '/fake/docker' if name in ('docker','docker.exe') else None)


def test_docker_is_opt_in_and_invalid_backend_fails_closed(monkeypatch):
    monkeypatch.delenv('CENTRAL_COMMAND_RUNNER',raising=False)
    assert sb.backend() == 'host'
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
    assert sb.backend() == 'docker'
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','unknown')
    with pytest.raises(RuntimeError,match='host ou docker'):
        sb.backend()


def test_docker_args_block_network_and_host_privileges(monkeypatch,project):
    mock_docker(monkeypatch)
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
    req = {'action':'command','command':'npm_build'}
    spec = tools.command_spec(str(project),req)
    args,name = sb.sandbox_argv(spec,req)
    assert args[0] == '/fake/docker'
    assert name.startswith('central-job-') and len(name)==44
    for pair in (['--network','none'],['--read-only','--cap-drop','ALL'],
                 ['--security-opt','no-new-privileges'],['--memory','512m'],
                 ['--cpus','1'],['--pids-limit','128']):
        assert any(args[i:i+len(pair)] == pair
                   for i in range(len(args)-len(pair)+1))
    assert '--privileged' not in args and '--device' not in args
    assert '--publish' not in args and '/var/run/docker.sock' not in ' '.join(args)
    assert '--mount' in args
    mnt=args[args.index('--mount')+1]
    assert mnt == 'type=bind,source='+str(project.resolve())+',target=/workspace'
    assert args[-3:] == ['npm','run','build']
    assert args.count('--mount') == 1


def test_nested_project_only_mounts_selected_project(monkeypatch,tmp_path):
    mock_docker(monkeypatch)
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
    outer=tmp_path/'authorized'
    nested=outer/'apps'/'web'
    nested.mkdir(parents=True)
    (nested/'package.json').write_text('{"scripts":{"build":"vite build"}}',encoding='utf-8')
    spec=tools.command_spec(str(outer),{
        'action':'command','command':'npm_build','cwd':'apps/web'})
    args,_=sb.sandbox_argv(spec,{'action':'command','command':'npm_build','cwd':'apps/web'})
    mount=args[args.index('--mount')+1]
    assert 'source='+str(nested.resolve())+',target=' in mount
    assert 'source='+str(outer.resolve())+',target=' not in mount


def test_unsupported_installations_are_denied_in_docker_mode(monkeypatch,project):
    mock_docker(monkeypatch)
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
    for code in ('npm_ci','npm_install','pip_package','pip_requirements','venv_create'):
        with pytest.raises(HTTPException,match='Instalação'):
            tools.command_spec(str(project),{'action':'command','command':code})
    with pytest.raises(HTTPException,match='não compatível'):
        sb.sandbox_argv({'root':project},{'command':'powershell'})


def test_missing_docker_never_falls_back_to_host(monkeypatch,project):
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
    monkeypatch.setattr(sb.shutil,'which',lambda _:None)
    with pytest.raises(HTTPException) as ex:
        tools.execute(str(project),{'action':'command','command':'python_compile'},
                      run_id='missing-docker')
    assert ex.value.status_code == 503


def test_sandbox_run_uses_bounded_output_and_command_lifecycle(monkeypatch,project):
    mock_docker(monkeypatch)
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
    launched = []
    class FakeProcess:
        def __init__(self,*argv,**kwargs):
            self.args=argv[0]
            self.stdout=io.BytesIO(b'build passed')
            self.returncode=0
            launched.append(self)
        def wait(self,timeout=None): return self.returncode
        def poll(self): return self.returncode
    monkeypatch.setattr(tools.subprocess,'Popen',FakeProcess)
    result=tools.execute(str(project),
                         {'action':'command','command':'npm_build'},
                         run_id='sandbox-test')
    assert result['success'] is True, result
    assert result['output'] == 'build passed'
    assert launched and launched[0].args[0]=='/fake/docker'
    assert launched[0].args[1]=='run'
    assert 'sandbox-test' not in tools._active_containers
    assert 'sandbox-test' not in tools._active_commands


def test_cancel_removes_only_the_tracked_docker_container(monkeypatch):
    names=[]
    monkeypatch.setattr(tools,'force_remove',lambda name:names.append(name))
    run='cancel-docker-test'
    identifier='central-job-'+'f'*32
    with tools._process_lock:
        tools._active_containers[run]=identifier
    try:
        tools.stop_run_commands(run)
        assert names==[identifier]
    finally:
        with tools._process_lock:
            tools._active_containers.pop(run,None)
        tools.reset_run_commands(run)


def test_mount_path_cannot_inject_extra_docker_options(monkeypatch,tmp_path):
    mock_docker(monkeypatch)
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
    dangerous=tmp_path/'app,readonly=false'
    dangerous.mkdir()
    with pytest.raises(HTTPException,match='mount'):
        sb.sandbox_argv({'root':dangerous},{'command':'git_status'})


def test_docker_mode_disables_host_preview(monkeypatch):
    import uuid
    from fastapi.testclient import TestClient
    from central.main import app
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
    with TestClient(app) as client:
        email=uuid.uuid4().hex+'@example.org'
        r=client.post('/api/register',
                      headers={'X-Central-Request':'1'},
                      json={'email':email,'password':'teststrongpassword'})
        assert r.status_code==200,r.text
        res=client.post('/api/preview/start',
                        headers={'X-Central-Request':'1'},
                        json={'cwd':''})
        assert res.status_code==409
        assert 'host' in res.json()['detail']
        ready=client.get('/api/health/ready')
        assert ready.status_code==200
        assert ready.json()['command_executor']['backend']=='docker'
        ops=client.get('/api/operations/overview')
        assert ops.json()['command_executor']['backend']=='docker'



def test_run_binding_blocks_backend_mismatch_between_api_and_worker(tmp_path,monkeypatch):
    from central.database import Database,utcnow
    from central.computer_access import set_policy
    from central.workspace_guard import bind_run,enforce_run_scope
    db=Database(tmp_path/'scoped.db')
    folder=tmp_path/'workspace'
    folder.mkdir()
    try:
        db.execute('INSERT INTO users VALUES(?,?,?,?)',
                   ('user','user@example.org','hash',utcnow()))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                   ('chat','user','Teste',None,utcnow(),utcnow()))
        db.execute(
            'INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,'
            'agent_ids,plan,created_at,updated_at,autonomous) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('run','user','chat','Trabalhar','running','auto','[]','[]',
             utcnow(),utcnow(),1))
        set_policy(db,'user','full',str(folder))
        monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
        assert bind_run(db,'user','run')['command_runner']=='docker'
        assert enforce_run_scope(db,'user','run')==str(folder.resolve())
        monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','host')
        with pytest.raises(HTTPException,match='executor diferente'):
            enforce_run_scope(db,'user','run')
        monkeypatch.setenv('CENTRAL_COMMAND_RUNNER','docker')
        enforce_run_scope(db,'user','run')
    finally:
        db.close()
