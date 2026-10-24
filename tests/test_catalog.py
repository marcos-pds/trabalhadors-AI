"""Catalog parsing and connection orchestration with immediate, network-free fakes."""
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException, Request

from central.catalog import candidates, discover_models, normalize_models, zero_price
from central.database import Database
from central.providers import ProviderError


def complete(coro):
    """These fakes never wait for I/O, so no OS socket-based event loop is needed."""
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value
    else:
        coro.close()
        raise AssertionError('Unexpected asynchronous I/O in an immediate fake')


@pytest.mark.parametrize('pricing,expected', [
    ({'prompt': '0', 'completion': '0'}, True),
    ({'prompt': '0', 'completion': '.1'}, False),
    ({'prompt': '0'}, False), (None, False),
    ({'prompt': 'NaN', 'completion': '0'}, False),
    ({'prompt': '0', 'completion': '0', 'request': '.1'}, False),
    ({'prompt': 'broken', 'completion': '0'}, False),
])
def test_zero_price_requires_complete_zero_pricing(pricing, expected):
    assert zero_price(pricing) is expected


def test_model_catalog_deduplicates_and_excludes_non_chat():
    models = normalize_models('mistral', [
        {'id': 'mistral-small-latest', 'name': 'Small', 'capabilities': {'completion_chat': True}},
        {'id': 'mistral-small-latest', 'name': 'Small'},
        {'id': 'mistral-embed'}, {'id': 'whisper-large-v3'},
        {'id': 'inactive', 'active': False},
        {'id': 'other', 'capabilities': {'completion_chat': False}}, None,
    ])
    assert [m['id'] for m in models] == ['mistral-small-latest']
    assert models[0]['name'] == 'Small'


def test_openrouter_never_infers_zero_price_from_free_suffix():
    models = normalize_models('openrouter', [
        {'id': 'unsafe:free'},
        {'id': 'paid', 'pricing': {'prompt': '0', 'completion': '0.01'}},
        {'id': 'safe:free', 'name': 'Safe', 'pricing': {'prompt': '0', 'completion': '0'}},
    ])
    assert [m['id'] for m in candidates(models, 'openrouter')] == ['safe:free']
    assert [m['id'] for m in candidates(models, 'openrouter', 'paid')] == ['paid']
    assert next(m for m in models if m['id'] == 'paid')['billing'] == 'paid'
    assert next(m for m in models if m['id'] == 'safe:free')['billing'] == 'free'


