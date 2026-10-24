"""Controlled provider fakes in tests only. Production has no fake AI paths."""
import asyncio
import os
import time
import uuid
from pathlib import Path
from tempfile import mkdtemp

# Set before importing the ASGI application: never touch a user's data folder.
os.environ['CENTRAL_DATA_DIR'] = mkdtemp(prefix='central-ia-test-')
from fastapi.testclient import TestClient
from central.main import app, ENGINE
from central.providers import ProviderError

HEADERS={'x-central-request':'1'}


def register(c):
    email=f'{uuid.uuid4().hex}@example.com'
    r=c.post('/api/register',json={'email':email,'password':'strongpasswordxyz'},headers=HEADERS)
    assert r.status_code==200, r.text
    return r.json()


def new_convo(c):
    r=c.post('/api/conversations',json={'title':'Nova conversa'},headers=HEADERS)
    assert r.status_code==200
    return r.json()['id']


def add_provider(c,name,priority):
    r=c.post('/api/providers',json={'name':name,'kind':'openai','model':'test-model-'+name,
    'api_key':'fake-key-no-real-requests','priority':priority,'base_url':'https://example.com/v1',
    'input_price':0.5,'output_price':1},headers=HEADERS)
    assert r.status_code==200,r.text
    return r.json()['id']


def wait_for(c,rid,statuses=('completed','failed'),timeout=5):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        run=c.get(f'/api/runs/{rid}').json()
        if run['status'] in statuses:return run
        time.sleep(.04)
    raise AssertionError('Run did not reach expected status: '+str(run['status']))


class FakeClient:
    def __init__(self, broken=False, delay=.005):
        self.broken=broken
        self.delay=delay
        self.active=0
        self.max_active=0
        self.called=[]

    async def stream(self,provider,key,model,system,messages):
        self.called.append(provider['name'])
        if self.broken and provider['name']=='offline':
            raise ProviderError('unavailable','Simulated upstream outage',False)
        self.active+=1
        self.max_active=max(self.max_active,self.active)
        try:
            await asyncio.sleep(self.delay)
            yield 'Resposta funcional de '+provider['name']
            await asyncio.sleep(self.delay)
            yield '. Texto completo.'
        finally:self.active-=1


def test_authenticated_workflow_and_isolation():
    with TestClient(app) as c1, TestClient(app) as c2:
        a=register(c1);b=register(c2)
        cid=new_convo(c1)
        assert c2.get(f'/api/conversations/{cid}/messages').status_code==404
        assert c2.get('/api/agents').status_code==200
        assert len(c1.get('/api/agents').json())==10
        assert c1.post('/api/providers',json={'name':'x'},headers={}).status_code==403
        assert len(c2.get('/api/conversations').json())==0


def test_parallel_run_and_reviewer_checkpoint():
    with TestClient(app) as c:
        register(c);add_provider(c,'healthy',1)
        fake=FakeClient(delay=.07);ENGINE.client=fake
        cid=new_convo(c)
        r=c.post('/api/runs',json={'conversation_id':cid,'prompt':'Analise frontend react e backend API login'},headers=HEADERS)
        assert r.status_code==200,r.text
        run=wait_for(c,r.json()['id'])
        assert run['status']=='completed',run.get('error')
        assert len(run['steps'])>=3
        assert any(s['name']=='Revisor IA' and len(__import__('json').loads(s['deps']))>=2 for s in run['steps'])
        assert fake.max_active>=2,'Independent workers did not execute in parallel'
        assert 'Resposta funcional de healthy' in run['output']
        assert all(s['status']=='completed' for s in run['steps'])
        msg=c.get(f'/api/conversations/{cid}/messages').json()
        assert len(msg)==2


def test_provider_failover_and_event_journal():
    with TestClient(app) as c:
        register(c)
        add_provider(c,'offline',1)
        add_provider(c,'healthy',2)
        fake=FakeClient(broken=True);ENGINE.client=fake
        cid=new_convo(c)
        r=c.post('/api/runs',json={'conversation_id':cid,'prompt':'Escreva uma função em Python'},headers=HEADERS)
        run=wait_for(c,r.json()['id'])
        assert run['status']=='completed',run.get('error')
        assert 'offline' in fake.called and 'healthy' in fake.called
        events=__import__('central.main',fromlist=['DB']).DB.all('SELECT event FROM events WHERE run_id=?',(run['id'],))
        assert any(ev['event']=='failover' for ev in events)
        assert 'healthy' in run['output']
        assert len(run['steps'])==1


