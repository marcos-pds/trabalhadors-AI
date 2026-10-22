import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .database import Database, uid, utcnow
from .security import Security, password_hash, verify_password, require_owned
from .engine import Engine, TEMPLATES, validate_flow
from .providers import DEFAULT_ENDPOINTS, ProviderError
from .workspace import WorkspaceError
from .roles import worker_role, role_source
from .runtime import RuntimeManager

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('CENTRAL_DATA_DIR', ROOT/'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = Database(DATA_DIR/'central.sqlite3')
SEC = Security(DB, DATA_DIR)
ENGINE = Engine(DB, SEC)
RUNTIME = RuntimeManager(DB, ENGINE.workspaces)


@asynccontextmanager
async def lifespan(app):
    ENGINE.shutting_down = False
    ENGINE.resume_pending()
    yield
    ENGINE.shutting_down = True
    RUNTIME.shutdown()
    pending = list(ENGINE.running.values())
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title='Central de Trabalhadores IA', version='0.3.0', lifespan=lifespan)


@app.exception_handler(WorkspaceError)
async def workspace_exception(request:Request, exc:WorkspaceError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status,content={'detail':str(exc)})
app.mount('/assets', StaticFiles(directory=ROOT/'static'), name='assets')


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(ROOT/'static'/'index.html')


def current_user(request: Request):
    return SEC.user(request)


def require_csrf(request: Request):
    if request.headers.get('x-central-request') != '1':
        raise HTTPException(403,'Cabeçalho de proteção obrigatório.')
    origin = request.headers.get('origin')
    if origin:
        o = urlparse(origin)
        if o.hostname != request.url.hostname or o.scheme != request.url.scheme:
            raise HTTPException(403,'Origem não autorizada.')


class Credentials(BaseModel):
    email: str = Field(min_length=5,max_length=180)
    password: str = Field(min_length=10,max_length=200)


@app.post('/api/register')
def register(data: Credentials, request: Request, response: Response):
    require_csrf(request)
    email = data.email.strip().lower()
    if '@' not in email: raise HTTPException(422,'E-mail inválido.')
    if DB.one('SELECT id FROM users WHERE email=?',(email,)):
        raise HTTPException(409,'E-mail já cadastrado.')
    user_id = uid()
    DB.execute('INSERT INTO users VALUES(?,?,?,?)', (user_id,email,password_hash(data.password),utcnow()))
    for name,specialty,instructions,avatar in TEMPLATES:
        DB.execute('''INSERT INTO agents(id,user_id,name,specialty,instructions,avatar,created_at)
          VALUES(?,?,?,?,?,?,?)''', (uid(),user_id,name,specialty,instructions,avatar,utcnow()))
    token = SEC.create_session(user_id)
    response.set_cookie('central_session',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=604800)
    return {'id':user_id,'email':email}


@app.post('/api/login')
def login(data: Credentials, request: Request, response: Response):
    require_csrf(request)
    row = DB.one('SELECT * FROM users WHERE email=?',(data.email.strip().lower(),))
    if not row or not verify_password(data.password,row['password_hash']):
        raise HTTPException(401,'E-mail ou senha incorretos.')
    token = SEC.create_session(row['id'])
    response.set_cookie('central_session',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=604800)
    return {'id':row['id'],'email':row['email']}


@app.post('/api/logout')
def logout(request:Request,response:Response,user=Depends(current_user)):
    import hashlib
    token=request.cookies.get('central_session','')
    DB.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie('central_session')
    return {'ok':True}


@app.get('/api/me')
def me(user=Depends(current_user)):
    return user


class ProviderIn(BaseModel):
    name: str = Field(min_length=2,max_length=70)
    kind: str = 'openai'
    base_url: str = ''
    model: str = Field(min_length=1,max_length=120)
    api_key: str = ''
    priority: int = Field(default=5,ge=1,le=99)
    enabled: bool = True
    input_price: float | None = Field(default=None,ge=0)
    output_price: float | None = Field(default=None,ge=0)