def test_gemini_filters_generation_methods_and_uses_explicit_free_ids():
    models = normalize_models('gemini', [
        {'name': 'models/gemini-3.5-flash-lite', 'displayName': 'Flash Lite',
         'supportedGenerationMethods': ['generateContent'], 'inputTokenLimit': 100000},
        {'name': 'models/future-flash-paid', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/embedding', 'supportedGenerationMethods': ['embedContent']},
    ])
    assert [m['id'] for m in candidates(models, 'gemini')] == ['gemini-3.5-flash-lite']
    assert models[0]['context_length'] == 100000


def mock_catalog(handler):
    original = httpx.AsyncClient
    return patch('central.catalog.httpx.AsyncClient',
                 side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def test_discovery_authenticates_and_paginates_gemini_without_key_in_url():
    calls = []
    def respond(request):
        calls.append(request)
        assert request.headers['x-goog-api-key'] == 'secret-key'
        assert 'secret-key' not in str(request.url)
        if len(calls) == 1:
            return httpx.Response(200, json={'models': [], 'nextPageToken': 'next'})
        assert request.url.params['pageToken'] == 'next'
        return httpx.Response(200, json={'models': [{'name': 'models/gemini-3.5-flash-lite',
                              'supportedGenerationMethods': ['generateContent']}]})
    with mock_catalog(respond):
        result = complete(discover_models('gemini', 'secret-key'))
    assert len(calls) == 2
    assert result[0]['eligible'] is True


def test_discovery_never_echoes_upstream_credentials():
    with mock_catalog(lambda request: httpx.Response(401, text='secret-key')):
        with pytest.raises(ProviderError) as err:
            complete(discover_models('groq', 'secret-key'))
    assert err.value.category == 'authentication'
    assert 'secret-key' not in str(err.value)


def test_zai_documented_fallback_is_labeled():
    with mock_catalog(lambda request: httpx.Response(404)):
        models = complete(discover_models('zai', 'secret-key'))
    assert {m['id'] for m in models} == {'glm-4.7-flash', 'glm-4.5-flash'}
    assert all('Documentação' in m['source'] for m in models)


@pytest.mark.parametrize('items', [[], [{'id': 'glm-5.3-flash'}], [{'id': 'glm-4.7-flash'}]])
def test_zai_supplements_incomplete_successful_catalog(items):
    with mock_catalog(lambda request: httpx.Response(200, json={'data': items})):
        models = complete(discover_models('zai', 'secret-key'))
    eligible = candidates(models, 'zai')
    assert {m['id'] for m in eligible} == {'glm-4.7-flash', 'glm-4.5-flash'}
    assert len({m['id'] for m in models}) == len(models)
    for model in eligible:
        if model['id'] not in {item['id'] for item in items}:
            assert 'Documentação' in model['source']


def test_zai_invalid_key_does_not_fall_back_to_documentation():
    with mock_catalog(lambda request: httpx.Response(401)):
        with pytest.raises(ProviderError) as error:
            complete(discover_models('zai', 'invalid'))
    assert error.value.category == 'authentication'


@pytest.fixture
def connection_app(monkeypatch):
    runtime = Path(__file__).resolve().parents[1] / 'data' / 'test-catalog-runtime'
    monkeypatch.setenv('CENTRAL_DATA_DIR', str(runtime))
    from central import main
    db = Database(':memory:')
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('user', 'user@test.local', 'hash', 'now'))
    monkeypatch.setattr(main, 'DB', db)
    from central.health import ProviderHealth
    monkeypatch.setattr(main.ENGINE, 'health', ProviderHealth(db))
    async def discover(kind, key):
        return normalize_models(kind, [{'id': 'chat-model'}])
    monkeypatch.setattr(main, 'discover_models', discover)
    yield main, db
    db.close()


def request():
    return Request({'type': 'http', 'method': 'POST', 'scheme': 'http',
                    'path': '/', 'headers': [(b'x-central-request', b'1')],
                    'server': ('testserver', 80)})


def test_connection_rejects_duplicate_without_testing_again(connection_app, monkeypatch):
    main, db = connection_app
    calls = []
    async def stream(*args):
        calls.append(args)
        yield 'OK'
    monkeypatch.setattr(main.ENGINE.client, 'stream', stream)
    data = main.QuickProviderIn(kind='groq', api_key='secret-key')
    first = complete(main.connect_provider(data, request(), {'id': 'user'}))
    with pytest.raises(HTTPException) as error:
        complete(main.connect_provider(data, request(), {'id': 'user'}))
    assert error.value.status_code == 409
    assert len(calls) == 1
    assert len(db.all('SELECT * FROM providers')) == 1
    assert 'secret-key' not in json.dumps(first)
    assert db.one('SELECT api_key_enc FROM providers')['api_key_enc'] != 'secret-key'
    assert first['provider']['health']['state'] == 'healthy'


def test_manual_create_and_edit_reject_duplicates_including_paused(connection_app):
    main, db = connection_app
    user = {'id': 'user'}
    data = main.ProviderIn(name='First', kind='groq', model=' model-a ', enabled=False)
    first = main.add_provider(data, user)
    with pytest.raises(HTTPException) as error:
        main.add_provider(main.ProviderIn(name='Duplicate', kind='groq', model='model-a'), user)
    assert error.value.status_code == 409
    second = main.add_provider(main.ProviderIn(name='Second', kind='groq', model='model-b'), user)
    with pytest.raises(HTTPException) as error:
        main.update_provider(second['id'], main.ProviderIn(name='Collision', kind='groq', model='model-a'), user)
    assert error.value.status_code == 409
    updated = main.update_provider(first['id'], main.ProviderIn(name='Renamed', kind='groq', model='model-a'), user)
    assert updated['name'] == 'Renamed'
    assert len(db.all('SELECT * FROM providers')) == 2
    # The same identifier at another provider is a distinct connection.
    main.add_provider(main.ProviderIn(name='Other provider', kind='mistral', model='model-a'), user)


def test_duplicate_check_is_scoped_to_account(connection_app):
    main, db = connection_app
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('other', 'other@test.local', 'hash', 'now'))
    main.add_provider(main.ProviderIn(name='First', kind='groq', model='model-a'), {'id': 'user'})
    main.add_provider(main.ProviderIn(name='Other', kind='groq', model='model-a'), {'id': 'other'})
    assert len(db.all('SELECT * FROM providers')) == 2


