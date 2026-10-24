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
    assert candidates(models, 'openrouter', 'paid') == []


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