def public_provider(row):
    health = ENGINE.health.detail(row['id'], row['model'])
    if not row['enabled']:
        health['state'] = 'disabled'
    return {k:row[k] for k in ('id','name','kind','base_url','model','priority','enabled','input_price','output_price','last_error','created_at')} | {'has_key':bool(row['api_key_enc']), 'health':health}


def check_provider(data):
    if data.kind not in DEFAULT_ENDPOINTS: raise HTTPException(422,'Provedor não suportado.')
    url = (data.base_url or DEFAULT_ENDPOINTS[data.kind]).rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422,'URL inválida.')
    if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):
        raise HTTPException(422,'HTTP somente para modelo local; use HTTPS.')
    return url


@app.get('/api/providers')
def list_providers(user=Depends(current_user)):
    return [public_provider(p) for p in DB.all('SELECT * FROM providers WHERE user_id=? ORDER BY priority ASC',(user['id'],))]


@app.post('/api/providers')
def add_provider(data:ProviderIn,user=Depends(current_user)):
    url = check_provider(data)
    pid=uid()
    DB.execute('''INSERT INTO providers(id,user_id,name,kind,base_url,model,api_key_enc,priority,enabled,input_price,output_price,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
      (pid,user['id'],data.name,data.kind,url,data.model,SEC.encrypt(data.api_key),data.priority,int(data.enabled),data.input_price,data.output_price,utcnow()))
    return public_provider(require_owned(DB,'providers',pid,user['id']))


@app.put('/api/providers/{pid}')
def update_provider(pid:str,data:ProviderIn,user=Depends(current_user)):
    previous = require_owned(DB,'providers',pid,user['id'])
    url = check_provider(data)
    key = SEC.encrypt(data.api_key) if data.api_key else previous['api_key_enc']
    DB.execute('''UPDATE providers SET name=?,kind=?,base_url=?,model=?,api_key_enc=?,priority=?,enabled=?,input_price=?,output_price=?,last_error=NULL WHERE id=?''',
    (data.name,data.kind,url,data.model,key,data.priority,int(data.enabled),data.input_price,data.output_price,pid))
    return public_provider(require_owned(DB,'providers',pid,user['id']))


@app.delete('/api/providers/{pid}')
def delete_provider(pid:str,user=Depends(current_user)):
    require_owned(DB,'providers',pid,user['id'])
    DB.execute('DELETE FROM providers WHERE id=?',(pid,))
    DB.execute('UPDATE agents SET provider_id=NULL WHERE provider_id=? AND user_id=?',(pid,user['id']))
    return {'ok':True}


@app.get('/api/providers/{pid}/attempts')
def provider_attempts(pid: str, user=Depends(current_user)):
    provider = require_owned(DB, 'providers', pid, user['id'])
    return ENGINE.health.attempts(pid, provider['model'], 30)


@app.post('/api/providers/{pid}/test')
async def test_provider(pid:str,user=Depends(current_user)):
    p = require_owned(DB,'providers',pid,user['id'])
    allowed, half_open = ENGINE.health.acquire(pid, p['model'])
    if not allowed:
        detail = ENGINE.health.detail(pid, p['model'])
        return {'ok':False,'category':'suspended',
                'error':f"Modelo temporariamente suspenso. Aguarde {detail['remaining_seconds']} segundos."}
    started = time.monotonic()
    try:
        chunks=[]
        async for part in ENGINE.client.stream(p,SEC.decrypt(p['api_key_enc']),p['model'],
                                               'Seja conciso.',[{'role':'user','content':'Responda somente OK.'}]):
            chunks.append(part)
            if sum(map(len,chunks))>100: break
        answer=''.join(chunks).strip()
        if not answer:
            raise ProviderError('response','Resposta vazia.',True)
        ENGINE.health.record(pid,p['model'],success=True,latency_ms=(time.monotonic()-started)*1000)
        DB.execute('UPDATE providers SET last_error=NULL WHERE id=?',(pid,))
        return {'ok':True,'response':answer[:110]}
    except ProviderError as e:
        ENGINE.health.record(pid,p['model'],success=False,error=e,latency_ms=(time.monotonic()-started)*1000)
        DB.execute('UPDATE providers SET last_error=? WHERE id=?',(str(e)[:220],pid))
        return {'ok':False,'category':e.category,'error':str(e)}
    except asyncio.CancelledError:
        if half_open: ENGINE.health.release_probe(pid,p['model'])
        raise
    except Exception:
        failure=ProviderError('internal','Falha interna na validação.',False)
        ENGINE.health.record(pid,p['model'],success=False,error=failure,latency_ms=(time.monotonic()-started)*1000)
        return {'ok':False,'category':'internal','error':'Falha interna na validação.'}


class AgentIn(BaseModel):
    name: str = Field(min_length=2,max_length=70)
    specialty: str = Field(default='custom',max_length=70)
    instructions: str = Field(min_length=4,max_length=12000)
    avatar: str = Field(default='✦',max_length=5)
    provider_id: str | None = None
    model: str | None = None
    enabled: bool = True
    max_concurrency: int = Field(default=2,ge=1,le=10)


@app.get('/api/agents')
def list_agents(user=Depends(current_user)):
    agents=DB.all('SELECT * FROM agents WHERE user_id=? ORDER BY created_at',(user['id'],))
    return [dict(agent,resolved_role=worker_role(agent),role_source=role_source(agent))
            for agent in agents]


@app.post('/api/agents')
def add_agent(data:AgentIn,user=Depends(current_user)):
    if data.provider_id: require_owned(DB,'providers',data.provider_id,user['id'])
    aid=uid()
    DB.execute('''INSERT INTO agents(id,user_id,name,specialty,instructions,avatar,provider_id,model,enabled,max_concurrency,created_at)
       VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (aid,user['id'],data.name,data.specialty,data.instructions,data.avatar,
       data.provider_id,data.model,int(data.enabled),data.max_concurrency,utcnow()))
    return require_owned(DB,'agents',aid,user['id'])


