import asyncio
import hashlib
import ipaddress
import logging
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .database import Database, uid, utcnow
from .security import Security, password_hash, verify_password, require_owned
from .worker_checkpoint import checkpoint_summary
from .engine import (Engine, TEMPLATES, validate_flow,
                     suggested_default_specialty, recoverable_default_agents)
from .providers import DEFAULT_ENDPOINTS, ProviderError
from .agent_registry import suggested_agent_specialty
from . import chatgpt_plan
from .catalog import CATALOG, BY_KIND, discover_models, candidates
from .memory import search_history, SMALL_HISTORY_COUNT, PROJECT_HISTORY_COUNT
from .computer_access import local_only, policy as computer_policy, set_policy as set_computer_policy, request_action as computer_request_action, decide_action as computer_decide_action
from .workspace_tools import decide as decide_workspace_action
from .task_contract import (needs_workspace_tools, delivery_evidence,
                            resolve_continuation_prompt)
from .observability import request_context, correlation_id, log_event, duration_ms
from .run_policy import classify_task
from .ops import overview as ops_overview, audit as ops_audit, audit_history
from .auth_limits import ensure_allowed as allow_login, failed as fail_login, succeeded as login_ok
from .quotas import QuotaExceeded
from .sandbox_executor import status as sandbox_status
from .workspace_guard import binding_summary
from .organizations import (
    ensure_personal, membership, require_org, require_project, visible_projects,
    create_organization, set_member, remove_member, all_organizations, require_run_write)
from .live_preview import candidates as preview_candidates, start as start_preview, stop as stop_preview, info as preview_info, stop_all as stop_all_previews
from .token_usage import run_usage, usage_overview

