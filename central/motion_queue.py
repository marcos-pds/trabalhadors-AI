"""Owned, durable local media jobs. Typed commands only; never shell strings.

Runtime presence, successful execution and artifact verification are separate.
This executor runs trusted local media tools; it is not an OS sandbox.
"""
import asyncio
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time

from fastapi import HTTPException

from .computer_access import policy
from .database import uid, utcnow
from .motion_contracts import (ContractError, _root, configured_motion,
                               plan_jobs, scoped_path, validate_manifest, MotionConfig, _bounded_manifest)

MAX_BYTES = 2 * 1024**3
TERMINAL = {'completed','failed','cancelled','interrupted'}


def digest_file(path):
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > MAX_BYTES:
        raise ContractError('invalid media file or size')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def authorized_root(db, user, relative=''):
    if os.environ.get('CENTRAL_DEPLOYMENT_MODE','local') != 'local':
        raise HTTPException(403,'Motion exige execução local.')
    grant = policy(db,user)
    if grant['mode'] != 'full' or not grant['folder']:
        raise HTTPException(403,'Autorize uma pasta em Computador para executar mídia.')
    base = _root(grant['folder'])
    from .workspace_tools import target
    root = _root(target(str(base),relative,directory=True)) if relative else base
    return root, str(base)


def receipt(path, artifact):
    digest = digest_file(path)
    with path.open('rb') as stream:
        header=stream.read(16)
    if (artifact['kind']=='video' and header[4:8] != b'ftyp' or
        artifact['kind']=='audio' and not (header[:4]==b'RIFF' and header[8:12]==b'WAVE')):
        raise ContractError('output is not the declared media format')
    if artifact['kind']=='captions':
        if path.stat().st_size>16*1024**2:
            raise ContractError('captions too large')
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or not isinstance(data.get('segments'),list):
            raise ContractError('invalid transcription output')
    return {'id':artifact['id'],'kind':artifact['kind'],'path':artifact['path'],
            'bytes':path.stat().st_size,'sha256':digest}


