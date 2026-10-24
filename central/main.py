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
from .catalog import CATALOG, BY_KIND, discover_models, candidates

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('CENTRAL_DATA_DIR', ROOT/'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = Database(DATA_DIR/'central.sqlite3')
SEC = Security(DB, DATA_DIR)
ENGINE = Engine(DB, SEC)


@asynccontextmanager
async def lifespan(app):
    ENGINE.shutting_down = False
    ENGINE.resume_pending()
    yield
    ENGINE.shutting_down = True
    pending = list(ENGINE.running.values())
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title='Central de Trabalhadores IA', version='0.2.0', lifespan=lifespan)
FRONTEND_BUILD = ROOT/'static'/'build'
app.mount('/assets', StaticFiles(directory=ROOT/'static'), name='assets')


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(FRONTEND_BUILD/'index.html')


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


class QuickProviderIn(BaseModel):
    kind: str = Field(max_length=40)
    api_key: str = Field(default='', max_length=4096)
    model: str = Field(default='', max_length=120)
    provider_id: str | None = None


@app.get('/api/provider-catalog')
def provider_catalog(user=Depends(current_user)):
    return CATALOG


def quick_key(data, user):
    key = data.api_key.strip()
    if data.provider_id:
        previous = require_owned(DB, 'providers', data.provider_id, user['id'])
        if previous['kind'] != data.kind:
            raise HTTPException(422, 'O provedor selecionado não corresponde à chave salva.')
        if not key:
            key = SEC.decrypt(previous['api_key_enc'])
    return key


def reject_duplicate_model(user_id, kind, model, exclude_id=None):
    duplicate = DB.one('SELECT id FROM providers WHERE user_id=? AND kind=? AND TRIM(model)=? AND id<>? LIMIT 1',
                       (user_id, kind, model.strip(), exclude_id or ''))
    if duplicate:
        raise HTTPException(409, 'Este modelo já está cadastrado neste provedor. Use Editar para alterar ou reativar a conexão existente.')


def catalog_with_connections(models, user_id, kind):
    registered = {p['model'].strip() for p in DB.all('SELECT model FROM providers WHERE user_id=? AND kind=?', (user_id, kind))}
    return [dict(m, connected=m['id'].strip() in registered) for m in models]


@app.post('/api/provider-catalog/models')
async def provider_models(data: QuickProviderIn, request: Request, user=Depends(current_user)):
    require_csrf(request)
    try:
        models = await discover_models(data.kind, quick_key(data, user))
        return {'models': catalog_with_connections(models, user['id'], data.kind)}
    except ProviderError as exc:
        raise HTTPException(422, str(exc))


