"""Validate new provider HTTP requests without credentials or external calls."""
import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from central.providers import DEFAULT_ENDPOINTS, ProviderClient


@pytest.mark.parametrize('kind,model,url', [
    ('ollama', 'qwen2.5-coder:3b', 'http://127.0.0.1:11434/v1/chat/completions'),
    ('groq', 'openai/gpt-oss-20b', 'https://api.groq.com/openai/v1/chat/completions'),
    ('openrouter', 'openrouter/free', 'https://openrouter.ai/api/v1/chat/completions'),
    ('mistral', 'mistral-small-latest', 'https://api.mistral.ai/v1/chat/completions'),
    ('zai', 'glm-4.7-flash', 'https://api.z.ai/api/paas/v4/chat/completions'),
    ('modelscope', 'account/model', 'https://api-inference.modelscope.cn/v1/chat/completions'),
    ('siliconflow', 'account/model', 'https://api.siliconflow.com/v1/chat/completions'),
])
def test_provider_stream_request(kind, model, url):
    def respond(request):
        assert str(request.url) == url
        assert request.headers['Authorization'] == 'Bearer test-key'
        body = json.loads(request.content)
        assert body['model'] == model
        assert body['stream'] is True
        assert body['messages'] == [
            {'role': 'system', 'content': 'Be helpful'},
            {'role': 'user', 'content': 'Hello'},
        ]
        # Reasoning-only and usage-only frames must not break visible streaming.
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, text=(
            'data: {"choices":[{"delta":{"reasoning_content":"private"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[],"usage":{"total_tokens":3}}\n\n'
            'data: [DONE]\n\n'
        ))

    client_type = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        return client_type(*args, transport=httpx.MockTransport(respond), **kwargs)

    async def run():
        provider = {'kind': kind, 'base_url': DEFAULT_ENDPOINTS[kind]}
        with patch('central.providers.httpx.AsyncClient', side_effect=client_factory):
            return ''.join([token async for token in ProviderClient().stream(
                provider, 'test-key', model, 'Be helpful',
                [{'role': 'user', 'content': 'Hello'}],
            )])

    assert asyncio.run(run()) == 'Hello'


def test_openai_compatible_stream_reports_provider_token_usage():
    from central.token_usage import reset_usage_callback, set_usage_callback

    captured = []

    def respond(request):
        body = json.loads(request.content)
        assert body['stream_options'] == {'include_usage': True}
        return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, text=(
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":2,"total_tokens":11}}\n\n'
            'data: [DONE]\n\n'
        ))

    client_type = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        return client_type(*args, transport=httpx.MockTransport(respond), **kwargs)

    async def run():
        scope = set_usage_callback(captured.append)
        try:
            with patch('central.providers.httpx.AsyncClient', side_effect=client_factory):
                result = ''.join([part async for part in ProviderClient().stream(
                    {'kind': 'groq', 'base_url': DEFAULT_ENDPOINTS['groq']},
                    'key', 'test-model', 'System prompt',
                    [{'role': 'user', 'content': 'Hello'}],
                )])
                return result
        finally:
            reset_usage_callback(scope)

    assert asyncio.run(run()) == 'Hello'
    assert captured == [{'input_tokens': 9, 'output_tokens': 2, 'source': 'actual'}]