@app.put('/api/agents/{aid}')
def edit_agent(aid:str,data:AgentIn,user=Depends(current_user)):
    require_owned(DB,'agents',aid,user['id'])
    if data.provider_id: require_owned(DB,'providers',data.provider_id,user['id'])
    DB.execute('''UPDATE agents SET name=?,specialty=?,instructions=?,avatar=?,provider_id=?,model=?,enabled=?,max_concurrency=? WHERE id=?''',
    (data.name,data.specialty,data.instructions,data.avatar,data.provider_id,data.model,int(data.enabled),data.max_concurrency,aid))
    return require_owned(DB,'agents',aid,user['id'])


@app.delete('/api/agents/{aid}')
def remove_agent(aid:str,user=Depends(current_user)):
    require_owned(DB,'agents',aid,user['id'])
    # Keep historical step references and do not destroy an agent used in existing jobs.
    DB.execute('UPDATE agents SET enabled=0 WHERE id=?',(aid,))
    return {'ok':True}


class ProjectIn(BaseModel):
    name:str = Field(min_length=1,max_length=90)
    description:str = Field(default='',max_length=2000)


@app.get('/api/projects')
def projects(user=Depends(current_user)):
    return DB.all('SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC',(user['id'],))


@app.post('/api/projects')
def add_project(data:ProjectIn,user=Depends(current_user)):
    pid=uid()
    DB.execute('INSERT INTO projects VALUES(?,?,?,?,?)',(pid,user['id'],data.name,data.description,utcnow()))
    return require_owned(DB,'projects',pid,user['id'])


@app.get('/api/projects/{pid}/workspace')
def workspace_info(pid:str,user=Depends(current_user)):
    require_owned(DB,'projects',pid,user['id'])
    return ENGINE.workspaces.info(user['id'],pid)


@app.post('/api/projects/{pid}/workspace')
def prepare_workspace(pid:str,user=Depends(current_user)):
    require_owned(DB,'projects',pid,user['id'])
    return ENGINE.workspaces.initialize(user['id'],pid)


@app.get('/api/projects/{pid}/workspace/file')
def workspace_file(pid:str,path:str,user=Depends(current_user)):
    require_owned(DB,'projects',pid,user['id'])
    return ENGINE.workspaces.read(user['id'],pid,path)


