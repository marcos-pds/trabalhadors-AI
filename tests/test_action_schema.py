"""Structured provider output must remain executable by the tool parser."""
import asyncio
import json

import httpx
import pytest
from jsonschema import Draft202012Validator

from central.action_schema import ACTION_RESPONSE_SCHEMA
from central.agent_autonomy import parse_tool
from central.providers import ProviderClient


def delegation(**changes):
    command = {
        'action': 'delegate_task', 'recipient_agent_id': 'b' * 128,
        'title': 'Create API', 'instructions': 'Implement the local API with tests.',
        'request_id': 'backend-api-v1',
    }
    command.update(changes)
    return command


def test_structured_delegation_stream_reaches_parser(monkeypatch):
    command = delegation()
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        schema = payload['response_format']['json_schema']['schema']
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(command)
        requests.append(payload)
        event = {'choices': [{'delta': {'content': json.dumps(command)}}]}
        return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n',
                              headers={'content-type': 'text/event-stream'})

    original_client = httpx.AsyncClient
    monkeypatch.setattr('central.providers.httpx.AsyncClient',
                        lambda **kw: original_client(transport=httpx.MockTransport(respond), **kw))

    async def generate():
        tokens = [token async for token in ProviderClient().stream(
            {'kind': 'ollama', 'base_url': 'http://provider.test/v1',
             '_structured_actions': True}, '', 'local-model', 'Delegate work', [])]
        return parse_tool(''.join(tokens))

    assert asyncio.run(generate()) == command
    assert len(requests) == 1
    assert requests[0]['temperature'] == 0


@pytest.mark.parametrize('change', [
    {'title': 'ab'}, {'title': 'x' * 101},
    {'instructions': 'short'}, {'instructions': 'x' * 2501},
    {'request_id': 'bad id'}, {'request_id': 'x' * 81},
    {'recipient_agent_id': 'x' * 129},
])
def test_delegation_bounds_match_generation_and_runtime(change):
    command = delegation(**change)
    assert list(Draft202012Validator(ACTION_RESPONSE_SCHEMA).iter_errors(command))
    with pytest.raises(ValueError):
        parse_tool(json.dumps(command))


def test_runtime_still_rejects_missing_fields_and_whitespace():
    command = delegation(title='   ')
    # The generation schema is a constraint, not an authorization boundary.
    with pytest.raises(ValueError):
        parse_tool(json.dumps(command))
    command = delegation()
    del command['instructions']
    with pytest.raises(ValueError):
        parse_tool(json.dumps(command))
