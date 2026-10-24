"""Official provider catalogs. Listing a model does not establish its price or quota."""
from decimal import Decimal, InvalidOperation
import httpx

from .providers import DEFAULT_ENDPOINTS, ProviderError, classify_http


def entry(kind, name, access, note, keys, source, **extra):
    return dict(kind=kind, name=name, access=access, note=note, keys_url=keys,
                source_url=source, checked_at='2026-10-23', **extra)


CATALOG = [
    entry('groq', 'Groq', 'Faixa gratuita', 'Use uma conta no Free Plan. Limites variam por modelo.',
          'https://console.groq.com/keys', 'https://console.groq.com/docs/rate-limits', quick=True),
    entry('openrouter', 'OpenRouter', 'Modelos de preço zero', 'Somente modelos com preços de entrada e saída iguais a zero no catálogo. Há limites de uso.',
          'https://openrouter.ai/settings/keys', 'https://openrouter.ai/collections/free-models', quick=True),
    entry('gemini', 'Google AI Studio / Gemini', 'Faixa gratuita', 'Use um projeto sem faturamento. O catálogo não informa o plano da conta; a conexão automática usa uma lista conservadora de modelos com faixa gratuita.',
          'https://aistudio.google.com/app/apikey', 'https://ai.google.dev/gemini-api/docs/pricing', quick=True),
    entry('mistral', 'Mistral', 'Faixa gratuita', 'Ative o Studio em Free mode. A chave herda o plano da organização; o catálogo não confirma gratuidade da conta.',
          'https://console.mistral.ai/api-keys', 'https://docs.mistral.ai/admin/billing-usage/subscriptions', quick=True),
    entry('sambanova', 'SambaNova', 'Faixa gratuita', 'Free Tier disponível para contas sem método de pagamento. Há limites diários por modelo.',
          'https://cloud.sambanova.ai/apis', 'https://docs.sambanova.ai/docs/en/models/rate-limits', quick=True),
    entry('zai', 'Z.ai / GLM Flash', 'Modelos de preço zero', 'Somente GLM-4.7-Flash e GLM-4.5-Flash. FlashX e versões mais novas podem ser pagas.',
          'https://z.ai/manage-apikey/apikey-list', 'https://docs.z.ai/guides/overview/pricing', quick=True),
    entry('cloudflare', 'Cloudflare Workers AI', 'Cota diária', 'Exige token e Account ID. Use Workers Free; alguns modelos exigem plano pago. Configuração manual disponível.',
          'https://dash.cloudflare.com/profile/api-tokens', 'https://developers.cloudflare.com/workers-ai/platform/pricing/', quick=False),
    entry('huggingface', 'Hugging Face', 'Créditos mensais', 'Pequena cota mensal em créditos; não é uso ilimitado nem preço zero por modelo.',
          'https://huggingface.co/settings/tokens', 'https://huggingface.co/docs/inference-providers/pricing', quick=False),
    entry('cohere', 'Cohere', 'Avaliação', 'Chave trial gratuita e limitada para avaliação; não destinada a produção ou uso comercial.',
          'https://dashboard.cohere.com/api-keys', 'https://cohere.com/pricing', quick=False),
    entry('nvidia', 'NVIDIA NIM', 'Avaliação', 'Acesso de desenvolvimento sujeito às condições, limites e elegibilidade do API Catalog.',
          'https://build.nvidia.com/', 'https://docs.api.nvidia.com/nim/docs/product', quick=False),
    entry('cerebras', 'Cerebras', 'Crédito promocional', 'A página atual oferece crédito único com método de pagamento e validade. Não tratar como faixa gratuita recorrente.',
          'https://cloud.cerebras.ai/', 'https://www.cerebras.ai/pricing', quick=False),
    entry('modelscope', 'ModelScope', 'Verificar conta e região', 'API-Inference depende de modelos habilitados, cadastro e regras da conta. Gratuidade não confirmada pelo catálogo.',
          'https://modelscope.cn/my/myaccesstoken', 'https://modelscope.cn/docs/model-service/API-Inference/intro', quick=False),
    entry('siliconflow', 'SiliconFlow', 'Verificar conta e região', 'Preço e ofertas diferem por região e modelo. Não selecionar modelo automaticamente sem preço confirmado.',
          'https://cloud.siliconflow.com/account/ak', 'https://docs.siliconflow.com/', quick=False),
    entry('ollama', 'Ollama local', 'Local', 'Usa os modelos já instalados no computador. Sem chave API; mantenha o Ollama aberto.',
          'https://ollama.com/', 'https://docs.ollama.com/api/openai-compatibility', quick=True),
]
BY_KIND = {p['kind']: p for p in CATALOG}
# Explicit IDs, never infer free access from a model name containing "flash".
GEMINI_FREE = {'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'}
ZAI_FREE = {'glm-4.7-flash', 'glm-4.5-flash'}
NON_CHAT = ('embed', 'whisper', 'tts', 'transcrib', 'moderation', 'rerank', 'guard', 'orpheus', 'image', 'audio', 'video')