@app.post('/api/provider-catalog/connect')
async def connect_provider(data: QuickProviderIn, request: Request, user=Depends(current_user)):
    require_csrf(request)
    key = quick_key(data, user)
    if data.model:
        reject_duplicate_model(user['id'], data.kind, data.model)
    try:
        models = catalog_with_connections(await discover_models(data.kind, key), user['id'], data.kind)
        options = candidates([m for m in models if not m['connected']], data.kind, data.model)
        if data.model and not any(m['id'] == data.model for m in models):
            raise ProviderError('catalog', 'Modelo não encontrado no catálogo de chat do provedor.')
        if not options and any(m['eligible'] and m['connected'] for m in models) and not data.model:
            raise HTTPException(409, 'Todos os modelos elegíveis deste provedor já estão cadastrados. Use Editar para gerenciar suas conexões.')
        if not options:
            raise ProviderError('catalog', 'Nenhum modelo de chat elegível encontrado. Confira o plano e o catálogo; nenhum modelo pago será selecionado como alternativa.')
        provider = {'kind': data.kind, 'base_url': DEFAULT_ENDPOINTS[data.kind]}
        failures = []
        for model in options[:3]:
            started = time.monotonic()
            stream = ENGINE.client.stream(provider, key, model['id'], 'Seja conciso.',
                                          [{'role': 'user', 'content': 'Responda somente OK.'}])
            try:
                answer = ''
                async for part in stream:
                    answer += part
                    if answer.strip():
                        break
                if not answer.strip():
                    raise ProviderError('response', 'O modelo não retornou texto.', True)
                latency = (time.monotonic() - started) * 1000
                break
            except ProviderError as exc:
                if exc.category in ('authentication', 'credits'):
                    raise
                failures.append(exc.category)
            finally:
                await stream.aclose()
        else:
            raise ProviderError('validation', 'Os modelos encontrados não responderam ao teste (' + ', '.join(failures) + '). Nenhuma conexão foi alterada. Tente novamente.')
        # Recheck inside the write transaction to cover simultaneous connections.
        with DB.lock, DB.conn:
            DB.conn.execute('BEGIN IMMEDIATE')
            reject_duplicate_model(user['id'], data.kind, model['id'])
            pid = uid()
            DB.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) VALUES(?,?,?,?,?,?,?)',
                       (pid, user['id'], BY_KIND[data.kind]['name'], data.kind, provider['base_url'], model['id'], utcnow()))
            if data.kind == 'ollama':
                DB.execute("UPDATE providers SET enabled=0 WHERE user_id=? AND kind='ollama' AND id<>?", (user['id'], pid))
            # Only model-level zero prices are stored as zero. Account quotas are not token prices.
            price = 0 if model.get('billing') in ('free', 'local') and data.kind in ('ollama', 'openrouter', 'zai') else None
            DB.execute('UPDATE providers SET api_key_enc=?,enabled=1,priority=?,last_error=NULL,input_price=?,output_price=? WHERE id=?',
                       (SEC.encrypt(key), 10 if data.kind == 'ollama' else 5, price, price, pid))
            ENGINE.health.record(pid, model['id'], success=True, latency_ms=latency)
        return {'provider': public_provider(require_owned(DB, 'providers', pid, user['id'])),
                'model': model, 'models': catalog_with_connections(models, user['id'], data.kind), 'message': 'Conexão testada e salva.'}
    except ProviderError as exc:
        # A listed model is not evidence of billing entitlement. Stop on credit errors
        # rather than probing other models with the same account.
        if data.kind == 'sambanova' and exc.category == 'credits':
            status = f' (HTTP {exc.http_status})' if exc.http_status else ''
            message = ('A SambaNova recusou o teste por falta de créditos/saldo ou '
                       'cobrança não habilitada' + status + '. '
                       'O catálogo não garante cota gratuita para sua conta. '
                       'Confira o plano e os créditos no painel da SambaNova.')
        else:
            # Never echo a key even if an upstream service includes it in an error.
            message = str(exc).replace(key, '[chave omitida]') if key else str(exc)
        raise HTTPException(422, message)


@app.post('/api/providers')
def add_provider(data:ProviderIn,user=Depends(current_user)):
    url = check_provider(data)
    data.model = data.model.strip()
    if not data.model: raise HTTPException(422, 'Informe o modelo.')
    pid=uid()
    with DB.lock, DB.conn:
        DB.conn.execute('BEGIN IMMEDIATE')
        reject_duplicate_model(user['id'], data.kind, data.model)
        DB.execute('''INSERT INTO providers(id,user_id,name,kind,base_url,model,api_key_enc,priority,enabled,input_price,output_price,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
          (pid,user['id'],data.name,data.kind,url,data.model,SEC.encrypt(data.api_key),data.priority,int(data.enabled),data.input_price,data.output_price,utcnow()))
    return public_provider(require_owned(DB,'providers',pid,user['id']))


@app.put('/api/providers/{pid}')
def update_provider(pid:str,data:ProviderIn,user=Depends(current_user)):
    previous = require_owned(DB,'providers',pid,user['id'])
    url = check_provider(data)
    data.model = data.model.strip()
    if not data.model: raise HTTPException(422, 'Informe o modelo.')
    key = SEC.encrypt(data.api_key) if data.api_key else previous['api_key_enc']
    with DB.lock, DB.conn:
        DB.conn.execute('BEGIN IMMEDIATE')
        reject_duplicate_model(user['id'], data.kind, data.model, exclude_id=pid)
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
    return DB.all('SELECT * FROM agents WHERE user_id=? ORDER BY created_at',(user['id'],))


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
    now=utcnow()
    DB.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(uid(),convo['id'],user['id'],'user',None,data.prompt,now))
    DB.execute('UPDATE conversations SET updated_at=?,title=? WHERE id=?',
       (now,data.prompt[:60] if convo['title']=='Nova conversa' else convo['title'],convo['id']))
    try:
        run_id=ENGINE.create_run(user['id'],data.conversation_id,data.prompt,data.mode,data.agent_ids,
                                 flow,data.budget_limit,idempotency)
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