class ChangesIn(BaseModel):
    files: list[dict] = Field(min_length=1,max_length=20)


@app.post('/api/projects/{pid}/workspace/proposals')
def propose_workspace_files(pid:str,data:ChangesIn,user=Depends(current_user)):
    require_owned(DB,'projects',pid,user['id'])
    return ENGINE.workspaces.stage(user['id'],pid,data.files,agent='Manual')


@app.get('/api/projects/{pid}/workspace/proposals/{proposal_id}')
def preview_proposal(pid:str,proposal_id:str,user=Depends(current_user)):
    require_owned(DB,'projects',pid,user['id'])
    return ENGINE.workspaces.proposal(user['id'],pid,proposal_id)


class ProposalDecision(BaseModel):
    approved: bool
    confirmation: str = ''


@app.post('/api/projects/{pid}/workspace/proposals/{proposal_id}/decision')
def decide_proposal(pid:str,proposal_id:str,data:ProposalDecision,user=Depends(current_user)):
    require_owned(DB,'projects',pid,user['id'])
    if data.approved and data.confirmation!='APLICAR':
        raise HTTPException(422,'Confirme explicitamente a operação com APLICAR.')
    return ENGINE.workspaces.decide(user['id'],pid,proposal_id,data.approved)



@app.get('/api/skills')
def skills_catalog(project_id:str|None=None,user=Depends(current_user)):
    if project_id: require_owned(DB,'projects',project_id,user['id'])
    return ENGINE.skills.catalog(user['id'],project_id)


class SkillToggle(BaseModel):
    enabled: bool


@app.post('/api/projects/{pid}/skills/{skill_id}')
def set_project_skill(pid:str,skill_id:str,data:SkillToggle,request:Request,user=Depends(current_user)):
    require_csrf(request)
    require_owned(DB,'projects',pid,user['id'])
    return ENGINE.skills.enable(user['id'],pid,skill_id,data.enabled)


@app.get('/api/projects/{pid}/package-installs')
def project_package_installs(pid:str,user=Depends(current_user)):
    require_owned(DB,'projects',pid,user['id'])
    return ENGINE.skills.installs(user['id'],pid)


@app.get('/api/conversations/{cid}/architect-delegation')
def architect_delegation(cid:str,user=Depends(current_user)):
    require_owned(DB,'conversations',cid,user['id'])
    return ENGINE.skills.delegation(user['id'],cid)


class ArchitectDelegationIn(BaseModel):
    enabled: bool


@app.post('/api/conversations/{cid}/architect-delegation')
def change_architect_delegation(cid:str,data:ArchitectDelegationIn,
                                request:Request,user=Depends(current_user)):
    require_csrf(request)
    require_owned(DB,'conversations',cid,user['id'])
    return ENGINE.skills.set_delegation(user['id'],cid,data.enabled)


class ConversationIn(BaseModel):
    title:str = Field(default='Nova conversa',max_length=140)
    project_id:str | None = None


@app.get('/api/conversations')
def conversations(user=Depends(current_user)):
    return DB.all('SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT 100',(user['id'],))


@app.post('/api/conversations')
def new_conversation(data:ConversationIn,user=Depends(current_user)):
    if data.project_id: require_owned(DB,'projects',data.project_id,user['id'])
    cid,now=uid(),utcnow()
    DB.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',(cid,user['id'],data.title,data.project_id,now,now))
    return require_owned(DB,'conversations',cid,user['id'])



class RuntimeAccessIn(BaseModel):
    enabled: bool


@app.get('/api/conversations/{cid}/runtime')
def local_runtime_status(cid:str,user=Depends(current_user)):
    require_owned(DB,'conversations',cid,user['id'])
    return RUNTIME.status(user['id'],cid)


@app.post('/api/conversations/{cid}/runtime/access')
def local_runtime_access(cid:str,data:RuntimeAccessIn,
                         request:Request,user=Depends(current_user)):
    require_csrf(request)
    require_owned(DB,'conversations',cid,user['id'])
    return RUNTIME.authorize(user['id'],cid,data.enabled)


