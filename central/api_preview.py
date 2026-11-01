"""Run-owned loopback FastAPI preview. No arbitrary module, port or shell args."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from fastapi import HTTPException
import httpx

from .external_runtimes import _WindowsJob,_isolated_environment
from .live_preview import _port,_PreviewLogs
from .workspace_tools import target,_kill_tree
from .sandbox_executor import backend

_LOCK=threading.RLock()
_ENTRIES={}


def _finish(entry):
    timer=entry.get('timer')
    if timer:timer.cancel()
    try:_kill_tree(entry['process'])
    finally:
        if entry.get('job'):entry['job'].close()
        if entry.get('logs'):entry['logs'].close()
        entry['home'].cleanup()


def stop_run(run_id):
    with _LOCK:
        entries=[_ENTRIES.pop(k) for k in list(_ENTRIES) if k[2]==run_id]
    for entry in entries:_finish(entry)
    return {'status':'stopped'}


def stop_owned(db,user_id,run_id,folder):
    with _LOCK:entry=_ENTRIES.pop((id(db),user_id,run_id,folder),None)
    if entry:_finish(entry)
    return {'api_status':'stopped'}


def status(db,user_id,run_id,folder):
    with _LOCK:
        entry=_ENTRIES.get((id(db),user_id,run_id,folder))
        if not entry or entry['process'].poll() is not None:return {'api_status':'stopped'}
        return {'api_status':'running','api_url':entry['url'],'api_cwd':entry['cwd']}


def start(db,user_id,run_id,folder,cwd,cancelled,authorize):
    if backend()!='host':raise HTTPException(409,'Prévia FastAPI exige o executor local host.')
    directory=target(folder,cwd,directory=True)
    target(str(directory),'main.py')
    executable=directory/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not executable.is_file():
        raise HTTPException(422,'Crie uma .venv neste cwd e instale requirements.txt antes de iniciar a API. Use venv_create e pip_requirements.')
    current=directory
    for part in ('.venv', 'Scripts' if os.name=='nt' else 'bin'):
        current=current/part
        if current.is_symlink() or (hasattr(current,'is_junction') and current.is_junction()):
            raise HTTPException(403,'Ambiente Python não pode usar diretórios ligados.')
    key=(id(db),user_id,run_id,folder)
    with _LOCK:
        existing=_ENTRIES.get(key)
        if existing and existing['process'].poll() is None:
            if existing['cwd']!=cwd:raise HTTPException(409,'Pare a API antes de mudar o cwd.')
            return status(db,user_id,run_id,folder)
        if existing:
            _ENTRIES.pop(key);_finish(existing)
        if cancelled.is_set() or not authorize():raise HTTPException(409,'Prévia cancelada ou pasta revogada.')
        home=tempfile.TemporaryDirectory(prefix='central-api-preview-')
        port=_port()
        proc=None;job=None
        try:
            proc=subprocess.Popen([str(executable),'-m','uvicorn','main:app','--host','127.0.0.1','--port',str(port)],
                                  cwd=str(directory),env=_isolated_environment(home.name),stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE,stderr=subprocess.STDOUT,shell=False,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                                  start_new_session=os.name!='nt')
            if os.name=='nt':job=_WindowsJob(proc)
            entry={'process':proc,'job':job,'home':home,'cwd':cwd,'url':f'http://127.0.0.1:{port}',
                   'logs':_PreviewLogs(proc),'deadline':time.monotonic()+1800}
            _ENTRIES[key]=entry
        except BaseException:
            if proc:_kill_tree(proc)
            if job:job.close()
            home.cleanup();raise
    def watch():
        with _LOCK:
            if _ENTRIES.get(key) is not entry:return
            try:alive=not cancelled.is_set() and time.monotonic()<entry['deadline'] and authorize() and proc.poll() is None
            except Exception:alive=False
            if alive:
                timer=threading.Timer(2,watch);timer.daemon=True;entry['timer']=timer;timer.start();return
            _ENTRIES.pop(key,None)
        _finish(entry)
    watch()
    try:
        with httpx.Client(timeout=1,trust_env=False,follow_redirects=False) as client:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if cancelled.is_set() or proc.poll() is not None or not authorize():break
                try:
                    response=client.get(entry['url']+'/api/health')
                    if response.status_code==200 and response.json().get('ok') is True:
                        return dict(status(db,user_id,run_id,folder),output='API pronta em '+entry['url']+'. Configure o proxy /api do Vite para esta URL e reinicie a prévia frontend se necessário.')
                except (httpx.HTTPError,ValueError,AttributeError):pass
                time.sleep(.25)
        logs=entry['logs'].recent()
        raise HTTPException(422,'API não ficou pronta em /api/health. Corrija o erro e tente novamente. Logs locais: '+logs[-2400:])
    except BaseException:
        with _LOCK:
            if _ENTRIES.get(key) is entry:_ENTRIES.pop(key,None)
        _finish(entry);raise
