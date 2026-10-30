"""Sign in with ChatGPT plan credentials and Responses API adapter.

Only the documented public OAuth and Responses endpoints are used. Secrets stay
server-side, encrypted at rest by the existing Fernet key.
"""
import base64
import hashlib
import json
import time
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .providers import ProviderError, classify_http

AUTH_ISSUER = 'https://auth.openai.com'
AUTHORIZE_URL = AUTH_ISSUER + '/api/accounts/authorize'
TOKEN_URL = AUTH_ISSUER + '/api/accounts/oauth/token'
API_BASE = 'https://api.openai.com/v1'
REQUIRED_SCOPE = 'chatgpt.tokens.use.direct'


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def pkce_pair():
    import secrets
    verifier = b64url(secrets.token_bytes(32))
    challenge = b64url(hashlib.sha256(verifier.encode('ascii')).digest())
    return verifier, challenge


def authorization_url(*, client_id, host_id, app_name, redirect_uri, state, nonce, challenge, id_token_hint=None, login_hint=None):
    params = {
        'client_id': client_id, 'response_type': 'code', 'redirect_uri': redirect_uri,
        'scope': 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct',
        'resource': API_BASE, 'state': state, 'nonce': nonce,
        'code_challenge_method': 'S256', 'code_challenge': challenge,
        'ext_agent_host_id': host_id,
    }
    if client_id == 'dynamic_agent_client':
        params['agent_name_hint'] = app_name
    if id_token_hint:
        params['id_token_hint'] = id_token_hint
    if login_hint:
        params['login_hint'] = login_hint
    return AUTHORIZE_URL + '?' + urlencode(params)


async def exchange_code(*, code, client_id, verifier, redirect_uri):
    return await _token_request({
        'grant_type': 'authorization_code', 'code': code, 'client_id': client_id,
        'code_verifier': verifier, 'redirect_uri': redirect_uri, 'resource': API_BASE,
    })


async def refresh_token(credentials):
    result = await _token_request({
        'grant_type': 'refresh_token', 'refresh_token': credentials['refresh_token'],
        'client_id': credentials['client_id'], 'resource': API_BASE,
    })
    scopes = result.get('scope', credentials.get('scopes', ''))
    updated = dict(credentials)
    updated.update({
        'access_token': result['access_token'],
        'refresh_token': result.get('refresh_token', credentials['refresh_token']),
        'expires_at': int(time.time()) + int(result.get('expires_in', 3600)),
        'scopes': scopes,
    })
    return updated


async def _token_request(form):
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False) as client:
            response = await client.post(TOKEN_URL, data=form, headers={'Accept': 'application/json'})
        if response.status_code >= 400:
            raise ProviderError('authentication', 'A OpenAI recusou a autorização. Tente conectar novamente.', False, response.status_code)
        data = response.json()
        if not isinstance(data, dict) or not data.get('access_token'):
            raise ProviderError('authentication', 'A resposta de autorização não foi válida.', False)
        return data
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        raise ProviderError('network', 'Não foi possível concluir a autorização com a OpenAI.', True)