@app.post('/api/conversations/{cid}/runtime/start')
def local_runtime_start(cid:str,request:Request,user=Depends(current_user)):
    require_csrf(request)
    require_owned(DB,'conversations',cid,user['id'])
    return RUNTIME.start(user['id'],cid)


@app.post('/api/conversations/{cid}/runtime/stop')
def local_runtime_stop(cid:str,request:Request,user=Depends(current_user)):
    require_csrf(request)
    require_owned(DB,'conversations',cid,user['id'])
    return RUNTIME.stop(user['id'],cid)


class ConversationProjectIn(BaseModel):
    project_id: str | None = None


@app.post('/api/conversations/{cid}/project')
def change_conversation_project(cid:str,data:ConversationProjectIn,
                                request:Request,user=Depends(current_user)):
    """Bind a draft chat to a project. Existing history remains immutable.

    Once a message or run exists, switch project by opening a NEW conversation.
    This prevents old runs, file proposals or architect authority from crossing
    project boundaries.
    """
    require_csrf(request)
    if data.project_id:
        require_owned(DB,'projects',data.project_id,user['id'])
    with DB.lock:
        convo=require_owned(DB,'conversations',cid,user['id'])
        if data.project_id==convo['project_id']:
            return convo
        used=DB.one('''SELECT 1 AS used FROM messages
                       WHERE conversation_id=? AND user_id=? LIMIT 1''',
                    (cid,user['id']))
        runs=DB.one('''SELECT 1 AS used FROM runs
                       WHERE conversation_id=? AND user_id=? LIMIT 1''',
                    (cid,user['id']))
        if used or runs:
            raise HTTPException(409,'Esta conversa já possui histórico. Crie uma nova conversa para trocar de projeto.')
        DB.execute('DELETE FROM architect_delegations WHERE conversation_id=? AND user_id=?',
                   (cid,user['id']))
        # Stop any server launched under the old project before changing
        # this draft conversation's project association.
        try:
            RUNTIME.stop(user['id'],cid)
        except WorkspaceError:
            pass
        DB.execute('DELETE FROM runtime_permissions WHERE conversation_id=? AND user_id=?',
                   (cid,user['id']))
        DB.execute('UPDATE conversations SET project_id=?,updated_at=? WHERE id=? AND user_id=?',
                   (data.project_id,utcnow(),cid,user['id']))
    return require_owned(DB,'conversations',cid,user['id'])


@app.get('/api/conversations/{cid}/messages')
def convo_messages(cid:str,user=Depends(current_user)):
    require_owned(DB,'conversations',cid,user['id'])
    return DB.all('SELECT * FROM messages WHERE conversation_id=? AND user_id=? ORDER BY created_at',(cid,user['id']))


class RunIn(BaseModel):
    conversation_id: str
    prompt: str = Field(min_length=1,max_length=30000)
    mode: str = 'auto'
    agent_ids: list[str] = Field(default_factory=list,max_length=5)
    workflow_id: str | None = None
    budget_limit: float | None = Field(default=None,ge=0)