def zero_price(pricing):
    if not isinstance(pricing, dict):
        return False
    try:
        required = [Decimal(str(pricing[k])) for k in ('prompt', 'completion')]
        extras = [Decimal(str(v)) for k, v in pricing.items()
                  if k not in ('prompt', 'completion') and v is not None]
        return all(n.is_finite() and n == 0 for n in required + extras)
    except (KeyError, InvalidOperation, ValueError):
        return False


def normalize_models(kind, items):
    models = {}
    for item in items:
        if not isinstance(item, dict) or item.get('active') is False:
            continue
        mid = str(item.get('id') or item.get('name') or '')
        if kind == 'gemini':
            mid = mid.removeprefix('models/')
            if 'generateContent' not in item.get('supportedGenerationMethods', []):
                continue
        capabilities = item.get('capabilities') or {}
        if isinstance(capabilities, dict) and capabilities.get('completion_chat') is False:
            continue
        if not mid or len(mid) > 120 or any(s in mid.lower() for s in NON_CHAT):
            continue
        if kind == 'openrouter':
            modalities = (item.get('architecture') or {}).get('output_modalities', ['text'])
            if 'text' not in modalities:
                continue
            eligible = zero_price(item.get('pricing'))
        elif kind == 'gemini':
            eligible = mid in GEMINI_FREE
        elif kind == 'zai':
            eligible = mid in ZAI_FREE
        else:
            eligible = kind in ('groq', 'mistral', 'sambanova', 'ollama')
        models[mid] = dict(id=mid, name=item.get('displayName') or item.get('name') or mid,
                           source=item.get('_catalog_source', 'API do provedor'),
                           context_length=item.get('context_length') or item.get('inputTokenLimit')
                           or item.get('max_model_len'), eligible=eligible,
                           access='Elegível no plano gratuito' if eligible else 'Preço/plano não confirmado')
    return sorted(models.values(), key=lambda m: (not m['eligible'], m['id']))


async def discover_models(kind, api_key):
    if kind not in BY_KIND or not BY_KIND[kind]['quick']:
        raise ProviderError('catalog', 'Este provedor exige configuração manual; veja as condições no catálogo.')
    if kind != 'ollama' and not api_key.strip():
        raise ProviderError('authentication', 'Informe a chave API do provedor.')
    base = DEFAULT_ENDPOINTS[kind]
    headers = {'x-goog-api-key': api_key} if kind == 'gemini' else (
        {'Authorization': f'Bearer {api_key}'} if api_key else {})
    items = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8), follow_redirects=False) as client:
            params = {'pageSize': 1000} if kind == 'gemini' else {}
            seen = set()
            for _ in range(10):
                response = await client.get(base + '/models', headers=headers, params=params)
                # Some Z.ai deployments do not expose a model-list endpoint.
                # Clearly label documented IDs; only inference can validate access.
                if kind == 'zai' and response.status_code in (404, 405):
                    items = [{'id': mid, '_catalog_source': 'Documentação oficial; validar acesso no teste'}
                             for mid in sorted(ZAI_FREE)]
                    break
                if response.status_code >= 400:
                    raise classify_http(response.status_code, '')
                if response.status_code != 200:
                    raise ProviderError('catalog', 'O catálogo retornou uma resposta inesperada.')
                payload = response.json()
                batch = payload.get('models' if kind == 'gemini' else 'data', [])
                if not isinstance(batch, list):
                    raise ValueError('invalid catalog')
                items.extend(batch)
                token = payload.get('nextPageToken') if kind == 'gemini' else None
                if not token:
                    break
                if token in seen:
                    raise ProviderError('catalog', 'Paginação inválida no catálogo do provedor.')
                seen.add(token)
                params['pageToken'] = token
            else:
                raise ProviderError('catalog', 'Catálogo grande demais. Tente a configuração manual.')
        if kind == 'zai':
            # A successful list response may omit legacy free Flash models.
            # Supplement from documented IDs without claiming account availability.
            listed = {str(item.get('id') or item.get('name') or '')
                      for item in items if isinstance(item, dict)}
            items.extend({'id': mid, '_catalog_source': 'Documentação oficial; validar acesso no teste'}
                         for mid in sorted(ZAI_FREE - listed))
        return normalize_models(kind, items)
    except ProviderError:
        raise
    except httpx.TimeoutException:
        raise ProviderError('timeout', 'O catálogo demorou a responder. Tente novamente.', True)
    except httpx.TransportError:
        raise ProviderError('network', 'Não foi possível acessar o catálogo. Verifique a conexão e o serviço local.', True)
    except (ValueError, TypeError, AttributeError):
        raise ProviderError('catalog', 'O provedor retornou um catálogo inválido.')


def candidates(models, kind, selected=''):
    eligible = [m for m in models if m['eligible'] and (not selected or m['id'] == selected)]
    preferred = {'groq': ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant'],
                 'gemini': ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-2.5-flash-lite', 'gemini-2.5-flash'],
                 'mistral': ['mistral-small-latest'], 'zai': ['glm-4.7-flash', 'glm-4.5-flash'],
                 'ollama': ['qwen2.5-coder:3b', 'llama3.2:latest', 'llama3.2']}.get(kind, [])
    return sorted(eligible, key=lambda m: (preferred.index(m['id']) if m['id'] in preferred else 999, m['id']))