class MotionQueue:
    def __init__(self,db,config=None,timeout=1800,resources=None):
        self.db=db
        self.config=config
        self.timeout=timeout
        # Cooperative process-local reservations; no model is unloaded here.
        self.resources=resources

    def _config(self,user=None):
        if self.config:return self.config
        row=self.db.one('SELECT config FROM motion_tool_settings WHERE user_id=?',(user,)) if user else None
        return MotionConfig(**json.loads(row['config'])) if row else configured_motion()

    def settings(self,user,config=None):
        authorized_root(self.db,user)
        from dataclasses import asdict
        row=self.db.one('SELECT config FROM motion_tool_settings WHERE user_id=?',(user,))
        if config is not None:
            value=MotionConfig(**config)
        elif row:
            value=MotionConfig(**json.loads(row['config']))
            discovered=configured_motion()
            if not value.comfy_root and discovered.comfy_root:
                merged={**(discovered.executables or {}),**(value.executables or {})}
                value=MotionConfig(
                    comfy_endpoint=value.comfy_endpoint or discovered.comfy_endpoint,
                    comfy_root=discovered.comfy_root,
                    allow_remote=value.allow_remote,
                    executables=merged or None,
                )
        else:
            value=configured_motion()
        if config is not None or not row:
            self.db.execute('INSERT INTO motion_tool_settings(user_id,config,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET config=excluded.config,updated_at=excluded.updated_at',
                            (user,json.dumps(asdict(value)),utcnow()))
        return asdict(value)

    def preview(self,user,manifest,relative=''):
        root,_=authorized_root(self.db,user,relative)
        data=validate_manifest(manifest,root)
        plans=plan_jobs(data,root,self._config(user))
        self._check_workflows(data,root,user)
        return {'jobs':[{'id':p.job_id,'adapter':p.adapter,'status':p.status,
                         'reason':p.reason,'argv':list(p.command.argv) if p.command else None}
                        for p in plans], 'executable':all(p.command is not None or p.service_operation is not None for p in plans)}

    def _check_workflows(self,data,root,user):
        from .comfy_motion import prepare_workflow
        artifacts={a['id']:a for a in data['artifacts']}
        for job in data['jobs']:
            if job['adapter']=='comfyui_wan':
                prepare_workflow(scoped_path(root,artifacts[job['inputs'][0]]['path']),job['params'],'preview',self._config(user))

    def enqueue(self,user,manifest,request_id,relative=''):
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',request_id):
            raise HTTPException(422,'Identificador de solicitação inválido.')
        root,grant=authorized_root(self.db,user,relative)
        _bounded_manifest(manifest)
        serialized=json.dumps(manifest,sort_keys=True,separators=(',',':'))
        digest=hashlib.sha256(serialized.encode()).hexdigest()
        existing=self.db.one('SELECT id,digest,root FROM motion_runs WHERE user_id=? AND request_id=?',(user,request_id))
        if existing:
            if existing['digest']!=digest or existing['root']!=str(root):
                raise HTTPException(409,'Identificador já usado para outro plano.')
            return self.get(user,existing['id'])
        data=validate_manifest(manifest,root)
        plans=plan_jobs(data,root,self._config(user))
        if not plans or any(p.command is None and p.service_operation is None for p in plans):
            raise HTTPException(409,'Ferramenta ausente ou adaptador sem executor disponível.')
        self._check_workflows(data,root,user)
        inputs={a['id']:digest_file(scoped_path(root,a['path'])) for a in data['artifacts']
                if a['provenance']['source']=='local'}
        for a in data['artifacts']:
            if a['id'] in inputs and a['provenance'].get('sha256',inputs[a['id']])!=inputs[a['id']]:
                raise ContractError('input digest mismatch')
        runtimes={p.job_id:({'argv':list(p.command.argv),'program_sha256':digest_file(Path(p.command.argv[0]))}
                          if p.command else {'endpoint':p.endpoint,'service':'comfy_wan_v1'})
                  for p in plans}
        for p in plans:
            if p.adapter=='remotion' and len(p.command.argv)>1 and p.command.argv[1].endswith('.js'):
                runtimes[p.job_id]['entry_sha256']=digest_file(Path(p.command.argv[1]))
            if p.adapter=='episode_assembly':
                runtimes[p.job_id]['entry_sha256']=digest_file(Path(p.command.argv[1]))
        rid=uid(); now=utcnow()
        with self.db.lock:
            self.db.conn.execute('BEGIN IMMEDIATE')
            try:
                # Serialize idempotent enqueue across API processes.
                row=self.db.one('SELECT id,digest,root FROM motion_runs WHERE user_id=? AND request_id=?',(user,request_id))
                if row:
                    if row['digest']!=digest or row['root']!=str(root):
                        raise HTTPException(409,'Identificador já usado para outro plano.')
                    rid=row['id']
                else:
                    self.db.execute('INSERT INTO motion_runs(id,user_id,request_id,root,grant_root,manifest,digest,inputs,state,created_at,updated_at,runtimes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                                    (rid,user,request_id,str(root),grant,serialized,digest,json.dumps(inputs),'queued',now,now,json.dumps(runtimes)))
                    for job in data['jobs']:
                        self.db.execute('INSERT INTO motion_jobs(run_id,id,adapter,state) VALUES(?,?,?,?)',
                                        (rid,job['id'],job['adapter'],'queued'))
                self.db.conn.execute('COMMIT')
            except BaseException:
                self.db.conn.execute('ROLLBACK');raise
        return self.get(user,rid)

    def get(self,user,rid):
        run=self.db.one('SELECT id,state,error,created_at,updated_at,cancel_requested FROM motion_runs WHERE id=? AND user_id=?',(rid,user))
        if not run:raise HTTPException(404,'Renderização não encontrada.')
        jobs=self.db.all('SELECT id,adapter,state,artifact,error,started_at,finished_at,remote_id FROM motion_jobs WHERE run_id=? ORDER BY rowid',(rid,))
        for job in jobs:
            job['artifact']=json.loads(job['artifact']) if job['artifact'] else None
        return dict(run,jobs=jobs)

    def list(self,user):
        return [self.get(user,r['id']) for r in self.db.all('SELECT id FROM motion_runs WHERE user_id=? ORDER BY created_at DESC LIMIT 30',(user,))]

    def cancel(self,user,rid):
        self.get(user,rid)
        self.db.execute("UPDATE motion_runs SET cancel_requested=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END,updated_at=? WHERE id=? AND user_id=? AND state IN ('queued','running')",(utcnow(),rid,user))
        self.db.execute("UPDATE motion_jobs SET state='cancelled',finished_at=? WHERE run_id=? AND state='queued' AND EXISTS(SELECT 1 FROM motion_runs WHERE id=? AND state='cancelled')",(utcnow(),rid,rid))
        return self.get(user,rid)

    def _check(self,row,stop):
        current=self.db.one('SELECT cancel_requested,lease_owner,state FROM motion_runs WHERE id=?',(row['id'],))
        if stop.is_set():raise InterruptedError('worker_stopped')
        if not current or current['cancel_requested']:raise InterruptedError('cancelled')
        if current['state']!='running' or current['lease_owner']!=row['lease_owner']:
            raise InterruptedError('lease_lost')
        root,grant=authorized_root(self.db,row['user_id'])
        if grant!=row['grant_root'] or not _root(row['root']).is_relative_to(root):
            raise HTTPException(403,'Permissão de pasta alterada.')
        self.db.execute('UPDATE motion_runs SET heartbeat=?,updated_at=? WHERE id=? AND lease_owner=?',
                        (time.time(),utcnow(),row['id'],row['lease_owner']))

    def process_one(self,stop=None):
        stop=stop or threading.Event()
        owner=uid();now=time.time()
        with self.db.lock:
            self.db.conn.execute('BEGIN IMMEDIATE')
            try:
                # Never silently replay a crashed render over partially written files.
                self.db.execute("UPDATE motion_jobs SET state='interrupted',error='worker_lost',finished_at=? WHERE state IN ('queued','running') AND run_id IN (SELECT id FROM motion_runs WHERE state='running' AND heartbeat<?)",(utcnow(),now-120))
                self.db.execute("UPDATE motion_runs SET state='interrupted',error='worker_lost',updated_at=? WHERE state='running' AND heartbeat<?",(utcnow(),now-120))
                row=self.db.one("SELECT * FROM motion_runs WHERE state='queued' ORDER BY created_at LIMIT 1")
                if row:
                    self.db.execute("UPDATE motion_runs SET state='running',lease_owner=?,heartbeat=?,updated_at=? WHERE id=? AND state='queued'",(owner,now,utcnow(),row['id']))
                    row['lease_owner']=owner
                self.db.conn.execute('COMMIT')
            except BaseException:
                self.db.conn.execute('ROLLBACK');raise
        if not row:return False
        state,error='completed',None
        try:
            data=json.loads(row['manifest']);root=Path(row['root'])
            by_id={a['id']:a for a in data['artifacts']}; hashes=json.loads(row['inputs'])
            # Plans are re-created before any outputs exist, then each path and
            # input digest is checked immediately before its own job.
            plans=plan_jobs(data,root,self._config(row['user_id']))
            runtimes=json.loads(row['runtimes'])
            for job,plan in zip(data['jobs'],plans):
                self._check(row,stop)
                if not plan.command and not plan.service_operation:raise ContractError('runtime_unavailable')
                expected=runtimes.get(plan.job_id,{})
                if plan.command and (expected.get('argv')!=list(plan.command.argv) or
                    expected.get('program_sha256')!=digest_file(Path(plan.command.argv[0])) or
                    ('entry_sha256' in expected and expected['entry_sha256']!=digest_file(Path(plan.command.argv[1])))):
                    raise ContractError('runtime_changed')
                for aid in job['inputs']:
                    path=scoped_path(root,by_id[aid]['path'])
                    if digest_file(path)!=hashes[aid]:raise ContractError('input_changed')
                output=by_id[job['outputs'][0]]
                destination=scoped_path(root,output['path'],output=True)
                destination.parent.mkdir(parents=True,exist_ok=True)
                scoped_path(root,output['path'],output=True)
                self.db.execute("UPDATE motion_jobs SET state='running',started_at=? WHERE run_id=? AND id=?",(utcnow(),row['id'],job['id']))
                provenance=None
                if plan.command:self._command(row,plan.command,stop)
                else:
                    if expected!={'endpoint':plan.endpoint,'service':'comfy_wan_v1'}:raise ContractError('runtime_changed')
                    from .comfy_runtime import COMFY_RUNTIME
                    from .comfy_motion import execute as render_comfy
                    # Only the Wan rendering call holds the process-local GPU slot.
                    # Planning, FFmpeg and other non-GPU steps are not serialized.
                    context=nullcontext()
                    if self.resources is not None:
                        from .resource_orchestrator import ResourceRequest
                        last_check=[0.0]
                        def pending():
                            now=time.monotonic()
                            if stop.is_set() or now-last_check[0]>=2:
                                self._check(row,stop)  # heartbeat and cancellation
                                last_check[0]=now
                            return False
                        context=self.resources.reserve(
                            ResourceRequest('motion_wan',gpu_slots=1,priority=5),
                            timeout=self.timeout,cancelled=pending)
                    with context as acquired_lease:
                        # Acquire the GPU slot before starting ComfyUI itself:
                        # loading its model can already allocate VRAM.
                        try:
                            COMFY_RUNTIME.ensure_started(self._config(row['user_id']))
                        except Exception:
                            raise ContractError('comfy_startup_failed') from None
                        def checked():
                            if acquired_lease is not None and hasattr(acquired_lease, 'assert_owned'):
                                acquired_lease.assert_owned()
                            self._check(row,stop)
                        checked()
                        source=job['inputs'][0]
                        provenance=render_comfy(scoped_path(root,by_id[source]['path']),destination,job['params'],
                            'central_motion_'+row['id']+'_'+job['id'],self._config(row['user_id']),
                            checked,
                            lambda prompt_id:self.db.execute('UPDATE motion_jobs SET remote_id=? WHERE run_id=? AND id=?',(prompt_id,row['id'],job['id'])),
                            timeout=self.timeout,expected_digest=hashes[source])
                self._check(row,stop)
                path=scoped_path(root,output['path'])
                artifact=receipt(path,output)
                if provenance:artifact['provenance']=provenance
                hashes[output['id']]=artifact['sha256']
                self.db.execute("UPDATE motion_jobs SET state='completed',artifact=?,finished_at=? WHERE run_id=? AND id=?",(json.dumps(artifact),utcnow(),row['id'],job['id']))
        except InterruptedError as exc:
            state='interrupted' if str(exc)!='cancelled' else 'cancelled';error=str(exc)
        except Exception as exc:
            state='failed'
            # Do not persist subprocess output, paths, arbitrary error strings or secrets.
            known={'input_changed','runtime_changed','runtime_unavailable','media_process_failed','process_output_limit','render_timeout','comfy_startup_failed'}
            from .comfy_motion import ERRORS
            known.update(ERRORS)
            error=exc.detail if isinstance(exc,HTTPException) else str(exc) if str(exc) in known else type(exc).__name__
        self.db.execute("UPDATE motion_jobs SET state=?,error=?,finished_at=? WHERE run_id=? AND state IN ('queued','running')",(state,error,utcnow(),row['id']))
        self.db.execute("UPDATE motion_runs SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE ? END,error=?,updated_at=? WHERE id=? AND lease_owner=?",(state,error,utcnow(),row['id'],owner))
        return True

    def _command(self,row,command,stop):
        from .external_runtimes import _WindowsJob, _isolated_environment
        from .workspace_tools import _kill_tree
        proc=None;job=None;deadline=time.monotonic()+self.timeout
        with tempfile.TemporaryDirectory(prefix='central-motion-') as home, tempfile.TemporaryFile() as log:
            try:
                env=_isolated_environment(home)
                from .motion_contracts import runtime_path
                ffmpeg=runtime_path('ffmpeg',self._config(row['user_id']))
                if ffmpeg:env['PATH']=str(Path(ffmpeg).parent)+os.pathsep+env.get('PATH','')
                database=self.db.one('SELECT file FROM pragma_database_list WHERE name=?',('main',))
                if database and database['file']:
                    data_root=_root(Path(database['file']).parent)
                    cache=data_root/'motion-cache'/hashlib.sha256(row['user_id'].encode()).hexdigest()[:24]
                    cache.mkdir(parents=True,exist_ok=True)
                    _root(cache)
                    env['HF_HOME']=str(cache)
                    env['XDG_CACHE_HOME']=str(cache)
                proc=subprocess.Popen(command.argv,cwd=command.cwd,shell=False,
                    env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                    start_new_session=os.name!='nt')
                if os.name=='nt':job=_WindowsJob(proc)
                while proc.poll() is None:
                    self._check(row,stop)
                    if time.monotonic()>deadline:raise TimeoutError('render_timeout')
                    if log.tell()>4*1024**2:raise ContractError('process_output_limit')
                    time.sleep(.2)
                if proc.returncode!=0:raise ContractError('media_process_failed')
            finally:
                if proc and proc.poll() is None:_kill_tree(proc)
                if job:job.close()

    def artifact_path(self,user,rid,artifact_id):
        run=self.get(user,rid)
        row=self.db.one('SELECT root,grant_root FROM motion_runs WHERE id=?',(rid,))
        root,grant=authorized_root(self.db,user)
        if grant!=row['grant_root'] or not _root(row['root']).is_relative_to(root):
            raise HTTPException(403,'Permissão de pasta alterada.')
        artifact=next((j['artifact'] for j in run['jobs'] if j['state']=='completed' and j['artifact'] and j['artifact']['id']==artifact_id),None)
        if not artifact:raise HTTPException(404,'Artefato não disponível.')
        path=scoped_path(row['root'],artifact['path'])
        if digest_file(path)!=artifact['sha256']:raise HTTPException(409,'Artefato alterado após a renderização.')
        return path

    async def dispatch(self,stop):
        while not stop.is_set():
            try:
                await asyncio.to_thread(self.process_one,stop)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning('Motion dispatcher: %s',type(exc).__name__)
            await asyncio.sleep(.5)