@app.post('/api/runs')
async def start_run(data:RunIn, request:Request,user=Depends(current_user)):
    convo=require_owned(DB,'conversations',data.conversation_id,user['id'])
    if data.mode not in ('auto','manual','team'): raise HTTPException(422,'Modo inválido.')
    if data.agent_ids:
        for aid in data.agent_ids: require_owned(DB,'agents',aid,user['id'])
    flow=None
    if data.workflow_id:
        wf=require_owned(DB,'workflows',data.workflow_id,user['id'])
        flow=json.loads(wf['definition'])
    idempotency = request.headers.get('idempotency-key')
    if idempotency and len(idempotency)>100: raise HTTPException(422,'Chave de idempotência extensa demais.')
    if idempotency:
        existing=DB.one('SELECT id FROM runs WHERE user_id=? AND idempotency_key=?',(user['id'],idempotency))
        if existing: return {'id':existing['id']}
    # Do not record the user's prompt until the run was accepted. Otherwise
    # each 422 (e.g. disabled UI workers) adds another duplicate user bubble.
    try:
        workspace_prepared = ENGINE.workspaces.prepare_chat(user['id'],data.conversation_id,data.prompt)
        delegated = ENGINE.skills.instruction(user['id'],data.conversation_id,data.prompt)
        # An explicit request to USE the named local Skill activates its instructions
        # for this project. This never grants Architect permissions or runs packages.
        skill_activated = None
        linked = DB.one('SELECT project_id FROM conversations WHERE id=? AND user_id=?',
                        (data.conversation_id,user['id']))
        if (flow is None and linked and linked['project_id'] and
            ENGINE.skills.explicitly_requested(data.prompt)):
            skill_activated = ENGINE.skills.enable(user['id'],linked['project_id'],
                                                   'ux-ui-studio-pro',True)
        run_id=ENGINE.create_run(user['id'],data.conversation_id,data.prompt,data.mode,data.agent_ids,
                                 flow,data.budget_limit,idempotency)
        now=utcnow()
        DB.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                   (uid(),convo['id'],user['id'],'user',None,data.prompt,now))
        DB.execute('UPDATE conversations SET updated_at=?,title=? WHERE id=? AND user_id=?',
           (now,data.prompt[:60] if convo['title']=='Nova conversa' else convo['title'],
            convo['id'],user['id']))
        if workspace_prepared:
            ENGINE.emit(run_id,'workspace_prepared',workspace_prepared)
        if skill_activated:
            ENGINE.emit(run_id,'ui_skill_activated',{'project_id':linked['project_id'],
                                                    'skill_id':skill_activated['id']})
        if delegated is not None:
            ENGINE.emit(run_id,'architect_delegation_changed',delegated)
    except ValueError as exc: raise HTTPException(422,str(exc))
    return {'id':run_id}


@app.get('/api/runs')
def list_runs(user=Depends(current_user)):
    return DB.all('SELECT id,conversation_id,prompt,status,mode,error,total_cost,budget_limit,created_at,updated_at FROM runs WHERE user_id=? ORDER BY created_at DESC LIMIT 100',(user['id'],))


@app.get('/api/runs/{rid}')
def get_run(rid:str,user=Depends(current_user)):
    run=require_owned(DB,'runs',rid,user['id'])
    run['steps']=DB.all('SELECT * FROM steps WHERE run_id=?',(rid,))
    return run


@app.post('/api/runs/{rid}/resume')
async def resume_run(rid:str,user=Depends(current_user)):
    require_owned(DB,'runs',rid,user['id'])
    try: ENGINE.resume_run(rid)
    except ValueError as e: raise HTTPException(409,str(e))
    return {'ok':True}


@app.post('/api/runs/{rid}/cancel')
async def stop_run(rid:str,user=Depends(current_user)):
    require_owned(DB,'runs',rid,user['id'])
    ENGINE.cancel(rid)
    return {'ok':True}


class ApprovalIn(BaseModel):
    approved: bool


@app.post('/api/runs/{rid}/steps/{sid}/approval')
async def approve_step(rid:str,sid:str,data:ApprovalIn,user=Depends(current_user)):
    require_owned(DB,'runs',rid,user['id'])
    step=DB.one('SELECT * FROM steps WHERE id=? AND run_id=?',(sid,rid))
    if not step or step['kind']!='approval' or step['status']!='awaiting_approval':
        raise HTTPException(409,'Não há aprovação pendente.')
    ENGINE.approve(rid,sid,data.approved)
    return {'ok':True}


@app.get('/api/runs/{rid}/events')
async def events(rid:str, request:Request, after:int=0, user=Depends(current_user)):
    require_owned(DB,'runs',rid,user['id'])
    async def stream():
        cursor=max(0,after)
        while True:
            if await request.is_disconnected(): break
            items=DB.all('SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq ASC LIMIT 100',(rid,cursor))
            for e in items:
                cursor=e['seq']
                payload={'seq':e['seq'],'event':e['event'],'data':json.loads(e['payload'])}
                yield 'id: '+str(cursor)+'\ndata: '+json.dumps(payload,ensure_ascii=False)+'\n\n'
            run=DB.one('SELECT status FROM runs WHERE id=?',(rid,))
            if run and run['status'] in ('completed','failed','cancelled') and not items: break
            await asyncio.sleep(0.4)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})