def test_catalog_marks_existing_connections(connection_app):
    main, _ = connection_app
    main.add_provider(main.ProviderIn(name='Existing', kind='groq', model='chat-model'), {'id': 'user'})
    result = complete(main.provider_models(main.QuickProviderIn(kind='groq', api_key='key'), request(), {'id': 'user'}))
    assert result['models'][0]['connected'] is True


def test_failed_connection_does_not_save_or_leak_key(connection_app, monkeypatch):
    main, db = connection_app
    async def stream(*args):
        raise ProviderError('authentication', 'Invalid secret-key')
        yield  # async generator interface
    monkeypatch.setattr(main.ENGINE.client, 'stream', stream)
    with pytest.raises(HTTPException) as error:
        complete(main.connect_provider(main.QuickProviderIn(kind='groq', api_key='secret-key'), request(), {'id': 'user'}))
    assert 'secret-key' not in error.value.detail
    assert db.all('SELECT * FROM providers') == []


def test_saved_key_requires_ownership(connection_app):
    main, db = connection_app
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('other', 'other@test.local', 'hash', 'now'))
    db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) VALUES(?,?,?,?,?,?,?)',
               ('private', 'other', 'Private', 'groq', 'https://example.com', 'model', 'now'))
    with pytest.raises(HTTPException) as error:
        main.quick_key(main.QuickProviderIn(kind='groq', provider_id='private'), {'id': 'user'})
    assert error.value.status_code == 404


def test_connection_requires_csrf(connection_app):
    main, _ = connection_app
    bad_request = Request({'type': 'http', 'method': 'POST', 'headers': []})
    with pytest.raises(HTTPException) as error:
        complete(main.connect_provider(main.QuickProviderIn(kind='groq'), bad_request, {'id': 'user'}))
    assert error.value.status_code == 403


def test_automatic_connection_tries_next_eligible_model(connection_app, monkeypatch):
    main, db = connection_app
    async def discover(kind, key):
        return normalize_models(kind, [{'id': 'a'}, {'id': 'b'}])
    calls = []
    async def stream(provider, key, model, *args):
        calls.append(model)
        if model == 'a':
            raise ProviderError('rate_limit', 'Quota exhausted', True)
        yield 'OK'
    monkeypatch.setattr(main, 'discover_models', discover)
    monkeypatch.setattr(main.ENGINE.client, 'stream', stream)
    result = complete(main.connect_provider(main.QuickProviderIn(kind='groq', api_key='key'), request(), {'id': 'user'}))
    assert calls == ['a', 'b']
    assert result['model']['id'] == 'b'
    assert len(db.all('SELECT * FROM providers')) == 1


def test_no_eligible_model_never_calls_inference(connection_app, monkeypatch):
    main, db = connection_app
    async def discover(kind, key):
        return normalize_models(kind, [{'id': 'paid', 'pricing': {'prompt': '1', 'completion': '2'}}])
    monkeypatch.setattr(main, 'discover_models', discover)
    with pytest.raises(HTTPException) as error:
        complete(main.connect_provider(main.QuickProviderIn(kind='openrouter', api_key='key'), request(), {'id': 'user'}))
    assert 'Nenhum modelo' in error.value.detail
    assert db.all('SELECT * FROM providers') == []


