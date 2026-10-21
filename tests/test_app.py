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
    r=c.post('/api/providers',json={'name':name,'kind':'openai','model':'test-model',
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
        r=c.post('/api/runs',json={'conversation_id':cid,'prompt':'Crie frontend react e backend API login'},headers=HEADERS)
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
        r = c.post('/api/runs', json={'conversation_id':cid,'prompt':'Crie uma API'}, headers=HEADERS)
        rid = r.json()['id']
        assert wait_for(c,rid)['status']=='failed'
        add_provider(c,'restored',1)
        ENGINE.client=FakeClient()
        response = c.post(f'/api/runs/{rid}/resume',headers=HEADERS)
        assert response.status_code==200,response.text
        run = wait_for(c,rid)
        assert run['status']=='completed',run['error']
        assert all(s['status']=='completed' for s in run['steps'])
