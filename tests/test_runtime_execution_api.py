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
    async def request(body,*,client_ip='127.0.0.1',headers=True,runtime='gemini'):
        transport=httpx.ASGITransport(app=main.app,client=(client_ip,1234))
        async with httpx.AsyncClient(transport=transport,base_url='http://127.0.0.1',
                                    headers={'x-central-request':'1'} if headers else {}) as client:
            return await client.post('/api/runtimes/external/'+runtime+'/connect',json=body)
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
