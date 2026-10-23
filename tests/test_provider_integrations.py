"""Validate new provider HTTP requests without credentials or external calls."""
import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from central.providers import DEFAULT_ENDPOINTS, ProviderClient


@pytest.mark.parametrize('kind,model,url', [
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
