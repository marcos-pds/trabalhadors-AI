import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest

from central import acceptance_providers as ap
from central.providers import ProviderError


SECRET = 'fixture-secret-not-a-real-key'


@pytest.fixture
def source(tmp_path):
    key = Fernet.generate_key()
    (tmp_path / 'secret.key').write_bytes(key)
    db = sqlite3.connect(tmp_path / 'central.sqlite3')
    db.execute('CREATE TABLE providers(id TEXT,user_id TEXT,kind TEXT,model TEXT,base_url TEXT,api_key_enc TEXT,priority INTEGER,input_price REAL,output_price REAL,enabled INTEGER)')
    encrypted = Fernet(key).encrypt(SECRET.encode()).decode()
    for ident, kind, model in [('allowed', 'groq', 'qwen-test'), ('native', 'codex_cli', 'test'),
                               ('oauth', 'openai_chatgpt', 'test'), ('disguised', 'openai', 'codex-test')]:
        db.execute('INSERT INTO providers VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (ident, 'owner', kind, model, 'https://api.example.test/v1', encrypted, 1, None, None, 1))
    db.commit(); db.close()
    return tmp_path


def test_read_only_source_descriptors_exclude_native_and_credentials(source):
    path = source / 'central.sqlite3'
    before = hashlib.sha256(path.read_bytes()).digest()
    selected = ap.SourceProviders.load(source)
    assert len(selected.descriptors) == 1
    descriptor = selected.descriptors[0]
    assert descriptor['kind'] == 'groq' and descriptor['base_url'] == ap.LAB_BASE_URL
    assert descriptor['input_price'] is None
    serialized = json.dumps(selected.descriptors)
    assert SECRET not in serialized and 'api_key' not in serialized and 'api.example.test' not in serialized
    assert before == hashlib.sha256(path.read_bytes()).digest()
    descriptor['kind'] = 'codex_cli'
    assert selected.descriptors[0]['kind'] == 'groq'
    with pytest.raises(ValueError):
        ap.SourceProviders.load(source, kinds={'codex_cli'})


def test_bridge_uses_only_selected_api_redacts_echoes_and_enforces_call_limit(source, monkeypatch):
    calls = []

    class Client:
        async def stream(self, provider, key, model, system, messages):
            assert provider['_structured_actions'] is True
            calls.append((provider['kind'], model, key))
            yield 'before ' + SECRET[:10]
            yield SECRET[10:] + ' after'

    monkeypatch.setattr(ap, 'ProviderClient', Client)
    selected = ap.SourceProviders.load(source)
    descriptor = dict(selected.descriptors[0], _structured_actions=True)
    client = selected.client(max_calls=1)

    async def exercise():
        output = ''.join([part async for part in client.stream(descriptor, 'ignored', descriptor['model'], '', [])])
        assert output == 'before [redacted] after'
        with pytest.raises(ProviderError, match='Limite'):
            await anext(client.stream(descriptor, '', descriptor['model'], '', []))
        with pytest.raises(ProviderError, match='difere'):
            await anext(client.stream(dict(descriptor, kind='codex_cli'), '', descriptor['model'], '', []))

    asyncio.run(exercise())
    assert calls == [('groq', 'qwen-test', SECRET)]
    assert client.calls == 1


def test_tasklab_prepare_has_no_credentials_or_application_source(source, tmp_path, monkeypatch, capsys):
    from examples import validate_api_tasklab as lab
    selected = ap.SourceProviders.load(source)
    monkeypatch.setattr(lab, 'providers', lambda args: selected)
    monkeypatch.setenv('CENTRAL_JOB_MODE', 'api')
    monkeypatch.delenv('CENTRAL_SECRET_KEY', raising=False)
    destination = tmp_path / 'isolated lab'
    args = SimpleNamespace(destination=destination, source_user=None, max_calls=2)
    asyncio.run(lab.prepare(args))
    output = capsys.readouterr().out
    assert SECRET not in output
    state = lab.state_at(destination)
    assert state['codex_allowed'] is False
    assert state['application_source_written_by_harness'] is False
    connection = sqlite3.connect(destination / 'data/central.sqlite3')
    try:
        assert connection.execute('SELECT COUNT(*) FROM providers WHERE api_key_enc IS NOT NULL').fetchone()[0] == 0
        assert connection.execute('SELECT DISTINCT kind FROM providers').fetchall() == [('groq',)]
        assert connection.execute('SELECT COUNT(*) FROM agents').fetchone()[0] == 5
    finally:
        connection.close()
    assert not (destination / 'workspace/backend/main.py').exists()
    assert not (destination / 'workspace/frontend/src/App.tsx').exists()
    assert (destination / 'data/secret.key').read_bytes() != (source / 'secret.key').read_bytes()


def test_source_owner_must_be_unambiguous_and_bad_credentials_are_sanitized(source, monkeypatch):
    db = sqlite3.connect(source / 'central.sqlite3')
    db.execute("INSERT INTO providers SELECT 'other', 'second-owner', kind,model,base_url,api_key_enc,priority,input_price,output_price,enabled FROM providers WHERE id='allowed'")
    db.commit(); db.close()
    with pytest.raises(ValueError, match='proprietario'):
        ap.SourceProviders.load(source)
    selected = ap.SourceProviders.load(source, user_id='owner')
    descriptor = selected.descriptors[0]
    (source / 'secret.key').write_text('not-a-key')

    async def exercise():
        with pytest.raises(ProviderError) as error:
            await anext(selected.client().stream(descriptor, '', descriptor['model'], '', []))
        assert error.value.category == 'authentication'
        assert SECRET not in str(error.value) and 'not-a-key' not in str(error.value)

    asyncio.run(exercise())


def test_revoked_provider_is_blocked_before_network_even_with_existing_snapshot(source, monkeypatch):
    selected = ap.SourceProviders.load(source)
    descriptor = selected.descriptors[0]
    client = selected.client()
    connection = sqlite3.connect(source / 'central.sqlite3')
    connection.execute("UPDATE providers SET enabled=0 WHERE id='allowed'")
    connection.commit(); connection.close()
    monkeypatch.setattr(ap, 'ProviderClient', lambda: pytest.fail('Network client must not be created'))

    async def exercise():
        with pytest.raises(ProviderError) as error:
            await anext(client.stream(descriptor, '', descriptor['model'], '', []))
        assert error.value.category == 'acceptance_policy'

    asyncio.run(exercise())


def test_total_stream_deadline_closes_upstream_for_provider_failover(source, monkeypatch):
    closed = []

    class Client:
        async def stream(self, *args):
            try:
                while True:
                    yield 'keepalive'
                    await asyncio.sleep(.001)
            finally:
                closed.append(True)

    monkeypatch.setattr(ap, 'ProviderClient', Client)
    selected = ap.SourceProviders.load(source)
    descriptor = selected.descriptors[0]

    async def exercise():
        with pytest.raises(ProviderError) as error:
            async for _ in selected.client(timeout=.02).stream(descriptor, '', descriptor['model'], '', []):
                pass
        assert error.value.category == 'timeout' and error.value.retryable

    asyncio.run(exercise())
    assert closed == [True]
