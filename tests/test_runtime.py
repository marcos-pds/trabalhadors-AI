"""Safe project preview: user consent, ownership, fixed argv, no subprocess execution in CI."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_workspace import setup, prepare, HEADERS
from test_workspace import register
from central.main import app, ENGINE, RUNTIME


class DummyProcess:
    def __init__(self,argv,cwd):
        self.argv=argv
        self.cwd=cwd
        self.exit_code=None
        self.terminated=False
    def poll(self):return self.exit_code
    def terminate(self):
        self.terminated=True
        self.exit_code=0
    def wait(self,timeout=None):return self.exit_code
    def kill(self):
        self.terminated=True
        self.exit_code=-9


def conversation(c,pid):
    response=c.post('/api/conversations',json={'title':'Projeto','project_id':pid},headers=HEADERS)
    assert response.status_code==200,response.text
    return response.json()['id']


def configured(c,tmp_path):
    project=setup(c,tmp_path)
    prepare(c,project)
    RUNTIME.workspaces=ENGINE.workspaces
    cid=conversation(c,project)
    root=ENGINE.workspaces._folder(c.get('/api/me').json()['id'],project)
    front=root/'frontend'
    back=root/'backend'
    (front/'node_modules/vite/bin').mkdir(parents=True)
    (back/'.venv'/('Scripts' if __import__('os').name=='nt' else 'bin')).mkdir(parents=True)
    (front/'package.json').write_text('{"name":"teste","scripts":{"dev":"echo NOT_RUN"}}')
    (front/'node_modules/vite/bin/vite.js').write_text('// local Vite executable')
    (back/'main.py').write_text('from fastapi import FastAPI\napp=FastAPI()\n')
    python=back/'.venv'/('Scripts/python.exe' if __import__('os').name=='nt' else 'bin/python')
    python.write_bytes(b'python fixture executable')
    return project,cid,root


def test_start_requires_explicit_per_chat_permission_and_fixed_commands(tmp_path,monkeypatch):
    from central import runtime as module
    launched=[]
    def fake_popen(argv,**kwargs):
        assert kwargs['shell'] is False
        assert kwargs['cwd']
        assert kwargs['stdout'] is module.subprocess.PIPE
        assert kwargs['stderr'] is module.subprocess.STDOUT
        proc=DummyProcess(argv,kwargs['cwd'])
        launched.append(proc)
        return proc
    monkeypatch.setattr(module.subprocess,'Popen',fake_popen)
    monkeypatch.setattr(module.shutil,'which',lambda name:'/usr/bin/node')
    monkeypatch.setattr(RUNTIME,'_available',lambda port:True)
    monkeypatch.setattr(RUNTIME,'_probe',lambda :True)
    with TestClient(app) as c:
        project,cid,root=configured(c,tmp_path)
        status=c.get(f'/api/conversations/{cid}/runtime')
        assert status.status_code==200 and not status.json()['running']
        assert status.json()['frontend_url'] is None
        assert c.post(f'/api/conversations/{cid}/runtime/start',headers=HEADERS).status_code==403
        assert c.post(f'/api/conversations/{cid}/runtime/access',json={'enabled':True}).status_code==403
        granted=c.post(f'/api/conversations/{cid}/runtime/access',
                       json={'enabled':True},headers=HEADERS)
        assert granted.status_code==200 and granted.json()['enabled']
        started=c.post(f'/api/conversations/{cid}/runtime/start',headers=HEADERS)
        assert started.status_code==200,started.text
        assert started.json()['running']
        assert started.json()['frontend_url']=='http://127.0.0.1:5173/'
        assert len(launched)==2
        assert 'backend' in launched[0].cwd
        assert launched[0].argv[-4:]==['--host','127.0.0.1','--port','8000']
        assert launched[1].argv[-5:]==['--host','127.0.0.1','--port','5173','--strictPort']
        assert 'npm' not in ' '.join(launched[1].argv)
        assert 'NOT_RUN' not in ' '.join(launched[1].argv)
        assert c.post(f'/api/conversations/{cid}/runtime/start',headers=HEADERS).status_code==200
        assert len(launched)==2
        revoked=c.post(f'/api/conversations/{cid}/runtime/access',
                       json={'enabled':False},headers=HEADERS)
        assert revoked.status_code==200
        assert not revoked.json()['enabled']
        assert all(p.terminated for p in launched)
        assert c.get(f'/api/conversations/{cid}/runtime').json()['running'] is False


def test_preview_isolated_from_other_users_and_conversations(tmp_path,monkeypatch):
    from test_workspace import register
    with TestClient(app) as a, TestClient(app) as b:
        project,cid,root=configured(a,tmp_path)
        register(b)
        for endpoint in ('runtime','runtime/access','runtime/start','runtime/stop'):
            path=f'/api/conversations/{cid}/{endpoint}'
            result=b.get(path) if endpoint=='runtime' else b.post(
                path,headers=HEADERS,json={'enabled':True} if 'access' in path else None)
            assert result.status_code==404,(path,result.text)
        assert a.post(f'/api/conversations/{cid}/runtime/start',
                      headers=HEADERS).status_code==403
        second=conversation(a,project)
        assert a.post(f'/api/conversations/{cid}/runtime/access',
                      headers=HEADERS,json={'enabled':True}).status_code==200
        assert a.post(f'/api/conversations/{second}/runtime/start',headers=HEADERS).status_code==403
        assert not a.get(f'/api/conversations/{second}/runtime').json()['authorized']


def test_missing_dependencies_never_execute_or_leak_ports(tmp_path,monkeypatch):
    from central import runtime as module
    def forbidden(*args,**kwargs):raise AssertionError('should not spawn')
    monkeypatch.setattr(module.subprocess,'Popen',forbidden)
    monkeypatch.setattr(module.shutil,'which',lambda _: '/usr/bin/node')
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        RUNTIME.workspaces=ENGINE.workspaces
        cid=conversation(c,project)
        (folder/'frontend').mkdir()
        (folder/'backend').mkdir()
        (folder/'frontend/package.json').write_text('{"name":"no-deps"}')
        (folder/'backend/main.py').write_text('app=None')
        assert c.post(f'/api/conversations/{cid}/runtime/access',
                      json={'enabled':True},headers=HEADERS).status_code==200
        start=c.post(f'/api/conversations/{cid}/runtime/start',headers=HEADERS)
        assert start.status_code==422,start.text
        assert 'node_modules' in start.json()['detail'] or 'Diretório' in start.json()['detail']
        assert RUNTIME.sessions=={}


def test_vite_junction_or_symlink_rejected_before_spawn(tmp_path,monkeypatch):
    from central import runtime as module
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k:
                        pytest.fail('Cannot spawn when vite points outside'))
    monkeypatch.setattr(module.shutil,'which',lambda name:'/usr/bin/node')
    with TestClient(app) as c:
        project,cid,root=configured(c,tmp_path)
        outside=tmp_path/'outside.js';outside.write_text('unsafe')
        vite=root/'frontend/node_modules/vite/bin/vite.js';vite.unlink()
        try:vite.symlink_to(outside)
        except (OSError,NotImplementedError):pytest.skip('Symlinks unavailable')
        c.post(f'/api/conversations/{cid}/runtime/access',
               json={'enabled':True},headers=HEADERS)
        r=c.post(f'/api/conversations/{cid}/runtime/start',headers=HEADERS)
        assert r.status_code==403
        assert outside.read_text()=='unsafe'


def test_port_conflicts_no_partial_launch(tmp_path,monkeypatch):
    from central import runtime as module
    monkeypatch.setattr(module.shutil,'which',lambda name:'/usr/bin/node')
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k:
                        pytest.fail('Port conflict must block spawn'))
    monkeypatch.setattr(RUNTIME,'_available',lambda port:False if port==5173 else True)
    with TestClient(app) as c:
        project,cid,root=configured(c,tmp_path)
        c.post(f'/api/conversations/{cid}/runtime/access',json={'enabled':True},headers=HEADERS)
        r=c.post(f'/api/conversations/{cid}/runtime/start',headers=HEADERS)
        assert r.status_code==409
        assert '5173' in r.json()['detail']


def test_draft_chat_project_switch_revokes_runtime_consent(tmp_path):
    with TestClient(app) as c:
        project,cid,root=configured(c,tmp_path)
        c.post(f'/api/conversations/{cid}/runtime/access',json={'enabled':True},headers=HEADERS)
        other=c.post('/api/projects',json={'name':'Outro','description':''},headers=HEADERS).json()['id']
        switch=c.post(f'/api/conversations/{cid}/project',
                      json={'project_id':other},headers=HEADERS)
        assert switch.status_code==200,switch.text
        current=c.get(f'/api/conversations/{cid}/runtime')
        assert current.status_code==200
        assert current.json()['authorized'] is False


def test_permission_alone_never_installs_packages_or_starts_ai_worker(tmp_path):
    with TestClient(app) as c:
        project,cid,root=configured(c,tmp_path)
        assert c.post(f'/api/conversations/{cid}/runtime/access',
                      json={'enabled':True},headers=HEADERS).status_code==200
        assert c.get(f'/api/conversations/{cid}/runtime').json()['running'] is False
        assert not ENGINE.db.all('SELECT * FROM runs WHERE conversation_id=?',(cid,))
        assert not ENGINE.db.all('SELECT * FROM architect_package_installs WHERE project_id=?',(project,))


def test_early_fastapi_exit_reports_process_and_logs_and_blocks_preview(tmp_path,monkeypatch):
    from central import runtime as module
    import io
    launched=[]
    class FailFast(DummyProcess):
        def __init__(self,argv,cwd):
            super().__init__(argv,cwd)
            self.stdout=io.BytesIO(b'ERROR: Error loading ASGI app. Could not import module main.\n')
            if '-m' in argv and 'uvicorn' in argv:
                self.exit_code=1
    def fake_popen(argv,**kwargs):
        p=FailFast(argv,kwargs['cwd']);launched.append(p);return p
    monkeypatch.setattr(module.subprocess,'Popen',fake_popen)
    monkeypatch.setattr(module.shutil,'which',lambda name:'/usr/bin/node')
    monkeypatch.setattr(RUNTIME,'_available',lambda port:True)
    monkeypatch.setattr(RUNTIME,'_probe',lambda:False)
    with TestClient(app) as c:
        project,cid,root=configured(c,tmp_path)
        c.post(f'/api/conversations/{cid}/runtime/access',json={'enabled':True},headers=HEADERS)
        fail=c.post(f'/api/conversations/{cid}/runtime/start',headers=HEADERS)
        assert fail.status_code==422,fail.text
        assert 'backend (código 1)' in fail.json()['detail']
        status=c.get(f'/api/conversations/{cid}/runtime').json()
        assert not status['running']
        assert status['frontend_url'] is None
        assert 'backend' in status['last_error']
        assert 'Error loading ASGI' in fail.json()['detail']
        assert RUNTIME.sessions=={}


def test_live_process_without_reachable_http_is_not_reported_as_started(tmp_path,monkeypatch):
    from central import runtime as module
    launched=[]
    def fake_popen(argv,**kwargs):
        proc=DummyProcess(argv,kwargs['cwd']);launched.append(proc);return proc
    monkeypatch.setattr(module.subprocess,'Popen',fake_popen)
    monkeypatch.setattr(module.shutil,'which',lambda name:'/usr/bin/node')
    monkeypatch.setattr(RUNTIME,'_available',lambda port:True)
    monkeypatch.setattr(RUNTIME,'_probe',lambda:False)
    # Avoid eight real seconds during CI.
    clock=[0.0]
    def fake_monotonic():
        clock[0]+=1.5
        return clock[0]
    monkeypatch.setattr(module.time,'monotonic',fake_monotonic)
    monkeypatch.setattr(module.time,'sleep',lambda seconds:None)
    with TestClient(app) as c:
        project,cid,root=configured(c,tmp_path)
        c.post(f'/api/conversations/{cid}/runtime/access',json={'enabled':True},headers=HEADERS)
        result=c.post(f'/api/conversations/{cid}/runtime/start',headers=HEADERS)
        assert result.status_code==422,result.text
        assert 'não ficaram prontos' in result.json()['detail']
        assert all(p.terminated for p in launched)
        status=c.get(f'/api/conversations/{cid}/runtime').json()
        assert not status['running']
        assert '8 segundos' in status['last_error']