async def validate_id_token(token, *, client_id, nonce):
    """Validate RS256 signature and OIDC issuer/audience/time/nonce claims."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError('jwt')
        header = json.loads(base64.urlsafe_b64decode(parts[0] + '=' * (-len(parts[0]) % 4)))
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        if header.get('alg') != 'RS256' or not header.get('kid'):
            raise ValueError('alg')
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=6), follow_redirects=False) as client:
            discovery_response = await client.get(AUTH_ISSUER + '/.well-known/openid-configuration')
            discovery_response.raise_for_status()
            discovery = discovery_response.json()
            if discovery.get('issuer') != AUTH_ISSUER:
                raise ValueError('issuer')
            jwks_uri = discovery.get('jwks_uri', '')
            if not jwks_uri.startswith(AUTH_ISSUER + '/'):
                raise ValueError('jwks')
            keys_response = await client.get(jwks_uri)
            keys_response.raise_for_status()
            keys = keys_response.json().get('keys', [])
        jwk = next(key for key in keys if key.get('kid') == header['kid'] and key.get('kty') == 'RSA')
        number = lambda value: int.from_bytes(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)), 'big')
        public_key = rsa.RSAPublicNumbers(number(jwk['e']), number(jwk['n'])).public_key()
        signature = base64.urlsafe_b64decode(parts[2] + '=' * (-len(parts[2]) % 4))
        public_key.verify(signature, (parts[0] + '.' + parts[1]).encode('ascii'), padding.PKCS1v15(), hashes.SHA256())
        now = int(time.time())
        audience = claims.get('aud')
        if claims.get('iss') != AUTH_ISSUER or (client_id not in audience if isinstance(audience, list) else audience != client_id):
            raise ValueError('issuer/audience')
        if int(claims.get('exp', 0)) <= now or int(claims.get('iat', 0)) > now + 120:
            raise ValueError('time')
        if claims.get('nonce') != nonce or not claims.get('sub'):
            raise ValueError('nonce/subject')
        return claims
    except Exception as exc:
        raise ProviderError('authentication', 'A identidade retornada pela OpenAI não pôde ser validada.', False) from exc


def visible_models(models):
    if not isinstance(models, list):
        raise ValueError('models')
    output = []
    for item in models:
        if isinstance(item, dict) and item.get('visibility') == 'list':
            slug = item.get('slug')
            name = item.get('display_name')
            if isinstance(slug, str) and slug and len(slug) <= 120:
                output.append({'id': slug, 'name': name if isinstance(name, str) else slug})
    return output


def response_payload(model, system, messages):
    return {
        'model': model,
        'instructions': system,
        'input': [{'role': m['role'], 'content': m['content']} for m in messages],
        'store': False,
        'stream': True,
    }


async def available_models(access_token):
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), follow_redirects=False) as client:
            response = await client.get(API_BASE + '/models', headers={'Authorization': 'Bearer ' + access_token})
        if response.status_code >= 400:
            raise classify_http(response.status_code, '')
        return visible_models(response.json().get('models', []))
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        raise ProviderError('catalog', 'Não foi possível carregar os modelos permitidos por esta conta ChatGPT.', True)


async def stream_response(access_token, model, system, messages, timeout=90):
    """Stream plan-eligible text; never use ChatGPT's private backend endpoints."""
    from .token_usage import estimate_tokens, report_usage

    payload = response_payload(model, system, messages)
    completed = False
    input_tokens = output_tokens = None
    output_chars = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=12), follow_redirects=False) as client:
            async with client.stream('POST', API_BASE + '/responses', json=payload,
                                    headers={'Authorization': 'Bearer ' + access_token, 'Content-Type': 'application/json'}) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode('utf-8', errors='replace')
                    raise classify_http(response.status_code, '')
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == '[DONE]':
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    kind = event.get('type')
                    if kind == 'response.output_text.delta':
                        token = event.get('delta')
                        if isinstance(token, str) and token:
                            output_chars += len(token)
                            yield token
                    elif kind == 'response.failed':
                        error = (event.get('response') or {}).get('error') or {}
                        code = error.get('code')
                        category = 'credits' if code in ('subscription_sharing_usage_limit_exceeded', 'subscription_sharing_usage_unavailable') else 'response'
                        raise ProviderError(category, 'A solicitação do ChatGPT não foi concluída. Verifique os limites e permissões da conta.', False)
                    elif kind == 'response.incomplete':
                        raise ProviderError('response', 'A resposta do ChatGPT foi interrompida antes da conclusão.', True)
                    elif kind == 'response.completed':
                        completed = True
                        usage = (event.get('response') or {}).get('usage') or {}
                        input_tokens = usage.get('input_tokens')
                        output_tokens = usage.get('output_tokens')
        if not completed:
            raise ProviderError('response', 'O fluxo do ChatGPT foi encerrado sem confirmação de conclusão.', True)
        if input_tokens is not None and output_tokens is not None:
            report_usage(input_tokens, output_tokens, 'actual')
        else:
            report_usage(
                estimate_tokens(system + ''.join(m.get('content', '') for m in messages)),
                (output_chars + 3) // 4,
                'estimated',
            )
    except ProviderError:
        raise
    except httpx.TimeoutException:
        raise ProviderError('timeout', 'Tempo limite excedido.', True)
    except httpx.TransportError:
        raise ProviderError('network', 'Erro de conexão com a API do ChatGPT.', True)

async def _stored_credentials_locked(db, security, connection_id):
    """Load, refresh and persist one user-owned OAuth connection."""
    from .database import utcnow
    row = db.one('SELECT * FROM chatgpt_plan_connections WHERE id=?', (connection_id,))
    if not row:
        raise ProviderError('authentication', 'A conta ChatGPT foi desconectada. Reconecte o provedor.', False)
    try:
        credentials = json.loads(security.decrypt(row['credentials_enc']))
        if int(credentials.get('expires_at', 0)) <= int(time.time()) + 60:
            credentials = await refresh_token(credentials)
            scopes = str(credentials.get('scopes') or '').split()
            if REQUIRED_SCOPE not in scopes or 'resource.invoke' not in scopes:
                raise ProviderError('authentication', 'A permissão para uso do plano ChatGPT expirou. Reconecte a conta.', False)
            db.execute('UPDATE chatgpt_plan_connections SET credentials_enc=?,scopes=?,updated_at=? WHERE id=?',
                       (security.encrypt(json.dumps(credentials, separators=(',', ':'))),
                        credentials['scopes'], utcnow(), connection_id))
        return credentials
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError('authentication', 'A conexão ChatGPT precisa ser renovada. Reconecte a conta.', False) from exc

async def revoke_session(credentials):
    """Revoke only this OAuth renewable session through OpenID metadata."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8), follow_redirects=False) as client:
            metadata_response = await client.get(AUTH_ISSUER + '/.well-known/openid-configuration')
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            endpoint = metadata.get('revocation_endpoint', '')
            if not endpoint.startswith(AUTH_ISSUER + '/'):
                raise ProviderError('authentication', 'O endpoint oficial de revogação não pôde ser validado.', False)
            response = await client.post(endpoint, data={
                'token': credentials['refresh_token'],
                'token_type_hint': 'refresh_token',
                'client_id': credentials['client_id'],
            }, headers={'Accept': 'application/json'})
        if response.status_code != 200:
            raise ProviderError('authentication', 'A OpenAI não confirmou a revogação da sessão.', False, response.status_code)
        return True
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        raise ProviderError('network', 'Não foi possível confirmar a revogação remota. As credenciais locais foram apagadas.', True)

_refresh_locks = {}


async def stored_credentials(db, security, connection_id):
    import asyncio
    loop = asyncio.get_running_loop()
    lock = _refresh_locks.setdefault((id(loop), str(connection_id)), asyncio.Lock())
    async with lock:
        return await _stored_credentials_locked(db, security, connection_id)