class WorkflowIn(BaseModel):
    name:str=Field(min_length=1,max_length=90)
    description:str=Field(default='',max_length=600)
    definition:dict


@app.get('/api/workflows')
def workflows(user=Depends(current_user)):
    rows=DB.all('SELECT * FROM workflows WHERE user_id=? ORDER BY updated_at DESC',(user['id'],))
    for r in rows: r['definition']=json.loads(r['definition'])
    return rows


@app.post('/api/workflows')
def add_workflow(data:WorkflowIn,user=Depends(current_user)):
    agents=DB.all('SELECT * FROM agents WHERE user_id=?',(user['id'],))
    try:validate_flow(data.definition,agents)
    except ValueError as e:raise HTTPException(422,str(e))
    wid,now=uid(),utcnow()
    DB.execute('INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?)',(wid,user['id'],data.name,data.description,json.dumps(data.definition),1,now,now))
    return {'id':wid}


@app.put('/api/workflows/{wid}')
def update_workflow(wid:str,data:WorkflowIn,user=Depends(current_user)):
    require_owned(DB,'workflows',wid,user['id'])
    agents=DB.all('SELECT * FROM agents WHERE user_id=?',(user['id'],))
    try:validate_flow(data.definition,agents)
    except ValueError as e:raise HTTPException(422,str(e))
    DB.execute('UPDATE workflows SET name=?,description=?,definition=?,version=version+1,updated_at=? WHERE id=?',
       (data.name,data.description,json.dumps(data.definition),utcnow(),wid))
    return {'id':wid}


@app.post('/api/uploads/text')
async def upload_text(file:UploadFile=File(...),user=Depends(current_user)):
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in {'.txt','.md','.csv','.json','.py','.js','.ts','.tsx','.jsx','.html','.css','.sql','.yaml','.yml','.xml'}:
        raise HTTPException(415,'Suportamos apenas arquivos de texto/código nesta versão.')
    content=await file.read(2*1024*1024+1)
    if len(content)>2*1024*1024: raise HTTPException(413,'Máximo de 2 MB por arquivo.')
    try: text=content.decode('utf-8')
    except UnicodeError:raise HTTPException(415,'Arquivo precisa estar em UTF-8.')
    return {'name':Path(file.filename).name,'content':text[:27000], 'truncated':len(text)>27000}


@app.get('/api/dashboard')
def dashboard(user=Depends(current_user)):
    u=user['id']
    count=lambda q: DB.one(q,(u,))['n']
    return {
     'agents':count('SELECT COUNT(*) n FROM agents WHERE user_id=? AND enabled=1'),
     'providers':count('SELECT COUNT(*) n FROM providers WHERE user_id=? AND enabled=1'),
     'running':count("SELECT COUNT(*) n FROM runs WHERE user_id=? AND status IN ('running','awaiting_approval')"),
     'completed':count("SELECT COUNT(*) n FROM runs WHERE user_id=? AND status='completed'"),
     'failed':count("SELECT COUNT(*) n FROM runs WHERE user_id=? AND status='failed'"),
     'queued':count("SELECT COUNT(*) n FROM runs WHERE user_id=? AND status='queued'"),
     'failovers':DB.one('SELECT COUNT(*) n FROM events WHERE event=? AND run_id IN (SELECT id FROM runs WHERE user_id=?)',('failover',u))['n'],
     'estimated_cost': DB.one('SELECT COALESCE(SUM(total_cost),0) total FROM runs WHERE user_id=?',(u,))['total'],
     'recent':DB.all('SELECT id,prompt,status,created_at FROM runs WHERE user_id=? ORDER BY created_at DESC LIMIT 8',(u,)),
    }


@app.get('/api/health')
def health():
    return {'status':'ok','note':'Saúde da API local. Não significa que provedores estejam disponíveis.'}