def test_local_connection_leaves_only_one_ollama_active(connection_app, monkeypatch):
    main, db = connection_app
    db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) VALUES(?,?,?,?,?,?,?)',
               ('old', 'user', 'Old local', 'ollama', 'http://127.0.0.1:11434/v1', 'old-model', 'now'))
    async def stream(*args):
        yield 'OK'
    monkeypatch.setattr(main.ENGINE.client, 'stream', stream)
    complete(main.connect_provider(main.QuickProviderIn(kind='ollama'), request(), {'id': 'user'}))
    active = db.all("SELECT * FROM providers WHERE kind='ollama' AND enabled=1")
    assert len(active) == 1
    assert active[0]['model'] == 'chat-model'
    assert len(db.all('SELECT * FROM providers')) == 2


def test_discovery_empty_key_and_unknown_provider_are_rejected():
    for kind, key in [('groq', ''), ('not-a-provider', 'key')]:
        with pytest.raises(ProviderError):
            complete(discover_models(kind, key))


def test_openrouter_discovery_uses_fixed_endpoint_and_bearer_auth():
    def respond(request):
        assert str(request.url) == 'https://openrouter.ai/api/v1/models'
        assert request.headers['Authorization'] == 'Bearer secret-key'
        return httpx.Response(200, json={'data': [{'id': 'free-model', 'pricing': {'prompt': '0', 'completion': '0'}}]})
    with mock_catalog(respond):
        models = complete(discover_models('openrouter', 'secret-key'))
    assert models[0]['eligible'] is True


def test_zai_manual_selection_can_use_non_free_catalog_model():
    models = normalize_models('zai', [{'id': 'glm-4.7-flash'}, {'id': 'glm-5.3'}, {'id': 'glm-5.3-flashx'}])
    assert {m['id'] for m in candidates(models, 'zai')} == {'glm-4.7-flash'}
    assert [m['id'] for m in candidates(models, 'zai', 'glm-5.3')] == ['glm-5.3']
    assert next(m for m in models if m['id'] == 'glm-5.3')['billing'] == 'unknown'


def test_manual_paid_model_is_connected_without_false_zero_price(connection_app, monkeypatch):
    main, db = connection_app

    async def discover(kind, key):
        return normalize_models(kind, [
            {'id': 'free', 'pricing': {'prompt': '0', 'completion': '0'}},
            {'id': 'paid', 'pricing': {'prompt': '1', 'completion': '2'}},
        ])

    calls = []

    async def stream(provider, key, model, *args):
        calls.append(model)
        yield 'OK'

    monkeypatch.setattr(main, 'discover_models', discover)
    monkeypatch.setattr(main.ENGINE.client, 'stream', stream)
    response = complete(main.connect_provider(
        main.QuickProviderIn(kind='openrouter', api_key='key', model='paid'),
        request(), {'id': 'user'}))
    assert calls == ['paid']
    assert response['model']['billing'] == 'paid'
    row = db.one('SELECT model,input_price,output_price FROM providers')
    assert row['model'] == 'paid'
    assert row['input_price'] is None
    assert row['output_price'] is None


def test_manual_model_must_be_in_discovered_catalog(connection_app, monkeypatch):
    main, db = connection_app
    with pytest.raises(HTTPException) as error:
        complete(main.connect_provider(
            main.QuickProviderIn(kind='groq', api_key='key', model='not-listed'),
            request(), {'id': 'user'}))
    assert 'não encontrado' in error.value.detail
    assert db.all('SELECT * FROM providers') == []


def test_sambanova_auto_uses_only_documented_free_tier_model_ids():
    models = normalize_models('sambanova', [
        {'id': 'MiniMax-M3.1-Flash'},
        {'id': 'DeepSeek-V3.1'},
        {'id': 'gpt-oss-120b'},
        {'id': 'gemma-4-31B-it'},
        {'id': 'another-unknown-model'},
    ])
    assert {m['id'] for m in candidates(models, 'sambanova')} == {
        'DeepSeek-V3.1', 'gpt-oss-120b', 'gemma-4-31B-it'
    }
    assert next(m for m in models if m['id'] == 'MiniMax-M3.1-Flash')['billing'] == 'unknown'
    assert [m['id'] for m in candidates(models, 'sambanova', 'MiniMax-M3.1-Flash')] == [
        'MiniMax-M3.1-Flash'
    ]


