"""Authorized API connectors. Provider capability / price data is user-provided, never fabricated."""
import asyncio
import json
from urllib.parse import quote
import httpx
from .token_usage import estimate_tokens, report_usage

DEFAULT_ENDPOINTS = {
    'openai': 'https://api.openai.com/v1',
    'anthropic': 'https://api.anthropic.com/v1',
    'gemini': 'https://generativelanguage.googleapis.com/v1beta',
    'deepseek': 'https://api.deepseek.com/v1',
    'grok': 'https://api.x.ai/v1',
    'mistral': 'https://api.mistral.ai/v1',
    'ollama': 'http://127.0.0.1:11434/v1',
    'lmstudio': 'http://127.0.0.1:1234/v1',
    'localai': 'http://127.0.0.1:8080/v1',
    'jan': 'http://127.0.0.1:1337/v1',
    'vllm': 'http://127.0.0.1:8000/v1',
    'llamacpp': 'http://127.0.0.1:8080/v1',
    'openrouter': 'https://openrouter.ai/api/v1',
    'groq': 'https://api.groq.com/openai/v1',
    'cerebras': 'https://api.cerebras.ai/v1',
    'sambanova': 'https://api.sambanova.ai/v1',
    'huggingface': 'https://router.huggingface.co/v1',
    'cloudflare': 'https://api.cloudflare.com/client/v4/accounts/SEU_ACCOUNT_ID/ai/v1',
    'nvidia': 'https://integrate.api.nvidia.com/v1',
    'together': 'https://api.together.xyz/v1',
    'fireworks': 'https://api.fireworks.ai/inference/v1',
    'perplexity': 'https://api.perplexity.ai',
    'cohere': 'https://api.cohere.ai/compatibility/v1',
    'deepinfra': 'https://api.deepinfra.com/v1/openai',
    'novita': 'https://api.novita.ai/v3/openai',
    'zai': 'https://api.z.ai/api/paas/v4',
    'modelscope': 'https://api-inference.modelscope.cn/v1',
    'siliconflow': 'https://api.siliconflow.com/v1',
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
        if kind == 'codex_cli':
            from .codex_bridge import stream_response
            async for token in stream_response(provider, model, system, messages, timeout=max(120, self.timeout)):
                yield token
            return
        if kind == 'openai_chatgpt':
            from .chatgpt_plan import stream_response
            async for token in stream_response(api_key, model, system, messages, timeout=self.timeout):
                yield token
            return
        requested = provider.get('_max_tokens', 1400)
        max_tokens = max(256, min(8192, int(requested)))
        base = provider['base_url'].rstrip('/')
        input_tokens = output_tokens = None
        output_chars = 0
        usage_reported = False

        def capture_usage(event):
            nonlocal input_tokens, output_tokens
            usage = (event.get('usage') or event.get('usageMetadata') or
                     event.get('message', {}).get('usage') or {})
            if kind == 'anthropic':
                if usage.get('input_tokens') is not None:
                    input_tokens = usage['input_tokens']
                if usage.get('output_tokens') is not None:
                    output_tokens = usage['output_tokens']
            elif kind == 'gemini':
                if usage.get('promptTokenCount') is not None:
                    input_tokens = usage['promptTokenCount']
                if usage.get('candidatesTokenCount') is not None:
                    output_tokens = usage['candidatesTokenCount']
            else:
                if usage.get('prompt_tokens') is not None:
                    input_tokens = usage['prompt_tokens']
                if usage.get('completion_tokens') is not None:
                    output_tokens = usage['completion_tokens']

        def finish_usage():
            nonlocal usage_reported
            if usage_reported:
                return
            if input_tokens is not None and output_tokens is not None:
                report_usage(input_tokens, output_tokens, 'actual')
            else:
                report_usage(
                    estimate_tokens(system + ''.join(m.get('content', '') for m in messages)),
                    (output_chars + 3) // 4,
                    'estimated',
                )
            usage_reported = True

        if kind == 'anthropic':
            url = base + '/messages'
            headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01'}
            payload = {'model': model, 'max_tokens': max_tokens, 'stream': True,
                       'system': system, 'messages': messages}
        elif kind == 'gemini':
            url = base + '/models/' + quote(model, safe='') + ':streamGenerateContent?alt=sse'
            headers = {'x-goog-api-key': api_key}
            contents = [{'role': 'model' if m['role']=='assistant' else 'user',
                         'parts': [{'text': m['content']}]} for m in messages]
            payload = {'systemInstruction': {'parts': [{'text': system}]}, 'contents': contents,
                       'generationConfig': {'maxOutputTokens': max_tokens}}
        else:
            url = base + '/chat/completions'
            headers = {'Content-Type': 'application/json'}
            if api_key: headers['Authorization'] = f'Bearer {api_key}'
            payload = {'model': model, 'messages': [{'role': 'system', 'content': system}] + messages,
                       'stream': True, 'max_tokens': max_tokens,
                       'stream_options': {'include_usage': True}}
            if kind == 'ollama' and provider.get('_structured_actions'):
                # Ollama's documented JSON mode applies only to the tool loop;
                # ordinary conversation remains free-form text.
                from .action_schema import ACTION_RESPONSE_SCHEMA
                payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                    'name': 'workspace_action', 'schema': ACTION_RESPONSE_SCHEMA}}
                payload['temperature'] = 0
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
                            if raw == '[DONE]':
                                finish_usage()
                                return
                            try: event = json.loads(raw)
                            except json.JSONDecodeError: continue
                            capture_usage(event)
                            if 'error' in event:
                                raise ProviderError('response', str(event['error'])[:240], False)
                            if kind == 'anthropic':
                                token = event.get('delta', {}).get('text', '') if event.get('type') == 'content_block_delta' else ''
                            elif kind == 'gemini':
                                token = ''.join(x.get('text','') for x in event.get('candidates',[{}])[0].get('content',{}).get('parts', []))
                            else:
                                token = ''.join(str(x.get('delta', {}).get('content') or '') for x in event.get('choices', []))
                            if token:
                                output_chars += len(token)
                                yield token
                    # Some proxies omit final newline; parse remaining complete frame.
                    if buffered:
                        try:
                            event = json.loads('\n'.join(buffered))
                            capture_usage(event)
                            if kind == 'anthropic': token = event.get('delta',{}).get('text','')
                            elif kind == 'gemini': token = ''.join(x.get('text','') for x in event.get('candidates',[{}])[0].get('content',{}).get('parts', []))
                            else: token = ''.join(str(x.get('delta',{}).get('content') or '') for x in event.get('choices',[]))
                            if token:
                                output_chars += len(token)
                                yield token
                        except json.JSONDecodeError:
                            pass
            finish_usage()
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError('timeout', 'Tempo limite excedido.', True)
        except httpx.TransportError as exc:
            raise ProviderError('network', f'Erro de conexão: {str(exc)[:120]}', True)