def test_workflow_approval_and_rejection():
    with TestClient(app) as c:
        register(c);add_provider(c,'healthy',1)
        ENGINE.client=FakeClient()
        aid=c.get('/api/agents').json()[0]['id']
        flow={'nodes':[{'id':'step1','kind':'approval','name':'Revisão humana','deps':[]},
                       {'id':'step2','kind':'agent','name':'Arquiteto IA','agent_id':aid,'deps':['step1']}]}
        wf=c.post('/api/workflows',json={'name':'Aprovação','definition':flow},headers=HEADERS)
        assert wf.status_code==200,wf.text
        cid=new_convo(c)
        r=c.post('/api/runs',json={'conversation_id':cid,'prompt':'Aguardar aprovação', 'workflow_id':wf.json()['id']},headers=HEADERS)
        rid=r.json()['id']
        wait=wait_for(c,rid,statuses=('awaiting_approval',))
        assert wait['status']=='awaiting_approval'
        approve=c.post(f'/api/runs/{rid}/steps/step1/approval',json={'approved':True},headers=HEADERS)
        assert approve.status_code==200,approve.text
        assert wait_for(c,rid)['status']=='completed'


def test_budget_and_failed_run_without_fake_claim():
    with TestClient(app) as c:
        register(c)
        cid=new_convo(c)
        r=c.post('/api/runs',json={'conversation_id':cid,'prompt':'Olá'},headers=HEADERS)
        result=wait_for(c,r.json()['id'])
        assert result['status']=='failed'
        assert 'Nenhum provedor' in result['error']
        add_provider(c,'healthy',1)
        ENGINE.client=FakeClient()
        r=c.post('/api/runs',json={'conversation_id':cid,'prompt':'Explique uma API', 'budget_limit':0.0},headers=HEADERS)
        result=wait_for(c,r.json()['id'])
        assert result['status']=='failed'
        assert 'Orçamento' in result['error']


def test_cycle_validation_and_key_redaction():
    with TestClient(app) as c:
        register(c)
        p=add_provider(c,'secure',1)
        assert 'fake-key' not in str(c.get('/api/providers').json())
        aid=c.get('/api/agents').json()[0]['id']
        definition={'nodes':[{'id':'a','kind':'agent','name':'A','agent_id':aid,'deps':['b']},
                             {'id':'b','kind':'agent','name':'B','agent_id':aid,'deps':['a']}]}
        r=c.post('/api/workflows',json={'name':'Cycle','definition':definition},headers=HEADERS)
        assert r.status_code==422


def test_resume_after_provider_configuration_preserves_steps():
    with TestClient(app) as c:
        register(c)
        cid = new_convo(c)
        r = c.post('/api/runs', json={'conversation_id':cid,'prompt':'Explique a arquitetura de uma API'}, headers=HEADERS)
        rid = r.json()['id']
        assert wait_for(c,rid)['status']=='failed'
        add_provider(c,'restored',1)
        ENGINE.client=FakeClient()
        response = c.post(f'/api/runs/{rid}/resume',headers=HEADERS)
        assert response.status_code==200,response.text
        run = wait_for(c,rid)
        assert run['status']=='completed',run['error']
        assert all(s['status']=='completed' for s in run['steps'])



def test_project_memory_api_and_safe_cross_conversation_search():
    from central.main import DB
    with TestClient(app) as c, TestClient(app) as other:
        account = register(c)
        register(other)
        pa = c.post('/api/projects', json={'name': 'Portal Alpha', 'description': 'API e login'}, headers=HEADERS)
        pb = c.post('/api/projects', json={'name': 'Portal Beta'}, headers=HEADERS)
        assert pa.status_code == 200, pa.text
        assert pb.status_code == 200, pb.text
        a, b = pa.json()['id'], pb.json()['id']
        saved = c.put(f'/api/projects/{a}/memory', json={'notes': 'Decidido usar FastAPI e autenticação JWT.'}, headers=HEADERS)
        assert saved.status_code == 200 and 'JWT' in saved.json()['memory_notes']
        assert other.put(f'/api/projects/{a}/memory', json={'notes': 'invasão'}, headers=HEADERS).status_code == 404
        assert c.put(f'/api/projects/{a}/memory', json={'notes': 'x' * 8001}, headers=HEADERS).status_code == 422
        c1 = c.post('/api/conversations', json={'project_id': a, 'title': 'Login'}, headers=HEADERS).json()['id']
        c2 = c.post('/api/conversations', json={'project_id': b, 'title': 'Login Beta'}, headers=HEADERS).json()['id']
        c3 = new_convo(c)
        other_chat = new_convo(other)
        for cid, uid in [(c1, account['id']), (c2, account['id']), (c3, account['id'])]:
            DB.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, cid, uid, 'user', None,
                        'Discussimos autenticação com API REST e tokens.', 'now'))
        other_user_id = other.get('/api/me').json()['id']
        DB.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex, other_chat, other_user_id, 'user',
                    None, 'A API secreta é exclusiva do segundo usuário', 'now'))
        scoped = c.get('/api/conversations/search', params={'q': 'API', 'project_id': a}).json()
        assert {x['conversation_id'] for x in scoped} == {c1}
        broad = c.get('/api/conversations/search', params={'q': 'API', 'scope': 'all'}).json()
        assert {x['conversation_id'] for x in broad} == {c1, c2, c3}
        assert all(x['conversation_id'] != other_chat for x in broad)
        assert c.get('/api/conversations/search', params={'q': 'API', 'project_id': 'missing'}).status_code == 404
        assert other.get(f'/api/conversations/{c1}/context-policy').status_code == 404
        assert c.get(f'/api/conversations/{c3}/context-policy').json()['recent_message_limit'] == 6
        assert c.patch(f'/api/conversations/{c3}/project', json={'project_id': a}, headers=HEADERS).status_code == 200
        policy = c.get(f'/api/conversations/{c3}/context-policy').json()
        assert policy['recent_message_limit'] == 32
        assert policy['same_project_recall'] is True
        assert policy['cross_project_recall'] is False
        assert other.patch(f'/api/conversations/{c3}/project', json={'project_id': b}, headers=HEADERS).status_code == 404
        assert c.patch(f'/api/conversations/{c3}/project', json={'project_id': 'missing'}, headers=HEADERS).status_code == 404