def test_sambanova_credit_error_does_not_try_other_models_or_save(connection_app, monkeypatch):
    main, db = connection_app
    async def discover(kind, key):
        return normalize_models(kind, [
            {'id': 'DeepSeek-V3.1'}, {'id': 'gpt-oss-120b'}
        ])
    attempted = []
    async def stream(provider, key, model, *args):
        attempted.append(model)
        raise ProviderError('credits', 'Créditos insuficientes.', False, 402)
        yield  # pragma: no cover

    monkeypatch.setattr(main, 'discover_models', discover)
    monkeypatch.setattr(main.ENGINE.client, 'stream', stream)
    with pytest.raises(HTTPException) as error:
        complete(main.connect_provider(
            main.QuickProviderIn(kind='sambanova', api_key='secret-key'),
            request(), {'id': 'user'}))
    assert error.value.status_code == 422
    assert 'SambaNova' in error.value.detail
    assert 'HTTP 402' in error.value.detail
    assert 'secret-key' not in error.value.detail
    assert attempted == ['DeepSeek-V3.1']
    assert db.all('SELECT * FROM providers') == []



def test_live_history_records_failed_model_and_next_candidate(connection_app, monkeypatch):
    main, db = connection_app

    async def discover(kind, key):
        return normalize_models(kind, [{'id': 'model-a'}, {'id': 'model-b'}])

    async def stream(provider, key, model, *args):
        if model == 'model-a':
            raise ProviderError('request', 'HTTP 400: secret-key invalid generation parameters', False, 400)
        yield 'OK'

    monkeypatch.setattr(main, 'discover_models', discover)
    monkeypatch.setattr(main.ENGINE.client, 'stream', stream)

    async def run():
        return [event async for event in main.connection_events(
            main.QuickProviderIn(kind='groq', api_key='secret-key'), {'id': 'user'}, 'secret-key')]

    events = complete(run())
    assert [e['type'] for e in events] == [
        'testing', 'failed', 'testing', 'passed', 'connected'
    ]
    first_failure = events[1]
    assert first_failure['model_id'] == 'model-a'
    assert first_failure['category'] == 'request'
    assert first_failure['http_status'] == 400
    assert first_failure['next_model'] == {'id': 'model-b', 'name': 'model-b'}
    assert 'HTTP 400' in first_failure['message']
    assert 'secret-key' not in json.dumps(events)
    assert events[3]['model_id'] == 'model-b'
    assert events[4]['model']['id'] == 'model-b'
    assert len(db.all('SELECT * FROM providers')) == 1


def test_streaming_endpoint_reports_failures_and_stops_after_credit_error(connection_app, monkeypatch):
    main, db = connection_app
    async def discover(kind, key):
        return normalize_models(kind, [{'id': 'model-a'}, {'id': 'model-b'}])

    attempted = []
    async def stream(provider, key, model, *args):
        attempted.append(model)
        raise ProviderError('credits', 'insufficient_quota secret-key', False, 402)
        yield  # pragma: no cover

    monkeypatch.setattr(main, 'discover_models', discover)
    monkeypatch.setattr(main.ENGINE.client, 'stream', stream)
    response = complete(main.connect_provider_stream(
        main.QuickProviderIn(kind='groq', api_key='secret-key'),
        request(), {'id': 'user'}))

    async def read_events():
        chunks = [chunk async for chunk in response.body_iterator]
        return [json.loads(chunk.removeprefix('data: ').strip()) for chunk in chunks]

    events = complete(read_events())
    assert response.media_type == 'text/event-stream'
    assert [e['type'] for e in events] == ['testing', 'failed', 'error']
    assert events[1]['next_model'] is None
    assert events[1]['http_status'] == 402
    assert 'secret-key' not in json.dumps(events)
    assert attempted == ['model-a']
    assert db.all('SELECT * FROM providers') == []


def test_streaming_connection_requires_csrf(connection_app):
    main, _ = connection_app
    bad_request = Request({'type': 'http', 'method': 'POST', 'headers': []})
    with pytest.raises(HTTPException) as error:
        complete(main.connect_provider_stream(
            main.QuickProviderIn(kind='groq', api_key='key'), bad_request, {'id': 'user'}))
    assert error.value.status_code == 403
