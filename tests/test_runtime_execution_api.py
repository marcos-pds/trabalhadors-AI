import asyncio

import httpx
import pytest

from central.database import Database, utcnow
from central.engine import Engine
from central.security import Security


@pytest.fixture
def api(tmp_path, monkeypatch):
    import central.main as main
    from central import runtime_execution
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    monkeypatch.setenv('CENTRAL_JOB_MODE', 'api')
    db=Database(tmp_path/'api.sqlite');security=Security(db,tmp_path)
    for user in ('owner','other'):
        db.execute('INSERT INTO users VALUES(?,?,?,?)',(user,user+'@example.test','test',utcnow()))
    for ident,user,kind in [('source','owner','gemini'),('foreign','other','gemini'),('wrong','owner','groq')]:
        db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,api_key_enc,created_at) VALUES(?,?,?,?,?,?,?,?)',
                   (ident,user,ident,kind,'https://example.test','test-model',security.encrypt('source-fixture-key'),utcnow()))
    calls=[]
    monkeypatch.setattr(runtime_execution,'verify',lambda runtime: calls.append(runtime) or 'fixture-version')
    monkeypatch.setattr(main,'DB',db);monkeypatch.setattr(main,'SEC',security)
    monkeypatch.setattr(main,'ENGINE',Engine(db,security))
    monkeypatch.setitem(main.app.dependency_overrides,main.current_user,lambda:{'id':'owner'})
    async def request(body,*,client_ip='127.0.0.1',headers=True,runtime='gemini',action='connect'):
        transport=httpx.ASGITransport(app=main.app,client=(client_ip,1234))
        async with httpx.AsyncClient(transport=transport,base_url='http://127.0.0.1',
                                    headers={'x-central-request':'1'} if headers else {}) as client:
            return await client.post('/api/runtimes/external/'+runtime+'/'+action,json=body)
    yield db,security,calls,request
    db.close()


def test_connect_uses_owned_source_encrypts_key_and_creates_worker_reviewer_idempotently(api):
    db,security,calls,request=api
    body={'model':'test-model','source_provider_id':'source'}
    first=asyncio.run(request(body));assert first.status_code==200,first.text
    saved=first.json();assert saved['generation_tested'] is False
    assert saved['native_tools'] is False and saved['agent_id'] and saved['reviewer_id']
    assert 'source-fixture-key' not in first.text
    row=db.one('SELECT * FROM providers WHERE id=?',(saved['provider']['id'],))
    assert row['kind']=='gemini_cli'
    assert security.decrypt(row['api_key_enc'])=='source-fixture-key'
    assert row['api_key_enc']!='source-fixture-key'
    second=asyncio.run(request(body));assert second.status_code==200
    assert second.json()['provider']['id']==saved['provider']['id']
    assert db.one('SELECT COUNT(*) n FROM agents')['n']==2


@pytest.mark.parametrize('body,status',[
    ({'model':'test','source_provider_id':'foreign'},404),
    ({'model':'test','source_provider_id':'wrong'},422),
    ({'model':'test','source_provider_id':'source','api_key':'manual-fixture'},422),
    ({'model':'test'},422),
])
def test_invalid_or_foreign_credentials_never_start_runtime(api,body,status):
    db,_,calls,request=api
    assert asyncio.run(request(body)).status_code==status
    assert calls==[]
    assert db.one('SELECT COUNT(*) n FROM agents')['n']==0


def test_connect_requires_local_client_csrf_and_local_deployment(api,monkeypatch):
    _,_,calls,request=api
    body={'model':'test-model','source_provider_id':'source'}
    assert asyncio.run(request(body,headers=False)).status_code==403
    assert asyncio.run(request(body,client_ip='10.1.2.3')).status_code==403
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE','server')
    assert asyncio.run(request(body)).status_code==403
    assert calls==[]


def test_runtime_model_list_uses_owned_saved_key_without_cli_or_mutations(api, monkeypatch):
    import central.main as main
    db, _, calls, request = api
    seen = []
    async def discover(kind, key, **options):
        seen.append((kind, key, options))
        return [{'id':'gemini-text','name':'Text'}]
    monkeypatch.setattr(main, 'discover_models', discover)
    response = asyncio.run(request({'source_provider_id':'source'}, action='models', runtime='opencode'))
    assert response.status_code == 200
    assert response.json()['models'][0]['id'] == 'google/gemini-text'
    assert response.json()['generation_tested'] is False
    assert seen == [('gemini','source-fixture-key',{'runtime':True})]
    assert 'source-fixture-key' not in response.text
    assert calls == [] and db.one('SELECT COUNT(*) n FROM agents')['n'] == 0


@pytest.mark.parametrize('body,options,status', [
    ({'source_provider_id':'foreign'}, {}, 404),
    ({'source_provider_id':'wrong'}, {}, 422),
    ({'source_provider_id':'source','api_key':'secret'}, {}, 422),
    ({}, {}, 422),
    ({'api_key':'secret'}, {'headers':False}, 403),
    ({'api_key':'secret'}, {'client_ip':'10.1.2.3'}, 403),
])
def test_runtime_model_list_guards_before_network(api, monkeypatch, body, options, status):
    import central.main as main
    monkeypatch.setattr(main,'discover_models',lambda *a,**kw:pytest.fail('network'))
    assert asyncio.run(api[3](body,action='models',**options)).status_code == status


def test_runtime_model_list_redacts_upstream_errors(api, monkeypatch):
    import central.main as main
    from central.providers import ProviderError
    async def fail(*args, **kwargs):
        raise ProviderError('authentication','secret-key upstream body')
    monkeypatch.setattr(main,'discover_models',fail)
    response=asyncio.run(api[3]({'api_key':'secret-key'},action='models'))
    assert response.status_code==422
    assert 'secret-key' not in response.text and 'authentication' in response.text


def test_runtime_model_catalog_server_mode_never_contacts_provider(api, monkeypatch):
    import central.main as main
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE','server')
    monkeypatch.setattr(main,'discover_models',lambda *a,**kw:pytest.fail('network'))
    assert asyncio.run(api[3]({'api_key':'secret'},action='models')).status_code == 403
