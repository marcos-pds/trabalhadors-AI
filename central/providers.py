"""Authorized API connectors. Provider capability / price data is user-provided, never fabricated."""
import asyncio
import json
from urllib.parse import quote
import httpx

DEFAULT_ENDPOINTS = {
    'openai': 'https://api.openai.com/v1',
    'anthropic': 'https://api.anthropic.com/v1',
    'gemini': 'https://generativelanguage.googleapis.com/v1beta',
    'deepseek': 'https://api.deepseek.com/v1',
    'grok': 'https://api.x.ai/v1',
    'mistral': 'https://api.mistral.ai/v1',
    'ollama': 'http://127.0.0.1:11434/v1',
    'compatible': '',
}


class ProviderError(Exception):
    def __init__(self, category, message, retryable=False, http_status=None):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.http_status = http_status


def classify_http(code, response):
    text = response[:220].replace('\n', ' ')
    if code in (401, 403): return ProviderError('authentication', f'Autenticação/permissão (HTTP {code}).', False, code)
    if code == 402 or ('insufficient_quota' in response.lower()): return ProviderError('credits', 'Créditos insuficientes.', False, code)
    if code == 429: return ProviderError('rate_limit', 'Limite de requisições do provedor.', True, code)
    if code >= 500: return ProviderError('unavailable', f'Provedor indisponível (HTTP {code}).', True, code)
    return ProviderError('request', f'Erro HTTP {code}: {text}', False, code)


def parse_sse(lines):
    """Assemble SSE data events, tolerating multiline payloads."""
    buf = []
    for line in lines:
        if line.startswith('data:'):
            buf.append(line[5:].strip())
        elif not line.strip() and buf:
            yield '\n'.join(buf)
            buf = []
    if buf:
        yield '\n'.join(buf)


class ProviderClient:
    def __init__(self, timeout=90):
        self.timeout = timeout

    async def stream(self, provider, api_key, model, system, messages):
        kind = provider['kind']
        base = provider['base_url'].rstrip('/')
        if kind == 'anthropic':
            url = base + '/messages'
            headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01'}
            payload = {'model': model, 'max_tokens': min(max(int(provider.get('_max_tokens',1400)),256),4096), 'stream': True,
                       'system': system, 'messages': messages}
        elif kind == 'gemini':
            url = base + '/models/' + quote(model, safe='') + ':streamGenerateContent?alt=sse'
            headers = {'x-goog-api-key': api_key}
            contents = [{'role': 'model' if m['role']=='assistant' else 'user',
                         'parts': [{'text': m['content']}]} for m in messages]
            payload = {'systemInstruction': {'parts': [{'text': system}]}, 'contents': contents,
                       'generationConfig': {'maxOutputTokens': min(max(int(provider.get('_max_tokens',1400)),256),4096)}}
        else:
            url = base + '/chat/completions'
            headers = {'Content-Type': 'application/json'}
            if api_key: headers['Authorization'] = f'Bearer {api_key}'
            payload = {'model': model, 'messages': [{'role': 'system', 'content': system}] + messages,
                       'stream': True, 'max_tokens': min(max(int(provider.get('_max_tokens',1400)),256),4096)}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=12)) as client:
                async with client.stream('POST', url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        error = (await response.aread()).decode('utf-8', errors='replace')
                        raise classify_http(response.status_code, error)
                    buffered = []
                    async for line in response.aiter_lines():
                        if line.startswith('data:'):
                            buffered.append(line[5:].strip())
                            continue
                        if not line.strip() and buffered:
                            raw = '\n'.join(buffered)
                            buffered.clear()
                            if raw == '[DONE]': return
                            try: event = json.loads(raw)
                            except json.JSONDecodeError: continue
                            if 'error' in event:
                                raise ProviderError('response', str(event['error'])[:240], False)
                            if kind == 'anthropic':
                                token = event.get('delta', {}).get('text', '') if event.get('type') == 'content_block_delta' else ''
                            elif kind == 'gemini':
                                token = ''.join(x.get('text','') for x in event.get('candidates',[{}])[0].get('content',{}).get('parts', []))
                            else:
                                token = ''.join(str(x.get('delta', {}).get('content') or '') for x in event.get('choices', []))
                            if token: yield token
                    # Some proxies omit final newline; parse remaining complete frame.
                    if buffered:
                        try:
                            event = json.loads('\n'.join(buffered))
                            if kind == 'anthropic': token = event.get('delta',{}).get('text','')
                            elif kind == 'gemini': token = ''.join(x.get('text','') for x in event.get('candidates',[{}])[0].get('content',{}).get('parts', []))
                            else: token = ''.join(str(x.get('delta',{}).get('content') or '') for x in event.get('choices',[]))
                            if token: yield token
                        except json.JSONDecodeError:
                            pass
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError('timeout', 'Tempo limite excedido.', True)
        except httpx.TransportError as exc:
            raise ProviderError('network', f'Erro de conexão: {str(exc)[:120]}', True)
