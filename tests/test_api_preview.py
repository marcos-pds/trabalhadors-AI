"""Owned API server lifecycle; fake transport/processes, real path validation."""
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest
from fastapi import HTTPException

from central import api_preview as api


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    root=tmp_path/'repo';root.mkdir()
    backend=root/'backend';backend.mkdir()
    (backend/'main.py').write_text('app = None')
    executable=backend/'.venv'/('Scripts/python.exe' if api.os.name=='nt' else 'bin/python')
    executable.parent.mkdir(parents=True);executable.write_bytes(b'fixture')
    procs=[]
    class Process:
        code=None
        def poll(self):return self.code
    def spawn(argv,**kwargs):
        p=Process();p.argv=argv;p.kwargs=kwargs;procs.append(p);return p
    class Logs:
        def __init__(self,p):pass
        def recent(self):return 'fixture diagnostic'
        def close(self):pass
    class Timer:
        def __init__(self,*args,**kwargs):pass
        def start(self):pass
        def cancel(self):pass
    class Client:
        def __init__(self,**kwargs):assert kwargs['trust_env'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):return SimpleNamespace(status_code=200,json=lambda:{'ok':True})
    monkeypatch.setattr(api,'backend',lambda:'host')
    monkeypatch.setattr(api.subprocess,'Popen',spawn)
    monkeypatch.setattr(api,'_PreviewLogs',Logs)
    monkeypatch.setattr(api,'_WindowsJob',lambda p:SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(api,'_kill_tree',lambda p:setattr(p,'code',0))
    monkeypatch.setattr(api.threading,'Timer',Timer)
    monkeypatch.setattr(api.httpx,'Client',Client)
    yield root,executable,procs
    api.stop_run('run');api.stop_run('other')


def test_owned_api_uses_project_venv_fixed_loopback_and_scoped_stop(runtime):
    root,executable,procs=runtime
    db=object();event=threading.Event()
    result=api.start(db,'u','run',str(root),'backend',event,lambda:True)
    assert result['api_status']=='running' and result['api_url'].startswith('http://127.0.0.1:')
    assert procs[0].argv[:4]==[str(executable),'-m','uvicorn','main:app']
    assert procs[0].kwargs['shell'] is False and procs[0].kwargs['cwd']==str(root/'backend')
    assert not any(k.startswith('CENTRAL_') for k in procs[0].kwargs['env'])
    assert api.status(object(),'u','run',str(root))['api_status']=='stopped'
    (root/'backend'/'main.py').write_text('app = changed')
    assert api.status(db,'u','run',str(root))['api_source_current'] is False
    api.start(db,'u','run',str(root),'backend',event,lambda:True)
    assert len(procs)==2 and procs[0].poll()==0
    assert api.status(db,'u','run',str(root))['api_source_current'] is True
    api.start(db,'u','other',str(root),'backend',event,lambda:True)
    api.stop_owned(db,'u','run',str(root))
    assert procs[1].poll()==0 and procs[2].poll() is None


def test_api_refuses_missing_venv_traversal_and_cancel_before_spawn(runtime):
    root,executable,procs=runtime
    executable.unlink()
    with pytest.raises(HTTPException) as err:
        api.start(object(),'u','run',str(root),'backend',threading.Event(),lambda:True)
    assert err.value.status_code==422 and 'venv' in err.value.detail
    with pytest.raises(HTTPException):
        api.start(object(),'u','run',str(root),'../',threading.Event(),lambda:True)
    executable.write_bytes(b'fixture')
    cancelled=threading.Event();cancelled.set()
    with pytest.raises(HTTPException):
        api.start(object(),'u','run',str(root),'backend',cancelled,lambda:True)
    assert not procs