def test_agents_receive_related_same_project_memories_but_not_other_projects():
    from central.main import DB
    with TestClient(app) as c:
        user = register(c)
        add_provider(c, 'healthy', 1)
        project = c.post('/api/projects', json={'name': 'Portal'}, headers=HEADERS).json()['id']
        other_project = c.post('/api/projects', json={'name': 'Fora'}, headers=HEADERS).json()['id']
        assert c.put(f'/api/projects/{project}/memory', json={'notes': 'Framework decidido: FastAPI'}, headers=HEADERS).status_code == 200
        earlier = c.post('/api/conversations', json={'project_id': project}, headers=HEADERS).json()['id']
        outsider = c.post('/api/conversations', json={'project_id': other_project}, headers=HEADERS).json()['id']
        current = c.post('/api/conversations', json={'project_id': project}, headers=HEADERS).json()['id']
        DB.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex, earlier, user['id'], 'user', None,
                    'No fluxo de login autenticação, escolhemos refresh token.', 'now'))
        DB.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex, outsider, user['id'], 'user', None,
                    'No fluxo de login autenticação, SENHA-DO-OUTRO-PROJETO', 'now'))

        class CapturingFake(FakeClient):
            inputs = []

            async def stream(self, provider, key, model, system, messages):
                self.inputs.append(messages[0]['content'])
                async for chunk in super().stream(provider, key, model, system, messages):
                    yield chunk

        capture = CapturingFake()
        ENGINE.client = capture
        first_agent = c.get('/api/agents').json()[0]['id']
        created = c.post('/api/runs', json={
            'conversation_id': current,
            'prompt': 'Revise o fluxo de autenticação e login.',
            'mode': 'manual', 'agent_ids': [first_agent]}, headers=HEADERS)
        assert created.status_code == 200, created.text
        run = wait_for(c, created.json()['id'])
        assert run['status'] == 'completed', run.get('error')
        assert len(capture.inputs) == 1
        sent = capture.inputs[0]
        assert 'Framework decidido: FastAPI' in sent
        assert 'refresh token' in sent
        assert 'SENHA-DO-OUTRO-PROJETO' not in sent
        assert 'Solicitação atual do usuário' in sent
        events = DB.all('SELECT event,payload FROM events WHERE run_id=?', (created.json()['id'],))
        assert any(e['event'] == 'memory_recalled' for e in events)


def test_explicit_software_delivery_cannot_silently_use_text_only_mode():
    """A coding request with Autonomia disabled must fail before saving a message."""
    with TestClient(app) as c:
        register(c)
        cid = new_convo(c)
        response = c.post('/api/runs', json={
            'conversation_id': cid,
            'prompt': 'Desenvolva uma landing page responsiva com React e testes.',
            'mode': 'team', 'autonomous': False,
        }, headers=HEADERS)
        assert response.status_code == 409, response.text
        assert 'Autonomia' in response.json()['detail']
        assert c.get(f'/api/conversations/{cid}/messages').json() == []


def test_architect_alone_cannot_claim_a_coding_delivery(monkeypatch):
    """The run must be rejected before the engine schedules a text-only worker."""
    from central.main import DB
    from central.engine import Engine
    from central.database import uid
    from central.security import Security
    with TestClient(app) as c:
        registered = register(c)
        cid = new_convo(c)
        agents = c.get('/api/agents').json()
        architect = next(a for a in agents if a['specialty'] == 'architecture')
        engine = Engine(DB, None)
        import asyncio
        async def attempt():
            with __import__('pytest').raises(ValueError, match='Programador'):
                engine.create_run(registered['id'], cid,
                                  'Implemente a landing page NOVA STUDIO.',
                                  'manual', agent_ids=[architect['id']], autonomous=True)
        asyncio.run(attempt())