from .runtime_config import validate_runtime, registration_allowed
validate_runtime()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('CENTRAL_DATA_DIR', ROOT/'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = Database(DATA_DIR/'central.sqlite3')
from .semantic_memory import preference as memory_preference
SEC = Security(DB, DATA_DIR)
ENGINE = Engine(DB, SEC)


async def knowledge_retention():
    from .knowledge import purge_expired
    while True:
        try:
            await asyncio.to_thread(purge_expired, DB)
        except Exception:
            log_event('knowledge_retention_failed', category='storage')
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app):
    # Multiple TestClient lifespans may use different asyncio loops.
    # Never await or cancel a task that belongs to a different loop.
    loop = asyncio.get_running_loop()
    ENGINE.shutting_down = False
    if ENGINE.job_mode == 'embedded':
        if ENGINE.dispatch_task and ENGINE.dispatch_task.get_loop() is not loop:
            ENGINE.dispatch_task = None
        ENGINE.resume_pending()
        ENGINE.start_dispatcher()
    own_dispatcher = (ENGINE.dispatch_task
                      if ENGINE.dispatch_task and ENGINE.dispatch_task.get_loop() is loop
                      else None)
    retention_task = asyncio.create_task(knowledge_retention())
    try:
        yield
    finally:
        retention_task.cancel()
        await asyncio.gather(retention_task, return_exceptions=True)
        ENGINE.shutting_down = True
        if own_dispatcher:
            own_dispatcher.cancel()
            await asyncio.gather(own_dispatcher, return_exceptions=True)
            if ENGINE.dispatch_task is own_dispatcher:
                ENGINE.dispatch_task = None
        stop_all_previews()
        pending = [task for task in ENGINE.running.values()
                   if task.get_loop() is loop and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        from .browser_mcp import close_all
        await close_all()
        ENGINE.shutting_down = False


app = FastAPI(title='Central de Trabalhadores IA', version='0.2.0', lifespan=lifespan)

class RedactChatGPTOAuthAccessLog(logging.Filter):
    def filter(self, record):
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and '/api/chatgpt-plan/callback' in args[2]:
            safe = list(args)
            safe[2] = '/api/chatgpt-plan/callback?[redacted]'
            record.args = tuple(safe)
        return True


logging.getLogger('uvicorn.access').addFilter(RedactChatGPTOAuthAccessLog())

@app.middleware('http')
async def trace_requests(request: Request, call_next):
    # IDs are for correlation only; do not treat client-supplied values as auth.
    rid = correlation_id(request.headers.get('x-request-id'))
    token = request_context.set(rid)
    started = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers['X-Request-ID'] = rid
        return response
    finally:
        route = request.scope.get('route')
        route_name = getattr(route, 'path', None)
        # URL path can contain identifiers or sensitive query parameters. Do not log it.
        safe_route = route_name or 'unmatched'
        log_event('http_request', method=request.method, route=safe_route,
                  http_status=status, duration_ms=duration_ms(started))
        request_context.reset(token)


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
    if not registration_allowed():
        raise HTTPException(403, 'Cadastro público desativado pelo administrador.')
    email = data.email.strip().lower()
    if '@' not in email: raise HTTPException(422,'E-mail inválido.')
    if DB.one('SELECT id FROM users WHERE email=?',(email,)):
        raise HTTPException(409,'E-mail já cadastrado.')
    user_id = uid()
    DB.execute('INSERT INTO users VALUES(?,?,?,?)', (user_id,email,password_hash(data.password),utcnow()))
    ensure_personal(DB, user_id)
    for name,specialty,instructions,avatar in TEMPLATES:
        DB.execute('''INSERT INTO agents(id,user_id,name,specialty,instructions,avatar,created_at)
          VALUES(?,?,?,?,?,?,?)''', (uid(),user_id,name,specialty,instructions,avatar,utcnow()))
    token = SEC.create_session(user_id)
    response.set_cookie('central_session',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=604800)
    return {'id':user_id,'email':email}


@app.post('/api/login')
def login(data: Credentials, request: Request, response: Response):
    require_csrf(request)
    email = data.email.strip().lower()
    allow_login(DB, email)
    row = DB.one('SELECT * FROM users WHERE email=?',(email,))
    if not row or not verify_password(data.password,row['password_hash']):
        fail_login(DB, email)
        raise HTTPException(401,'E-mail ou senha incorretos.')
    login_ok(DB, email)
    token = SEC.create_session(row['id'])
    response.set_cookie('central_session',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=604800)
    return {'id':row['id'],'email':row['email']}


@app.post('/api/logout')
def logout(request:Request,response:Response,user=Depends(current_user)):
    import hashlib
    stop_preview(user['id'])
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
    return {k:row[k] for k in ('id','name','kind','base_url','model','priority','enabled','input_price','output_price','last_error','created_at')} | {'has_key':bool(row['api_key_enc'] or row.get('chatgpt_connection_id')), 'auth_type':'codex_cli' if row['kind'] == 'codex_cli' else 'chatgpt_plan' if row.get('chatgpt_connection_id') else 'api_key', 'health':health}


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
    return CATALOG + [{
        'kind': 'openai_chatgpt', 'name': 'ChatGPT (assinatura)',
        'access': 'Plano ChatGPT elegível',
        'note': 'Conecte com Sign in with ChatGPT e autorize explicitamente o uso elegível do plano. Modelos exibidos conforme sua conta. Isso não usa a API paga por chave.',
        'keys_url': 'https://chatgpt.com/', 'source_url': 'https://developers.openai.com/siwc/token-sharing-open-source',
        'checked_at': '2026-10-25', 'quick': True,
    }]


def _oauth_callback_page(success, message):
    import html
    safe = html.escape(message)
    message_json = json.dumps(message, ensure_ascii=False).replace('<', '\\u003c')
    ok = 'true' if success else 'false'
    return HTMLResponse('<!doctype html><meta charset="utf-8"><title>ChatGPT conectado</title>'
        '<main style="font:16px system-ui;max-width:38rem;margin:12vh auto;padding:2rem">'
        '<h1>' + ('Conexão concluída' if success else 'Não foi possível conectar') + '</h1>'
        '<p>' + safe + '</p><p>Você pode fechar esta janela e voltar à Central.</p></main>'
        '<script>history.replaceState(null,"",location.pathname);if(window.opener){window.opener.postMessage({type:"central-chatgpt-oauth",ok:' + ok + ',message:' + message_json + '},String.fromCharCode(42));window.close()}</script>',
        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


@app.post('/api/chatgpt-plan/authorize')
def chatgpt_plan_authorize(request: Request, user=Depends(current_user)):
    try:
        local_client = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local_client = False
    if not local_client or request.url.scheme != 'http' or request.url.hostname not in ('127.0.0.1', 'localhost', '::1') or not request.url.port:
        raise HTTPException(400, 'A conexão com o plano ChatGPT só pode ser iniciada pela Central local.')
    connection = DB.one('SELECT * FROM chatgpt_plan_connections WHERE user_id=?', (user['id'],))
    setting = DB.one("SELECT value FROM app_settings WHERE key='chatgpt_plan_host_id'")
    if setting:
        host_id = setting['value']
    else:
        host_id = 'urn:uuid:' + str(__import__('uuid').uuid4())
        DB.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('chatgpt_plan_host_id',?)", (host_id,))
        host_id = DB.one("SELECT value FROM app_settings WHERE key='chatgpt_plan_host_id'")['value']
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = chatgpt_plan.pkce_pair()
    redirect_uri = f'http://127.0.0.1:{request.url.port}/api/chatgpt-plan/callback'
    client_id = connection['client_id'] if connection else 'dynamic_agent_client'
    DB.execute('DELETE FROM chatgpt_plan_pending WHERE expires_at<=?', (utcnow(),))
    DB.execute('INSERT INTO chatgpt_plan_pending VALUES(?,?,?,?,?,?,?)',
        (hashlib.sha256(state.encode()).hexdigest(), user['id'], SEC.encrypt(nonce), SEC.encrypt(verifier), redirect_uri,
         connection['client_id'] if connection else None,
         (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()))
    credentials = json.loads(SEC.decrypt(connection['credentials_enc'])) if connection else {}
    url = chatgpt_plan.authorization_url(
        client_id=client_id, host_id=host_id, app_name='Central de Trabalhadores IA',
        redirect_uri=redirect_uri, state=state, nonce=nonce, challenge=challenge,
        login_hint=connection['email'] if connection else None)
    return {'authorization_url': url}


@app.get('/api/chatgpt-plan/callback', include_in_schema=False)
async def chatgpt_plan_callback(request: Request):
    try:
        if not ipaddress.ip_address(request.client.host).is_loopback or request.url.hostname not in ('127.0.0.1', 'localhost', '::1'):
            return _oauth_callback_page(False, 'O retorno deve acontecer na Central local que iniciou a conexão.')
    except (ValueError, AttributeError):
        return _oauth_callback_page(False, 'O retorno deve acontecer na Central local que iniciou a conexão.')
    state = request.query_params.get('state', '')
    state_hash = hashlib.sha256(state.encode()).hexdigest() if state else ''
    pending = DB.one('SELECT * FROM chatgpt_plan_pending WHERE state_hash=? AND expires_at>?', (state_hash, utcnow()))
    if not pending:
        return _oauth_callback_page(False, 'A tentativa expirou ou não corresponde à autorização iniciada. Volte à Central e tente novamente.')
    DB.execute('DELETE FROM chatgpt_plan_pending WHERE state_hash=?', (state_hash,))
    if request.query_params.get('error'):
        return _oauth_callback_page(False, 'A autorização foi cancelada ou recusada.')
    code = request.query_params.get('code', '')
    issued_client_id = request.query_params.get('client_id') or pending['client_id']
    if not code or not issued_client_id or (pending['client_id'] and issued_client_id != pending['client_id']):
        return _oauth_callback_page(False, 'A resposta de autorização estava incompleta. Tente conectar novamente.')
    try:
        result = await chatgpt_plan.exchange_code(code=code, client_id=issued_client_id,
            verifier=SEC.decrypt(pending['verifier']), redirect_uri=pending['redirect_uri'])
        scopes = str(result.get('scope') or '').split()
        if chatgpt_plan.REQUIRED_SCOPE not in scopes or 'resource.invoke' not in scopes:
            raise ProviderError('authentication', 'A permissão de uso do plano ChatGPT não foi concedida.', False)
        claims = await chatgpt_plan.validate_id_token(result['id_token'], client_id=issued_client_id, nonce=SEC.decrypt(pending['nonce']))
        if not claims.get('email') or claims.get('email_verified') is not True:
            raise ProviderError('authentication', 'A identidade retornada não contém um e-mail verificado.', False)
        previous = DB.one('SELECT * FROM chatgpt_plan_connections WHERE user_id=?', (pending['user_id'],))
        if previous and previous['subject'] != claims['sub']:
            raise ProviderError('authentication', 'Desconecte a conta ChatGPT atual antes de conectar outra conta.', False)
        now = utcnow()
        credentials = {'access_token': result['access_token'], 'refresh_token': result.get('refresh_token', ''),
            'expires_at': int(time.time()) + int(result.get('expires_in', 3600)),
            'scopes': ' '.join(scopes), 'client_id': issued_client_id}
        if not credentials['refresh_token']:
            raise ProviderError('authentication', 'A OpenAI não retornou credencial renovável. Tente novamente autorizando a sessão.', False)
        encrypted = SEC.encrypt(json.dumps(credentials, separators=(',', ':')))
        if previous:
            DB.execute('UPDATE chatgpt_plan_connections SET client_id=?,email=?,scopes=?,credentials_enc=?,updated_at=? WHERE id=? AND user_id=?',
                (issued_client_id, claims['email'], ' '.join(scopes), encrypted, now, previous['id'], pending['user_id']))
        else:
            DB.execute('INSERT INTO chatgpt_plan_connections VALUES(?,?,?,?,?,?,?,?,?)',
                (uid(), pending['user_id'], issued_client_id, claims['sub'], claims['email'], ' '.join(scopes), encrypted, now, now))
        return _oauth_callback_page(True, 'Conta ChatGPT conectada. A Central exibirá somente os modelos listados para essa conta.')
    except ProviderError as exc:
        return _oauth_callback_page(False, str(exc))
    except Exception:
        return _oauth_callback_page(False, 'Não foi possível validar a autorização. Nenhum token foi exibido; tente conectar novamente.')


async def chatgpt_plan_credentials(user_id):
    row = DB.one('SELECT * FROM chatgpt_plan_connections WHERE user_id=?', (user_id,))
    if not row:
        raise HTTPException(409, 'Conecte uma conta ChatGPT antes de selecionar modelos.')
    try:
        credentials = await chatgpt_plan.stored_credentials(DB, SEC, row['id'])
        return row, credentials
    except ProviderError as exc:
        raise HTTPException(401, str(exc))


@app.get('/api/chatgpt-plan/status')
def chatgpt_plan_status(user=Depends(current_user)):
    row = DB.one('SELECT id,email,scopes,created_at,updated_at FROM chatgpt_plan_connections WHERE user_id=?', (user['id'],))
    return {'connected': bool(row), 'connection': row}


@app.get('/api/chatgpt-plan/models')
async def chatgpt_plan_models(user=Depends(current_user)):
    _, credentials = await chatgpt_plan_credentials(user['id'])
    try:
        return {'models': await chatgpt_plan.available_models(credentials['access_token'])}
    except ProviderError as exc:
        raise HTTPException(422, str(exc))


class ChatGPTPlanProviderIn(BaseModel):
    model: str = Field(min_length=1, max_length=120)


@app.post('/api/chatgpt-plan/providers')
async def add_chatgpt_plan_provider(data: ChatGPTPlanProviderIn, request: Request, user=Depends(current_user)):
    require_csrf(request)
    try:
        connection, credentials = await chatgpt_plan_credentials(user['id'])
        models = await chatgpt_plan.available_models(credentials['access_token'])
    except ProviderError as exc:
        raise HTTPException(422, str(exc))
    model = next((item for item in models if item['id'] == data.model), None)
    if not model:
        raise HTTPException(422, 'Esse modelo não consta no catálogo autorizado para a conta ChatGPT conectada.')
    reject_duplicate_model(user['id'], 'openai_chatgpt', data.model)
    started = time.monotonic()
    try:
        answer = ''.join([part async for part in chatgpt_plan.stream_response(credentials['access_token'], data.model,
            'Responda somente OK.', [{'role': 'user', 'content': 'Responda somente OK.'}], timeout=45)])
        if not answer.strip():
            raise ProviderError('response', 'O modelo não retornou texto.', True)
    except ProviderError as exc:
        raise HTTPException(422, str(exc))
    provider_id = uid()
    with DB.lock, DB.conn:
        DB.conn.execute('BEGIN IMMEDIATE')
        reject_duplicate_model(user['id'], 'openai_chatgpt', data.model)
        DB.execute('''INSERT INTO providers(id,user_id,name,kind,base_url,model,api_key_enc,priority,enabled,
            chatgpt_connection_id,created_at) VALUES(?,?,?,?,?,?,NULL,5,1,?,?)''',
            (provider_id, user['id'], 'ChatGPT (assinatura)', 'openai_chatgpt', chatgpt_plan.API_BASE,
             data.model, connection['id'], utcnow()))
    ENGINE.health.record(provider_id, data.model, success=True, latency_ms=(time.monotonic()-started)*1000)
    return {'provider': public_provider(require_owned(DB, 'providers', provider_id, user['id'])), 'model': model}


@app.delete('/api/chatgpt-plan/connection')
async def revoke_chatgpt_plan_connection(request: Request, user=Depends(current_user)):
    require_csrf(request)
    connection = DB.one('SELECT * FROM chatgpt_plan_connections WHERE user_id=?', (user['id'],))
    remote_revoked = False
    if connection:
        try:
            credentials = json.loads(SEC.decrypt(connection['credentials_enc']))
            remote_revoked = await chatgpt_plan.revoke_session(credentials)
        except Exception:
            remote_revoked = False
        provider_ids = [row['id'] for row in DB.all('SELECT id FROM providers WHERE chatgpt_connection_id=? AND user_id=?', (connection['id'], user['id']))]
        for provider_id in provider_ids:
            DB.execute('UPDATE agents SET provider_id=NULL,model=NULL WHERE provider_id=? AND user_id=?', (provider_id, user['id']))
            DB.execute('DELETE FROM providers WHERE id=? AND user_id=?', (provider_id, user['id']))
        DB.execute('DELETE FROM chatgpt_plan_connections WHERE id=? AND user_id=?', (connection['id'], user['id']))
    return {'ok': True, 'remote_revoked': remote_revoked}

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


def connection_error_message(kind, key, exc):
    """Return a bounded diagnostic without leaking the API key to the browser."""
    if kind == 'sambanova' and exc.category == 'credits':
        status = f' (HTTP {exc.http_status})' if exc.http_status else ''
        return ('A SambaNova recusou o teste por falta de créditos/saldo ou '
                'cobrança não habilitada' + status + '. '
                'O catálogo não garante cota gratuita para sua conta. '
                'Confira o plano e os créditos no painel da SambaNova.')
    message = str(exc).replace(key, '[chave omitida]') if key else str(exc)
    return message.replace('\r', ' ').replace('\n', ' ')[:360]


async def connection_events(data, user, key):
    """One connection engine shared by JSON and real-time SSE endpoints.

    Events are transient and belong only to this authenticated request.
    No keys, prompt text, or upstream headers are included in the trace.
    """
    models = catalog_with_connections(await discover_models(data.kind, key), user['id'], data.kind)
    options = candidates([m for m in models if not m['connected']], data.kind, data.model)
    if data.model and not any(m['id'] == data.model for m in models):
        raise ProviderError('catalog', 'Modelo não encontrado no catálogo de chat do provedor.')
    if not options and any(m['eligible'] and m['connected'] for m in models) and not data.model:
        raise HTTPException(409, 'Todos os modelos elegíveis deste provedor já estão cadastrados. Use Editar para gerenciar suas conexões.')
    if not options:
        raise ProviderError('catalog', 'Nenhum modelo de chat elegível encontrado. Confira o plano e o catálogo; nenhum modelo pago será selecionado como alternativa.')

    provider = {'kind': data.kind, 'base_url': DEFAULT_ENDPOINTS[data.kind]}
    attempts = options[:3]
    failures = []
    for index, model in enumerate(attempts):
        yield {'type': 'testing', 'model_id': model['id'], 'model_name': model['name'],
               'position': index + 1, 'total': len(attempts)}
        started = time.monotonic()
        stream = ENGINE.client.stream(provider, key, model['id'], 'Seja conciso.',
                                      [{'role': 'user', 'content': 'Responda somente OK.'}])
        failed = None
        try:
            answer = ''
            async for part in stream:
                answer += part
                if answer.strip():
                    break
            if not answer.strip():
                raise ProviderError('response', 'O modelo não retornou texto.', True)
        except ProviderError as exc:
            failed = exc
        finally:
            await stream.aclose()

        latency = (time.monotonic() - started) * 1000
        if failed:
            stop = failed.category in ('authentication', 'credits')
            next_model = attempts[index + 1] if not stop and index + 1 < len(attempts) else None
            yield {'type': 'failed', 'model_id': model['id'], 'model_name': model['name'],
                   'category': failed.category, 'http_status': failed.http_status,
                   'message': connection_error_message(data.kind, key, failed),
                   'next_model': {'id': next_model['id'], 'name': next_model['name']} if next_model else None}
            if stop:
                raise failed
            failures.append(failed.category)
            continue

        yield {'type': 'passed', 'model_id': model['id'], 'model_name': model['name'],
               'latency_ms': round(latency)}
        break
    else:
        raise ProviderError('validation', 'Os modelos encontrados não responderam ao teste (' +
                            ', '.join(failures) + '). Nenhuma conexão foi alterada. Tente novamente.')

    # Recheck inside the write transaction to cover simultaneous connections.
    with DB.lock, DB.conn:
        DB.conn.execute('BEGIN IMMEDIATE')
        reject_duplicate_model(user['id'], data.kind, model['id'])
        pid = uid()
        DB.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) VALUES(?,?,?,?,?,?,?)',
                   (pid, user['id'], BY_KIND[data.kind]['name'], data.kind, provider['base_url'], model['id'], utcnow()))
        if data.kind == 'ollama':
            DB.execute("UPDATE providers SET enabled=0 WHERE user_id=? AND kind='ollama' AND id<>?", (user['id'], pid))
        # Free-tier quota is not necessarily a zero token price.
        price = 0 if model.get('billing') in ('free', 'local') and data.kind in ('ollama', 'openrouter', 'zai') else None
        DB.execute('UPDATE providers SET api_key_enc=?,enabled=1,priority=?,last_error=NULL,input_price=?,output_price=? WHERE id=?',
                   (SEC.encrypt(key), 10 if data.kind == 'ollama' else 5, price, price, pid))
        ENGINE.health.record(pid, model['id'], success=True, latency_ms=latency)
    yield {'type': 'connected', 'provider': public_provider(require_owned(DB, 'providers', pid, user['id'])),
           'model': model, 'models': catalog_with_connections(models, user['id'], data.kind),
           'message': 'Conexão testada e salva.'}


def prepare_connection(data, request, user):
    require_csrf(request)
    key = quick_key(data, user)
    if data.model:
        reject_duplicate_model(user['id'], data.kind, data.model)
    return key


@app.post('/api/provider-catalog/connect')
async def connect_provider(data: QuickProviderIn, request: Request, user=Depends(current_user)):
    """Backward-compatible JSON API, also used by existing tests and clients."""
    key = prepare_connection(data, request, user)
    try:
        async for event in connection_events(data, user, key):
            if event['type'] == 'connected':
                return {k: v for k, v in event.items() if k != 'type'}
    except ProviderError as exc:
        raise HTTPException(422, connection_error_message(data.kind, key, exc))


@app.post('/api/provider-catalog/connect/stream')
async def connect_provider_stream(data: QuickProviderIn, request: Request, user=Depends(current_user)):
    """Authenticated SSE-over-POST stream for the catalogue's live attempt history."""
    key = prepare_connection(data, request, user)

    async def events():
        try:
            async for event in connection_events(data, user, key):
                yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
        except ProviderError as exc:
            message = connection_error_message(data.kind, key, exc)
            yield 'data: ' + json.dumps({'type': 'error', 'message': message,
                                           'category': exc.category}, ensure_ascii=False) + '\n\n'
        except HTTPException as exc:
            yield 'data: ' + json.dumps({'type': 'error', 'message': str(exc.detail)[:360]},
                                           ensure_ascii=False) + '\n\n'

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


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
    if previous['kind'] == 'codex_cli':
        raise HTTPException(422, 'Gerencie o Codex pelo painel de runtime local.')
    if previous.get('chatgpt_connection_id'):
        raise HTTPException(422, 'Gerencie modelos ChatGPT pela conexão da conta, não pela configuração manual de chave API.')
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
async def test_provider(pid:str,request:Request,user=Depends(current_user)):
    p = require_owned(DB,'providers',pid,user['id'])
    if p['kind'] == 'codex_cli':
        require_csrf(request)
        local_only(request)
        from .codex_runtime import probe
        result = await asyncio.to_thread(probe)
        connected = result['status'] == 'ok' and result['auth_type'] == 'chatgpt'
        return {'ok': connected, 'generation_tested': False,
                'response': 'CLI conectado. Acesso ao modelo é confirmado na execução da tarefa.' if connected else '',
                'error': '' if connected else 'Codex local indisponível: ' + result['status']}
    allowed, half_open = ENGINE.health.acquire(pid, p['model'])
    if not allowed:
        detail = ENGINE.health.detail(pid, p['model'])
        return {'ok':False,'category':'suspended',
                'error':f"Modelo temporariamente suspenso. Aguarde {detail['remaining_seconds']} segundos."}
    started = time.monotonic()
    try:
        chunks=[]
        credential = SEC.decrypt(p['api_key_enc'])
        if p['kind'] == 'openai_chatgpt':
            stored = await chatgpt_plan.stored_credentials(DB, SEC, p.get('chatgpt_connection_id'))
            credential = stored['access_token']
        async for part in ENGINE.client.stream(p,credential,p['model'],
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



class ComputerAccessSettingsIn(BaseModel):
    mode: str = Field(default='blocked', max_length=12)
    folder: str = Field(default='', max_length=1024)


class ComputerAccessActionIn(BaseModel):
    action: str = Field(max_length=12)
    relative_path: str = Field(default='', max_length=300)


class ComputerAccessDecisionIn(BaseModel):
    approve: bool


@app.get('/api/computer-access')
def computer_access_settings(request: Request, user=Depends(current_user)):
    local_only(request)
    return computer_policy(DB, user['id'])


@app.get('/api/computer-access/default-folder')
def computer_access_default_folder(request: Request, user=Depends(current_user)):
    local_only(request)
    # Suggest only; never grant a folder without an explicit save.
    return {'folder': str(ROOT.resolve())}


@app.put('/api/computer-access')
def update_computer_access(data: ComputerAccessSettingsIn, request: Request,
                           user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    result = set_computer_policy(DB, user['id'], data.mode, data.folder)
    ops_audit(DB,user['id'],'workspace_policy_changed','workspace',outcome=result['mode'])
    # A preview process must not outlive a revoked or changed workspace grant.
    stop_preview(user['id'])
    return result


@app.post('/api/computer-access/action')
def computer_access_action(data: ComputerAccessActionIn, request: Request,
                           user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    return computer_request_action(DB, user['id'], data.action, data.relative_path)


@app.post('/api/computer-access/approvals/{approval_id}/decision')
def computer_access_decision(approval_id: str, data: ComputerAccessDecisionIn,
                             request: Request, user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    outcome = computer_decide_action(DB, user['id'], approval_id, data.approve)
    ops_audit(DB,user['id'],'computer_action_decided','approval',approval_id,
              outcome='approved' if data.approve else 'denied')
    return outcome


class AssignSpecialtiesIn(BaseModel):
    apply: bool = False


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
    agents = DB.all('SELECT * FROM agents WHERE user_id=? ORDER BY created_at',(user['id'],))
    return [dict(agent, suggested_specialty=suggested_default_specialty(agent))
            for agent in agents]


@app.post('/api/agents/restore-default-specialties')
def restore_default_specialties(request: Request, user=Depends(current_user)):
    """User-approved repair; preserve per-agent models, keys, settings and instructions."""
    require_csrf(request)
    agents = DB.all('SELECT * FROM agents WHERE user_id=? ORDER BY created_at', (user['id'],))
    candidates = recoverable_default_agents(agents)
    # Re-check each original role in SQL. No custom/renamed/re-prompted agent is touched.
    repaired = []
    for agent in candidates:
        count = DB.execute(
            'UPDATE agents SET specialty=? WHERE id=? AND user_id=? AND specialty=?',
            (agent['suggested_specialty'], agent['id'], user['id'], agent['specialty']))
        if count:
            repaired.append({'id': agent['id'], 'name': agent['name'],
                             'old_specialty': agent['specialty'],
                             'new_specialty': agent['suggested_specialty']})
    return {'repaired_count': len(repaired), 'repaired': repaired}


@app.post('/api/agents/assign-specialties')
def assign_agent_specialties(data: AssignSpecialtiesIn, request: Request, user=Depends(current_user)):
    """Preview or apply confident per-user role assignments without changing agent setup."""
    require_csrf(request)
    agents = DB.all('SELECT * FROM agents WHERE user_id=? ORDER BY created_at', (user['id'],))
    suggestions = []
    unresolved = 0
    for agent in agents:
        specialty = suggested_agent_specialty(agent)
        if specialty is None:
            unresolved += 1
        elif specialty != agent['specialty']:
            suggestions.append({
                'id': agent['id'], 'name': agent['name'],
                'old_specialty': agent['specialty'], 'new_specialty': specialty,
            })
    if data.apply:
        applied = []
        for item in suggestions:
            count = DB.execute(
                'UPDATE agents SET specialty=? WHERE id=? AND user_id=? AND specialty=?',
                (item['new_specialty'], item['id'], user['id'], item['old_specialty']))
            if count:
                applied.append(item)
        suggestions = applied
    return {
        'applied': data.apply, 'assigned_count': len(suggestions),
        'unresolved_count': unresolved, 'assignments': suggestions,
    }


@app.post('/api/agents')
def add_agent(data:AgentIn,user=Depends(current_user)):
    if data.provider_id:
        selected_provider = require_owned(DB,'providers',data.provider_id,user['id'])
        if selected_provider['kind'] == 'openai_chatgpt': data.model = selected_provider['model']
    aid=uid()
    DB.execute('''INSERT INTO agents(id,user_id,name,specialty,instructions,avatar,provider_id,model,enabled,max_concurrency,created_at)
       VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (aid,user['id'],data.name,data.specialty,data.instructions,data.avatar,
       data.provider_id,data.model,int(data.enabled),data.max_concurrency,utcnow()))
    return require_owned(DB,'agents',aid,user['id'])


@app.put('/api/agents/{aid}')
def edit_agent(aid:str,data:AgentIn,user=Depends(current_user)):
    require_owned(DB,'agents',aid,user['id'])
    if data.provider_id:
        selected_provider = require_owned(DB,'providers',data.provider_id,user['id'])
        if selected_provider['kind'] == 'openai_chatgpt': data.model = selected_provider['model']
    DB.execute('''UPDATE agents SET name=?,specialty=?,instructions=?,avatar=?,provider_id=?,model=?,enabled=?,max_concurrency=? WHERE id=?''',
    (data.name,data.specialty,data.instructions,data.avatar,data.provider_id,data.model,int(data.enabled),data.max_concurrency,aid))
    return require_owned(DB,'agents',aid,user['id'])


@app.delete('/api/agents/{aid}')
def remove_agent(aid:str,user=Depends(current_user)):
    require_owned(DB,'agents',aid,user['id'])
    # Keep historical step references and do not destroy an agent used in existing jobs.
    DB.execute('UPDATE agents SET enabled=0 WHERE id=?',(aid,))
    return {'ok':True}


class OrganizationIn(BaseModel):
    name: str = Field(min_length=2,max_length=90)


class MemberIn(BaseModel):
    email: str = Field(min_length=5,max_length=180)
    role: str = Field(default='operator')


class OrgLimitsIn(BaseModel):
    daily_run_limit: int = Field(ge=1,le=100000)
    active_run_limit: int = Field(ge=1,le=100000)
    estimated_budget_usd: float | None = Field(default=None,ge=0)


@app.get('/api/organizations')
def get_organizations(user=Depends(current_user)):
    ensure_personal(DB,user['id'])
    return all_organizations(DB,user['id'])


@app.post('/api/organizations')
def add_organization(data:OrganizationIn,request:Request,user=Depends(current_user)):
    require_csrf(request)
    oid=create_organization(DB,user['id'],data.name.strip())
    ops_audit(DB,user['id'],'organization_created','organization',oid)
    return require_org(DB,oid,user['id'])


@app.get('/api/organizations/{oid}/members')
def get_organization_members(oid:str,user=Depends(current_user)):
    require_org(DB,oid,user['id'])
    return DB.all(
        """SELECT u.id,u.email,m.role FROM organization_members m
           JOIN users u ON u.id=m.user_id
           WHERE m.organization_id=? ORDER BY m.created_at""", (oid,))


@app.put('/api/organizations/{oid}/members')
def upsert_organization_member(oid:str,data:MemberIn,request:Request,
                               user=Depends(current_user)):
    require_csrf(request)
    require_org(DB,oid,user['id'],admin=True)
    member=DB.one('SELECT id FROM users WHERE email=?',(data.email.strip().lower(),))
    if not member:
        raise HTTPException(404,'Conta não encontrada. O usuário precisa se cadastrar primeiro.')
    role=set_member(DB,oid,user['id'],member['id'],data.role)
    ops_audit(DB,user['id'],'organization_member_changed','organization',oid)
    return {'user_id':member['id'],'role':role}


@app.delete('/api/organizations/{oid}/members/{member_id}')
def delete_organization_member(oid:str,member_id:str,request:Request,
                               user=Depends(current_user)):
    require_csrf(request)
    remove_member(DB,oid,user['id'],member_id)
    ops_audit(DB,user['id'],'organization_member_removed','organization',oid)
    return {'ok':True}


@app.put('/api/organizations/{oid}/limits')
def update_organization_limits(oid:str,data:OrgLimitsIn,request:Request,
                               user=Depends(current_user)):
    require_csrf(request)
    require_org(DB,oid,user['id'],admin=True)
    DB.execute(
        'UPDATE organizations SET daily_run_limit=?,active_run_limit=?,'
        'estimated_budget_usd=? WHERE id=?',
        (data.daily_run_limit,data.active_run_limit,data.estimated_budget_usd,oid))
    ops_audit(DB,user['id'],'organization_limits_changed','organization',oid)
    return require_org(DB,oid,user['id'])


class HostCommandsIn(BaseModel):
    enabled: bool
    confirmation: str = Field(default='',max_length=90)


@app.put('/api/organizations/{oid}/host-commands')
def change_host_commands(oid:str,data:HostCommandsIn,request:Request,
                         user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    member=require_org(DB,oid,user['id'],admin=True)
    if member['is_personal']:
        raise HTTPException(409,'O espaço pessoal já utiliza as permissões do computador.')
    if data.enabled and data.confirmation != 'AUTORIZO EXECUCAO LOCAL':
        raise HTTPException(
            422,'Para habilitar, digite exatamente AUTORIZO EXECUCAO LOCAL. '
                'Comandos npm/pip podem executar código fora da pasta autorizada.')
    DB.execute('UPDATE organizations SET host_commands_enabled=? WHERE id=?',
               (int(data.enabled),oid))
    ops_audit(DB,user['id'],'org_host_commands_changed','organization',oid,
              outcome='enabled' if data.enabled else 'disabled')
    return {'organization_id':oid,'enabled':data.enabled}


@app.get('/api/organizations/{oid}/usage')
def organization_usage(oid:str,user=Depends(current_user)):
    org=require_org(DB,oid,user['id'])
    from datetime import datetime,timedelta,timezone
    since=(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat()
    data=DB.one(
        """SELECT COUNT(*) AS daily,
           COALESCE(SUM(CASE WHEN r.status IN
              ('queued','running','awaiting_approval') THEN 1 ELSE 0 END),0) AS active,
           COALESCE(SUM(r.total_cost),0) AS estimated_spend
           FROM organization_runs x JOIN runs r ON r.id=x.run_id
           WHERE x.organization_id=? AND r.created_at>=?""",
        (oid,since))
    total=DB.one(
        """SELECT COALESCE(SUM(r.total_cost),0) AS cost,
                  COALESCE(SUM(CASE WHEN r.status IN
                    ('queued','running','awaiting_approval') THEN 1 ELSE 0 END),0) AS active
           FROM organization_runs x JOIN runs r ON r.id=x.run_id
           WHERE x.organization_id=?""",(oid,))
    return {'organization_id':oid,'role':org['role'],
            'daily_runs':data['daily'],'active_runs':total['active'],
            'estimated_spend_usd':total['cost'],
            'limits':{'daily_run_limit':org['daily_run_limit'],
                      'active_run_limit':org['active_run_limit'],
                      'estimated_budget_usd':org['estimated_budget_usd']}}


class ProjectIn(BaseModel):
    name:str = Field(min_length=1,max_length=90)
    description:str = Field(default='',max_length=2000)
    organization_id: str | None = None


@app.get('/api/projects')
def projects(user=Depends(current_user)):
    return visible_projects(DB,user['id'])


@app.post('/api/projects')
def add_project(data:ProjectIn,user=Depends(current_user)):
    org_id = data.organization_id or ensure_personal(DB,user['id'])
    require_org(DB,org_id,user['id'],write=True)
    pid=uid()
    with DB.lock, DB.conn:
        DB.conn.execute(
            'INSERT INTO projects(id,user_id,name,description,created_at) VALUES(?,?,?,?,?)',
            (pid,user['id'],data.name,data.description,utcnow()))
        DB.conn.execute(
            'INSERT INTO organization_projects(project_id,organization_id) VALUES(?,?)',
            (pid,org_id))
    ops_audit(DB,user['id'],'project_created','organization',org_id)
    return require_project(DB,pid,user['id'])

class ProjectMemoryIn(BaseModel):
    notes: str = Field(default='', max_length=8000)


class ProjectBrowserSessionIn(BaseModel):
    mode: Literal['run_isolated', 'project_persistent']


@app.get('/api/projects/{pid}/browser-session')
def project_browser_session(pid: str, user=Depends(current_user)):
    project = require_project(DB, pid, user['id'])
    setting = DB.one(
        'SELECT mode FROM project_browser_settings WHERE project_id=?', (pid,))
    return {'project_id': project['id'],
            'mode': setting['mode'] if setting else 'run_isolated'}


@app.put('/api/projects/{pid}/browser-session')
def save_project_browser_session(pid: str, data: ProjectBrowserSessionIn,
                                 request: Request, user=Depends(current_user)):
    require_csrf(request)
    require_project(DB, pid, user['id'], write=True)
    DB.execute(
        'INSERT INTO project_browser_settings(project_id,mode,updated_at) '
        'VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET '
        'mode=excluded.mode,updated_at=excluded.updated_at',
        (pid, data.mode, utcnow()))
    return {'project_id': pid, 'mode': data.mode}


@app.delete('/api/projects/{pid}/browser-session')
def clear_project_browser_session(pid: str, request: Request,
                                  user=Depends(current_user)):
    require_csrf(request)
    require_project(DB, pid, user['id'], write=True)
    from .browser_mcp import clear_project_profile
    return clear_project_profile(DB, user['id'], pid)


@app.put('/api/projects/{pid}/memory')
def save_project_memory(pid: str, data: ProjectMemoryIn, request: Request, user=Depends(current_user)):
    require_csrf(request)
    require_project(DB,pid,user['id'],write=True)
    DB.execute('UPDATE projects SET memory_notes=? WHERE id=?',
               (data.notes,pid))
    return require_project(DB,pid,user['id'])



class ConversationIn(BaseModel):
    title:str = Field(default='Nova conversa',max_length=140)
    project_id:str | None = None


@app.get('/api/conversations')
def conversations(user=Depends(current_user)):
    # The sidebar is bounded; older conversations remain saved and searchable.
    return DB.all(
        """SELECT c.* FROM conversations c
           LEFT JOIN organization_projects op ON op.project_id=c.project_id
           WHERE c.user_id=? AND (c.project_id IS NULL
             OR (op.organization_id IS NULL AND EXISTS
                 (SELECT 1 FROM projects p WHERE p.id=c.project_id AND p.user_id=?))
             OR op.organization_id IN
                (SELECT organization_id FROM organization_members WHERE user_id=?))
           ORDER BY c.updated_at DESC LIMIT 300""",
        (user['id'],user['id'],user['id']))


@app.get('/api/conversations/search')
def search_conversations(q: str = '', project_id: str | None = None,
                         scope: str = 'project', user=Depends(current_user)):
    if scope not in ('project', 'all'):
        raise HTTPException(422, 'Escopo de busca inválido.')
    if len(q.strip()) < 3 or len(q) > 140:
        raise HTTPException(422, 'Use entre 3 e 140 caracteres para buscar.')
    if project_id:
        require_project(DB,project_id,user['id'])
    return search_history(DB, user['id'], q, project_id, all_projects=(scope == 'all'))


@app.get('/api/conversations/{cid}')
def conversation_detail(cid: str, user=Depends(current_user)):
    return require_owned(DB, 'conversations', cid, user['id'])


@app.post('/api/conversations')
def new_conversation(data:ConversationIn,user=Depends(current_user)):
    if data.project_id: require_project(DB,data.project_id,user['id'],write=True)
    cid,now=uid(),utcnow()
    DB.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',(cid,user['id'],data.title,data.project_id,now,now))
    return require_owned(DB,'conversations',cid,user['id'])


class ConversationProjectIn(BaseModel):
    project_id: str | None = None


@app.patch('/api/conversations/{cid}/project')
def change_conversation_project(cid: str, data: ConversationProjectIn, request: Request,
                                user=Depends(current_user)):
    require_csrf(request)
    current=require_owned(DB, 'conversations', cid, user['id'])
    if current['project_id']:
        require_project(DB,current['project_id'],user['id'],write=True)
    if data.project_id:
        require_project(DB,data.project_id,user['id'],write=True)
    active = DB.one("SELECT id FROM runs WHERE conversation_id=? AND user_id=? "
                    "AND status IN ('queued','running','awaiting_approval') LIMIT 1",
                    (cid, user['id']))
    if active:
        raise HTTPException(409, 'Aguarde a tarefa atual terminar antes de alterar o projeto.')
    DB.execute('UPDATE conversations SET project_id=?,updated_at=? WHERE id=? AND user_id=?',
               (data.project_id, utcnow(), cid, user['id']))
    return require_owned(DB, 'conversations', cid, user['id'])




@app.get('/api/conversations/{cid}/context-policy')
def conversation_context_policy(cid: str, user=Depends(current_user)):
    convo = require_owned(DB, 'conversations', cid, user['id'])
    return {'scope': 'project' if convo['project_id'] else 'standalone',
            'recent_message_limit': PROJECT_HISTORY_COUNT if convo['project_id'] else SMALL_HISTORY_COUNT,
            'same_project_recall': bool(convo['project_id']),
            'cross_project_recall': False}


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
    autonomous: bool = False


@app.post('/api/runs')
async def start_run(data:RunIn, request:Request,user=Depends(current_user)):
    convo=require_owned(DB,'conversations',data.conversation_id,user['id'])
    if convo['project_id']:
        require_project(DB,convo['project_id'],user['id'],write=True)
    if data.mode not in ('auto','manual','team'): raise HTTPException(422,'Modo inválido.')
    effective_prompt = resolve_continuation_prompt(DB, convo['id'], data.prompt)
    if needs_workspace_tools(effective_prompt) and not data.autonomous:
        if effective_prompt != data.prompt:
            raise HTTPException(
                409, 'Reconheci que você quer continuar uma implementação desta conversa, '
                     'mas Autonomia está desligada. Abra Computador, confira a pasta '
                     'autorizada e ative Autonomia para eu inspecionar o estado atual '
                     'e continuar o trabalho. Nenhuma execução ou alteração foi iniciada.')
        raise HTTPException(
            409, 'Este pedido exige consultar ou alterar arquivos reais, mas Autonomia '
                 'está desligada. Abra Computador, confira a pasta correta e '
                 'ative Autonomia antes de enviar.')
    if data.autonomous:
        local_only(request)
        grant = computer_policy(DB, user['id'])
        if grant['mode'] not in ('full','ask') or not grant['folder']:
            raise HTTPException(403,'Autorize uma pasta no botão Computador antes de ativar a autonomia.')
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
    # Validate the worker plan BEFORE persisting the user's request. A rejected
    # plan must not create a ghost chat message or appear as a completed task.
    try:
        run_id=ENGINE.create_run(user['id'],data.conversation_id,effective_prompt,data.mode,data.agent_ids,
                                 flow,data.budget_limit,idempotency,autonomous=data.autonomous)
    except ValueError as exc: raise HTTPException(429 if isinstance(exc, QuotaExceeded) else 422,str(exc))
    now=utcnow()
    DB.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(uid(),convo['id'],user['id'],'user',None,data.prompt,now))
    DB.execute('UPDATE conversations SET updated_at=?,title=? WHERE id=?',
       (now,data.prompt[:60] if convo['title']=='Nova conversa' else convo['title'],convo['id']))
    ops_audit(DB,user['id'],'run_created','run',run_id)
    return {'id':run_id}


@app.get('/api/runs')
def list_runs(user=Depends(current_user)):
    rows=DB.all(
        """SELECT r.id,r.conversation_id,r.prompt,r.status,r.mode,r.error,
                  r.total_cost,r.budget_limit,r.created_at,r.updated_at
           FROM runs r LEFT JOIN organization_runs x ON x.run_id=r.id
           WHERE r.user_id=? AND (x.organization_id IS NULL OR
                  x.organization_id IN
                    (SELECT organization_id FROM organization_members WHERE user_id=?))
           ORDER BY r.created_at DESC LIMIT 100""",
        (user['id'],user['id']))
    for row in rows:
        row['delivery_verified']=False
        if row['status']=='completed':
            proof=delivery_evidence(DB,row['id'])
            row['delivery_verified']=bool(proof['changed_files'] and proof['tests_passed']
                                          and proof['validation_after_last_change'])
    return rows


@app.get('/api/runs/{rid}')
def get_run(rid:str,user=Depends(current_user)):
    run=require_owned(DB,'runs',rid,user['id'])
    run['steps']=DB.all('SELECT * FROM steps WHERE run_id=?',(rid,))
    run['checkpoints']=checkpoint_summary(DB,user['id'],rid)
    run['workspace_binding']=binding_summary(DB,user['id'],rid)
    run['job']=ENGINE.queue.details(rid)
    run['token_usage']=run_usage(DB,user['id'],rid)
    proof=delivery_evidence(DB,rid) if run['status']=='completed' else None
    run['delivery_verified']=bool(proof and proof['changed_files'] and proof['tests_passed']
                                   and proof['validation_after_last_change'])
    return run


@app.post('/api/runs/{rid}/feedback-summary')
def ensure_run_feedback_summary(rid:str,request:Request,user=Depends(current_user)):
    require_csrf(request)
    run=require_owned(DB,'runs',rid,user['id'])
    if run['status'] not in ('paused_limit','failed','cancelled'):
        raise HTTPException(409,'A execução não precisa de um resumo de interrupção.')
    if run.get('autonomous'):
        local_only(request)
    message=ENGINE._record_run_feedback(run,run['status'],run.get('error') or '')
    return {'message':message}


@app.get('/api/runs/{rid}/token-usage')
def get_run_token_usage(rid:str,user=Depends(current_user)):
    require_owned(DB,'runs',rid,user['id'])
    return run_usage(DB,user['id'],rid)


@app.get('/api/token-usage')
def get_token_usage(days:int=30,user=Depends(current_user)):
    if days not in (7,30,90):
        raise HTTPException(422,'O período deve ser de 7, 30 ou 90 dias.')
    return usage_overview(DB,user['id'],days)


class WorktreeApproveIn(BaseModel):
    confirmation: str = Field(min_length=20, max_length=128)


@app.get('/api/runs/{rid}/worktrees')
def list_run_worktrees(rid: str, request: Request, user=Depends(current_user)):
    local_only(request)
    from .scoped_worker_reviews import list_worktrees
    return list_worktrees(DB, user['id'], rid)


@app.post('/api/runs/{rid}/steps/{sid}/worktree')
async def prepare_run_worktree(rid: str, sid: str, request: Request,
                               user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    from .scoped_worker_reviews import register_worktree
    result = await asyncio.to_thread(register_worktree, DB, user['id'], rid, sid)
    ops_audit(DB, user['id'], 'worktree_prepared', 'run', rid)
    return result


@app.post('/api/runs/{rid}/steps/{sid}/worktree-review')
async def create_run_worktree_review(rid: str, sid: str, request: Request,
                                     user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    from .scoped_worker_reviews import create_review
    result = await asyncio.to_thread(create_review, DB, user['id'], rid, sid)
    ops_audit(DB, user['id'], 'worktree_review_created', 'run', rid)
    return result


@app.get('/api/runs/{rid}/worktree-reviews/{plan_id}')
def get_run_worktree_review(rid: str, plan_id: str, request: Request,
                            user=Depends(current_user)):
    local_only(request)
    from .scoped_worker_reviews import get_review
    return get_review(DB, user['id'], rid, plan_id)


@app.post('/api/runs/{rid}/worktree-reviews/{plan_id}/apply')
async def approve_run_worktree_review(rid: str, plan_id: str,
                                      data: WorktreeApproveIn, request: Request,
                                      user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    from .scoped_worker_reviews import approve_review
    result = await asyncio.to_thread(approve_review, DB, user['id'], rid,
                                     plan_id, data.confirmation)
    ops_audit(DB, user['id'], 'worktree_files_promoted', 'run', rid)
    return result


@app.post('/api/runs/{rid}/resume')
async def resume_run(rid:str,request:Request,user=Depends(current_user)):
    require_csrf(request)
    run=require_run_write(DB,rid,user['id'])
    if run['autonomous']:
        local_only(request)
    try: ENGINE.resume_run(rid)
    except ValueError as e: raise HTTPException(409,str(e))
    ops_audit(DB,user['id'],'run_resumed','run',rid)
    return {'ok':True,'status':'queued',
            'checkpoints':checkpoint_summary(DB,user['id'],rid)}


@app.post('/api/runs/{rid}/cancel')
async def stop_run(rid:str,request:Request,user=Depends(current_user)):
    require_csrf(request)
    require_run_write(DB,rid,user['id'])
    ENGINE.cancel(rid)
    ops_audit(DB,user['id'],'run_cancel_requested','run',rid)
    return {'ok':True}


class ApprovalIn(BaseModel):
    approved: bool


@app.post('/api/runs/{rid}/steps/{sid}/approval')
async def approve_step(rid:str,sid:str,data:ApprovalIn,request:Request,
                       user=Depends(current_user)):
    require_csrf(request)
    require_run_write(DB,rid,user['id'])
    step=DB.one('SELECT * FROM steps WHERE id=? AND run_id=?',(sid,rid))
    if not step or step['kind']!='approval' or step['status']!='awaiting_approval':
        raise HTTPException(409,'Não há aprovação pendente.')
    ENGINE.approve(rid,sid,data.approved)
    ops_audit(DB,user['id'],'step_approval_decided','run',rid,
              outcome='approved' if data.approved else 'denied')
    return {'ok':True}


@app.post('/api/runs/{rid}/workspace/approvals/{approval_id}')
async def approve_workspace_action(rid: str, approval_id: str,
                                   data: ApprovalIn, request: Request,
                                   user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    run = require_run_write(DB,rid,user['id'])
    if not run['autonomous'] or run['status'] not in ('running', 'awaiting_approval'):
        raise HTTPException(409, 'A execução não está aguardando autorização de ferramentas.')
    outcome = decide_workspace_action(DB, user['id'], rid, approval_id, data.approved)
    ops_audit(DB,user['id'],'workspace_action_decided','run',rid,
              outcome='approved' if data.approved else 'denied')
    return outcome


@app.get('/api/runs/{rid}/workspace/approvals')
def pending_workspace_approvals(rid: str, request: Request, user=Depends(current_user)):
    local_only(request)
    require_owned(DB, 'runs', rid, user['id'])
    rows = DB.all("""SELECT id,request_json,step_id,created_at FROM workspace_action_approvals
                     WHERE run_id=? AND user_id=? AND status='pending' ORDER BY created_at""",
                  (rid, user['id']))
    from .workspace_tools import preview
    import json as _json
    from .browser_mcp import approval_summary
    folder = computer_policy(DB, user['id'])['folder']
    result = []
    for row in rows:
        try:
            requested = _json.loads(row['request_json'])
            summary = (approval_summary(requested)
                       if requested.get('action') == 'browser_tool'
                       else preview(folder, requested))
            result.append({'approval_id': row['id'], 'step_id': row['step_id'],
                           'summary': summary})
        except (HTTPException, ValueError):
            continue
    return result


class RunFeedbackIn(BaseModel):
    message: str = Field(min_length=3, max_length=1800)


@app.post('/api/runs/{rid}/feedback')
def add_run_feedback(rid: str, data: RunFeedbackIn, request: Request,
                     user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    run = require_run_write(DB,rid,user['id'])
    if not run['autonomous'] or run['status'] not in ('queued', 'running', 'awaiting_approval', 'paused_limit', 'failed'):
        raise HTTPException(409, 'Esta execução não aceita novos ajustes.')
    cleaned = data.message.strip()
    if len(cleaned) < 3:
        raise HTTPException(422, 'Descreva o ajuste desejado.')
    pending = DB.one('SELECT COUNT(*) n FROM run_feedback WHERE run_id=? AND user_id=? AND consumed_at IS NULL',
                     (rid, user['id']))['n']
    if pending >= 12:
        raise HTTPException(429, 'Muitos ajustes pendentes. Aguarde os trabalhadores processarem.')
    feedback_id = uid()
    DB.execute('INSERT INTO run_feedback(id,run_id,user_id,content,created_at) VALUES(?,?,?,?,?)',
               (feedback_id, rid, user['id'], cleaned, utcnow()))
    ENGINE.emit(rid, 'workspace_feedback_received',
                {'id': feedback_id, 'message': cleaned, 'status': 'queued'})
    return {'id': feedback_id, 'status': 'queued',
            'message': ('Ajuste salvo. Clique em Continuar execução para aplicá-lo.'
                        if run['status'] in ('paused_limit', 'failed') else
                        'Ajuste recebido. Será entregue ao agente na próxima etapa de raciocínio.')}


class PreviewStartIn(BaseModel):
    cwd: str = Field(default='', max_length=280)


@app.get('/api/preview/projects')
def preview_projects(request: Request, user=Depends(current_user)):
    local_only(request)
    permission = computer_policy(DB, user['id'])
    if permission['mode'] == 'blocked':
        return {'projects': [], 'status': 'blocked'}
    return {'projects': preview_candidates(permission['folder']),
            'status': 'available'}


@app.get('/api/preview/status')
def preview_status(request: Request, user=Depends(current_user)):
    local_only(request)
    return preview_info(user['id'])


@app.post('/api/preview/start')
def preview_start(data: PreviewStartIn, request: Request,
                  user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    return start_preview(DB, user['id'], data.cwd)


@app.post('/api/preview/stop')
def preview_stop(request: Request, user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    return stop_preview(user['id'])


@app.get('/api/runs/{rid}/activity')
def run_activity(rid: str, user=Depends(current_user)):
    run = require_owned(DB, 'runs', rid, user['id'])
    events = DB.all('SELECT seq,event,payload,created_at FROM events WHERE run_id=? '
                    'ORDER BY seq DESC LIMIT 70', (rid,))
    allowed = {'run_created','run_status','run_resumed','run_paused_limit',
               'step_status','model_selected','worker_checkpoint_restored',
               'workspace_action_requested','workspace_action_result',
               'worker_message','worker_phase','worker_heartbeat','skill_context_selected',
               'worker_budget_warning','delivery_repair_queued','agent_message_sent','agent_messages_delivered',
               'native_session_started','native_session_resumed','native_turn_completed',
               'workspace_approval_required','workspace_validation',
               'workspace_feedback_received','workspace_feedback_applied',
               'run_failed','run_completed','provider_error','failover'}
    import re
    def safe_log(message):
        snippet = str(message or '')[-900:]
        snippet = re.sub(r'(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+',
                         r'\1=[oculto]', snippet)
        snippet = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}\b', '[chave ocultada]', snippet)
        return snippet
    entries = []
    for e in reversed(events):
        if e['event'] not in allowed:
            continue
        data = json.loads(e['payload'])
        # The activity feed is deliberately metadata-only; diffs and contents
        # stay behind the existing authenticated approval UI.
        summary = data.get('summary') or {}
        entries.append({
            'seq': e['seq'], 'event': e['event'], 'created_at': e['created_at'],
            'step_id': data.get('step_id') or data.get('id'),
            'stage': data.get('stage'),
            'action': data.get('action') or summary.get('action'),
            'path': data.get('path') or summary.get('path'),
            'description': summary.get('description'),
            'command': data.get('command'),
            'success': data.get('success', data.get('ok', data.get('passed'))),
            'model': data.get('model'),
            'status': data.get('status'),
            'error': safe_log(data.get('error') or data.get('message')),
            'detail': safe_log(data.get('output')) if data.get('success') is False else '',
            'count': data.get('count'),
            'remaining_rounds': data.get('remaining_rounds'),
            'sender_agent_id': data.get('sender_agent_id'),
            'recipient_agent_id': data.get('recipient_agent_id'),
            'message_type': data.get('message_type'),
            'attempt': data.get('attempt'),
            'available_count': data.get('available_count'),
            'available_skills': data.get('available_skills'),
            'inventory_truncated': data.get('inventory_truncated'),
            'selected_skills': data.get('selected_skills'),
        })
    last_event = DB.one('SELECT created_at FROM events WHERE run_id=? '
                        'ORDER BY seq DESC LIMIT 1', (rid,))
    proof=delivery_evidence(DB,rid) if run['status']=='completed' else None
    delivered=bool(proof and proof['changed_files'] and proof['tests_passed']
                   and proof['validation_after_last_change'])
    return {'run_id': rid, 'status': run['status'], 'error': run['error'],
            'delivery_verified': delivered,
            'updated_at': run['updated_at'],
            'checkpoints': checkpoint_summary(DB,user['id'],rid),
            'workspace_binding': binding_summary(DB,user['id'],rid),
            'native_sessions': DB.all('SELECT step_id,model,state,updated_at FROM codex_step_sessions WHERE run_id=? AND user_id=?',
                                      (rid, user['id'])),
            'agent_messages': DB.all(
                'SELECT m.id,m.message_type,m.state,substr(m.content,1,800) content,'
                'a.name sender_name,b.name recipient_name FROM agent_messages m '
                'JOIN agents a ON a.id=m.sender_agent_id JOIN agents b ON b.id=m.recipient_agent_id '
                'WHERE m.run_id=? AND m.user_id=? ORDER BY m.created_at DESC,m.id DESC LIMIT 8',
                (rid, user['id'])),
            'steps': [{'id':step['id'],'name':step['name'],'status':step['status'],
                       'error':step['error']} for step in DB.all(
                           'SELECT id,name,status,error FROM steps WHERE run_id=?', (rid,))],
            'last_activity_at': last_event['created_at'] if last_event else run['created_at'],
            'events': entries[-55:]}


@app.get('/api/runs/{rid}/agent-messages')
def run_agent_messages(rid: str, user=Depends(current_user)):
    run = require_owned(DB, 'runs', rid, user['id'])
    conversation = DB.one('SELECT project_id FROM conversations WHERE id=?', (run['conversation_id'],))
    from .agent_messages import list_messages
    return {'messages': list_messages(DB, user['id'], rid, conversation['project_id'])}


@app.get('/api/runtimes')
def local_runtimes(request: Request, user=Depends(current_user)):
    local_only(request)
    from .codex_runtime import inventory
    return inventory()


@app.post('/api/runtimes/codex/probe')
def probe_codex_runtime(request: Request, user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    from .codex_runtime import probe
    return probe()


class CodexConnectIn(BaseModel):
    model: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
    create_worker: bool = True


@app.post('/api/runtimes/codex/connect')
def connect_codex_runtime(data: CodexConnectIn, request: Request, user=Depends(current_user)):
    require_csrf(request)
    local_only(request)
    if os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local') != 'local':
        raise HTTPException(403, 'O login local do Codex não pode ser compartilhado no modo servidor.')
    from .codex_runtime import probe
    from .codex_bridge import CERTIFIED_VERSION
    result = probe()
    if result['status'] != 'ok' or result['auth_type'] != 'chatgpt':
        raise HTTPException(409, 'Conecte o Codex CLI com sua conta ChatGPT antes de continuar.')
    if result['version'] != CERTIFIED_VERSION:
        raise HTTPException(409, 'Esta versão do Codex ainda não foi validada com o gateway da Central.')
    if data.model not in {item['id'] for item in result['models']}:
        raise HTTPException(422, 'Selecione um modelo retornado pelo catálogo do Codex.')
    with DB.lock, DB.conn:
        DB.conn.execute('BEGIN IMMEDIATE')
        provider = DB.one("SELECT * FROM providers WHERE user_id=? AND kind='codex_cli' AND model=?",
                          (user['id'], data.model))
        if not provider:
            provider_id = uid()
            DB.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,priority,enabled,created_at) '
                       "VALUES(?,?,?,'codex_cli','codex://local',?,50,1,?)",
                       (provider_id, user['id'], 'Codex local · ' + data.model[:45], data.model, utcnow()))
            provider = DB.one('SELECT * FROM providers WHERE id=?', (provider_id,))
        else:
            DB.execute('UPDATE providers SET enabled=1 WHERE id=?', (provider['id'],))
        worker = DB.one("SELECT id FROM agents WHERE user_id=? AND provider_id=? AND specialty='code' ORDER BY created_at LIMIT 1",
                        (user['id'], provider['id']))
        if data.create_worker and not worker:
            worker_id = uid()
            DB.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,provider_id,model,avatar,max_concurrency,created_at) '
                       "VALUES(?,?,?,'code',?,?,?,'⌘',1,?)",
                       (worker_id, user['id'], 'Codex · ' + data.model[:45],
                        'Implemente soluções completas e verificáveis usando as ferramentas da Central. '
                        'Inspecione arquivos reais, corrija erros, execute testes e relate somente evidências. '
                        'Respeite o workspace, as aprovações e as instruções atuais do usuário.',
                        provider['id'], data.model, utcnow()))
            worker = {'id': worker_id}
        reviewer = DB.one("SELECT id FROM agents WHERE user_id=? AND provider_id=? AND specialty='review' ORDER BY created_at LIMIT 1",
                          (user['id'], provider['id']))
        if data.create_worker and not reviewer:
            reviewer_id = uid()
            DB.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,provider_id,model,avatar,max_concurrency,created_at) '
                       "VALUES(?,?,?,'review',?,?,?,'✓',1,?)",
                       (reviewer_id, user['id'], 'Revisor Codex · ' + data.model[:40],
                        'Revise os arquivos reais do implementador, verifique critérios de aceite e execute testes. '
                        'Corrija defeitos encontrados usando as ferramentas autorizadas da Central e valide novamente. '
                        'Não considere relatos ou build isolado como comprovação de funcionamento visual.',
                        provider['id'], data.model, utcnow()))
            reviewer = {'id': reviewer_id}
    ops_audit(DB, user['id'], 'codex_runtime_connected', 'provider', provider['id'])
    return {'provider': public_provider(require_owned(DB, 'providers', provider['id'], user['id'])),
            'agent_id': worker['id'] if worker else None,
            'reviewer_id': reviewer['id'] if reviewer else None, 'generation_tested': False}


@app.get('/api/agents/specialist-pack')
def missing_specialist_profiles(user=Depends(current_user)):
    from .specialist_profiles import list_missing_profiles
    return {'profiles': list_missing_profiles(DB, user['id'])}


@app.post('/api/agents/specialist-pack')
def add_specialist_profiles(request: Request, user=Depends(current_user)):
    require_csrf(request)
    from .specialist_profiles import install_missing_profiles
    result = install_missing_profiles(DB, user['id'])
    ops_audit(DB, user['id'], 'specialist_profiles_added', 'agents', user['id'])
    return result


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
            if run and run['status'] in ('completed','failed','cancelled','paused_limit') and not items: break
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


@app.get('/api/operations/overview')
def operational_overview(user=Depends(current_user)):
    result = ops_overview(DB,user['id'])
    result['command_executor'] = sandbox_status()
    return result


@app.get('/api/operations/audit')
def operational_audit(limit:int=50,user=Depends(current_user)):
    return audit_history(DB,user['id'],limit)


@app.get('/api/runs/{rid}/classification')
def run_classification(rid: str, user=Depends(current_user)):
    run=require_owned(DB,'runs',rid,user['id'])
    row=DB.one("SELECT payload FROM events WHERE run_id=? AND event='task_classified' "
               "ORDER BY seq DESC LIMIT 1", (rid,))
    return json.loads(row['payload']) if row else classify_task(
        run['prompt'], bool(run['autonomous']))


@app.get('/api/health/ready')
def readiness(response: Response):
    try:
        row=DB.one('SELECT 1 AS ready')
        if not row or row['ready']!=1:
            raise RuntimeError('Database unavailable')
        return {'status':'ready','database':'ready',
                'job_executor':ENGINE.job_mode,'durable_job_queue':True,
                'distributed_queue':False,
                'command_executor':sandbox_status(),
                'providers':'not_checked'}
    except Exception:
        response.status_code=503
        return {'status':'unavailable','database':'unavailable'}


@app.get('/api/health')
def health():
    return {'status':'ok','note':'Saúde da API local. Não significa que provedores estejam disponíveis.'}


class MemoryRetrievalIn(BaseModel):
    enabled: bool


@app.get('/api/projects/{project_id}/retrieval')
def get_memory_retrieval(project_id: str, user=Depends(current_user)):
    return memory_preference(DB, user['id'], project_id)


@app.put('/api/projects/{project_id}/retrieval')
def set_memory_retrieval(project_id: str, data: MemoryRetrievalIn,
                         user=Depends(current_user)):
    result = memory_preference(DB, user['id'], project_id, data.enabled)
    ops_audit(DB, user['id'], 'memory_retrieval_changed', 'project', project_id)
    return result


@app.get('/api/providers/comparison')
def compare_providers(user=Depends(current_user)):
    return ENGINE.providers.comparison(user['id'])


@app.get('/api/operations/release-check')
def release_check(request: Request, user=Depends(current_user)):
    local_only(request)
    from .release_checks import report
    return report(DB)


class InvitationIn(BaseModel):
    invited_user_id: str = Field(min_length=1, max_length=100)
    role: str = Field(default='analyst', max_length=20)


class AcceptInvitationIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)


@app.post('/api/organizations/{oid}/invitations')
def create_invitation(oid: str, data: InvitationIn, user=Depends(current_user)):
    from .invitations import create
    result = create(DB, user['id'], oid, data.invited_user_id, data.role)
    ops_audit(DB, user['id'], 'invitation_created', 'organization', oid)
    return result


@app.post('/api/invitations/accept')
def accept_invitation(data: AcceptInvitationIn, user=Depends(current_user)):
    from .invitations import accept
    result = accept(DB, user['id'], data.token)
    ops_audit(DB, user['id'], 'invitation_accepted', 'organization', result['organization_id'])
    return result


@app.delete('/api/organizations/{oid}/invitations/{invitation_id}')
def revoke_invitation(oid: str, invitation_id: str, user=Depends(current_user)):
    from .invitations import revoke
    result = revoke(DB, user['id'], oid, invitation_id)
    ops_audit(DB, user['id'], 'invitation_revoked', 'organization', oid)
    return result


@app.get('/api/runs/{rid}/export')
def export_run(rid: str, format: str = 'json', user=Depends(current_user)):
    from .exports import run_report, markdown
    report = run_report(DB, user['id'], rid)
    if format not in ('json', 'md'):
        raise HTTPException(422, 'Formato deve ser json ou md.')
    ops_audit(DB, user['id'], 'run_exported', 'run', rid)
    content = json.dumps(report, ensure_ascii=False, indent=2) if format == 'json' else markdown(report)
    # Generated UUID filenames are used only as attachment names, never as paths.
    return Response(content=content, media_type='application/json' if format == 'json' else 'text/markdown',
                    headers={'Content-Disposition': 'attachment; filename="run.' + format + '"',
                             'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


class GitConnectionIn(BaseModel):
    service: str = Field(max_length=20)
    repository: str = Field(default='', max_length=250)
    token: str = Field(min_length=1, max_length=4096)


@app.get('/api/git/connections')
def git_connections(user=Depends(current_user)):
    from .git_integrations import connections
    return connections(DB, user['id'])


@app.post('/api/git/connections')
def add_git_connection(data: GitConnectionIn, user=Depends(current_user)):
    from .git_integrations import connect
    result = connect(DB, SEC, user['id'], data.service, data.repository, data.token)
    ops_audit(DB, user['id'], 'git_connection_saved', 'git_connection', result['id'])
    return result


@app.get('/api/git/connections/{connection_id}/repositories')
def git_connection_repositories(connection_id: str, user=Depends(current_user)):
    from .git_integrations import repositories
    return repositories(DB, SEC, user['id'], connection_id)


@app.delete('/api/git/connections/{connection_id}')
def delete_git_connection(connection_id: str, user=Depends(current_user)):
    changed = DB.execute('DELETE FROM git_connections WHERE id=? AND user_id=?',
                         (connection_id, user['id']))
    if not changed:
        raise HTTPException(404, 'Conexão não encontrada.')
    ops_audit(DB, user['id'], 'git_connection_deleted', 'git_connection', connection_id)
    return {'deleted': True}


@app.get('/api/git/connections/{connection_id}/reviews')
def git_reviews(connection_id: str, number: int | None = None, page: int = 1,
               repository: str | None = None, user=Depends(current_user)):
    from .git_integrations import reviews
    return reviews(DB, SEC, user['id'], connection_id, number, page=page, repository=repository)


class KnowledgeIn(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    content: str = Field(min_length=1, max_length=128000)
    visibility: str = Field(default='private', max_length=20)
    retention_days: int | None = Field(default=90, ge=1, le=3650)


@app.get('/api/projects/{pid}/knowledge')
def list_knowledge(pid: str, user=Depends(current_user)):
    from .knowledge import documents
    return documents(DB, user['id'], pid)


@app.post('/api/projects/{pid}/knowledge')
def add_knowledge(pid: str, data: KnowledgeIn, user=Depends(current_user)):
    from .knowledge import create
    result = create(DB, user['id'], pid, data.title, data.content, data.visibility, data.retention_days)
    ops_audit(DB, user['id'], 'knowledge_document_created', 'project', pid)
    return result


@app.delete('/api/projects/{pid}/knowledge/{document_id}')
def delete_knowledge(pid: str, document_id: str, user=Depends(current_user)):
    from .knowledge import delete
    result = delete(DB, user['id'], pid, document_id)
    ops_audit(DB, user['id'], 'knowledge_document_deleted', 'project', pid)
    return result


class GitDraftPlanIn(BaseModel):
    repository: str | None = Field(default=None, max_length=250)
    head: str = Field(min_length=1, max_length=200)
    base: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default='', max_length=10000)


class GitPlanApprovalIn(BaseModel):
    confirmation: str = Field(min_length=64, max_length=64)


@app.post('/api/git/connections/{connection_id}/draft-plans')
def create_git_plan(connection_id: str, data: GitDraftPlanIn, user=Depends(current_user)):
    from .git_change_plans import create
    result = create(DB, SEC, user['id'], connection_id, data.head, data.base, data.title, data.body, repository=data.repository)
    ops_audit(DB, user['id'], 'git_draft_planned', 'git_plan', result['id'])
    return result


@app.get('/api/git/connections/{connection_id}/draft-plans')
def git_plan_history(connection_id: str, limit: int = 15, user=Depends(current_user)):
    from .git_change_plans import history
    return history(DB, user['id'], connection_id, limit)


@app.post('/api/git/draft-plans/{plan_id}/reconcile')
def reconcile_git_plan(plan_id: str, request: Request, user=Depends(current_user)):
    require_csrf(request)
    from .git_change_plans import reconcile
    result = reconcile(DB, SEC, user['id'], plan_id)
    ops_audit(DB, user['id'], 'git_draft_reconciled', 'git_plan', plan_id,
              outcome=result['reconciliation'])
    return result


@app.get('/api/git/draft-plans/{plan_id}')
def git_plan_status(plan_id: str, user=Depends(current_user)):
    from .git_change_plans import status
    return status(DB, user['id'], plan_id)


@app.post('/api/git/draft-plans/{plan_id}/approve')
def approve_git_plan(plan_id: str, data: GitPlanApprovalIn, user=Depends(current_user)):
    from .git_change_plans import execute
    result = execute(DB, SEC, user['id'], plan_id, data.confirmation)
    ops_audit(DB, user['id'], 'git_draft_created', 'git_plan', plan_id)
    return result


from .addon_api import router as resource_router
app.include_router(resource_router(DB, SEC, current_user))
