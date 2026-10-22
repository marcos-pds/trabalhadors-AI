"""Testador IA: deterministic checks before approval and before preview."""
from fastapi.testclient import TestClient
from test_workspace import setup,prepare,add_provider,wait_for,HEADERS
from central.main import app,ENGINE,RUNTIME
from central.quality import inspect_sources,inspect_project
from central.roles import worker_role


def test_catches_loading_spinner_named_import_against_default_export():
    proposed={
      'frontend/src/App.tsx':
          "import { LoadingSpinner } from './components/LoadingSpinner';\n"
          'export default function App(){ return <LoadingSpinner /> }',
      'frontend/src/components/LoadingSpinner.tsx':
          'export default function LoadingSpinner(){return <div>Carregando</div>}'
    }
    issues=inspect_sources(lambda path:None,proposed)
    assert len(issues)==1,issues
    assert 'LoadingSpinner' in issues[0]
    assert 'não existe' in issues[0]
    assert 'App.tsx' in issues[0]
    proposed['frontend/src/App.tsx']=proposed['frontend/src/App.tsx'].replace(
        '{ LoadingSpinner }','LoadingSpinner')
    assert inspect_sources(lambda path:None,proposed)==[]


def test_accepts_valid_named_reexports_types_and_default_exports():
    files={
      'frontend/src/api.ts':'''export interface Product {id:number}
export async function getProducts(){return []}
export {getProducts as products}''',
      'frontend/src/App.tsx':'''import type {Product} from "./api"
import { getProducts, products } from "./api"
import Component from "./components/Card"
export default function App(){return <main/>}''',
      'frontend/src/components/Card.tsx':
         'export const value = 1; export default function Component(){return <div/>}'
    }
    assert inspect_sources(lambda p:None,files)==[]


def test_chat_qa_reports_loading_spinner_without_mutating_disk(tmp_path):
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        RUNTIME.workspaces=ENGINE.workspaces
        front=folder/'frontend/src';(front/'components').mkdir(parents=True)
        appfile=front/'App.tsx'
        appfile.write_text("import { LoadingSpinner } from './components/LoadingSpinner';\n"
                           'export default function App(){return <LoadingSpinner />}')
        component=front/'components/LoadingSpinner.tsx'
        component.write_text('export default function LoadingSpinner(){return <span/>}')
        backend=folder/'backend';backend.mkdir()
        (backend/'main.py').write_text('from fastapi import FastAPI\napp=FastAPI()')
        before=(appfile.read_text(),component.read_text())
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()['id']
        result=c.get(f'/api/conversations/{convo}/quality')
        assert result.status_code==200,result.text
        payload=result.json()
        assert payload['status']=='failed'
        assert payload['checked_files']>=3
        assert 'LoadingSpinner' in ' '.join(payload['issues'])
        assert (appfile.read_text(),component.read_text())==before
        grant=c.post(f'/api/conversations/{convo}/runtime/access',headers=HEADERS,
                     json={'enabled':True})
        assert grant.status_code==200
        # Preflight detects the React error before checking prerequisites or spawning any process.
        blocked=c.post(f'/api/conversations/{convo}/runtime/start',headers=HEADERS)
        assert blocked.status_code==422,blocked.text
        assert 'Testador IA bloqueou' in blocked.json()['detail']
        assert 'LoadingSpinner' in blocked.json()['detail']
        assert RUNTIME.sessions=={}


def test_project_qa_reports_python_syntax_error(tmp_path):
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        RUNTIME.workspaces=ENGINE.workspaces
        back=folder/'backend';back.mkdir()
        (back/'main.py').write_text('def broken(:\n    pass')
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()['id']
        result=c.get(f'/api/conversations/{convo}/quality')
        assert result.status_code==200
        assert result.json()['status']=='failed'
        assert 'sintaxe Python' in str(result.json()['issues'])


def test_generated_bad_import_cannot_be_auto_applied_or_approved_by_architect(tmp_path):
    class ProducesBadImport:
        def __init__(self):self.reviews=0
        async def stream(self,provider,key,model,system,messages):
            if 'ARQUITETO REVISOR AUTORIZADO' in system:
                self.reviews+=1
                yield '{"decision":"approve","reason":"Ignoraria teste"}'
            else:
                yield '{"files":[{"path":"frontend/src/App.tsx",'
                yield '"content":"import { LoadingSpinner } from \\"./components/LoadingSpinner\\";'
                yield '\\nexport default function App(){return <LoadingSpinner />}"}]}'
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        comp=folder/'frontend/src/components/LoadingSpinner.tsx'
        comp.parent.mkdir(parents=True,exist_ok=True)
        comp.write_text('export default function LoadingSpinner(){return <div/>}')
        original=folder/'frontend/src/App.tsx'
        original.write_text('export default function App(){return <main>OK</main>}')
        cid=c.post('/api/conversations',json={'project_id':project},
                   headers=HEADERS).json()['id']
        c.post(f'/api/conversations/{cid}/architect-delegation',headers=HEADERS,
               json={'enabled':True})
        worker=next(x for x in c.get('/api/agents').json() if worker_role(x)=='frontend')
        fake=ProducesBadImport();ENGINE.client=fake
        result=c.post('/api/runs',json={'conversation_id':cid,'mode':'manual',
            'agent_ids':[worker['id']],'prompt':'Atualize o frontend/src/App.tsx.'},headers=HEADERS)
        assert result.status_code==200,result.text
        complete=wait_for(c,result.json()['id'])
        assert complete['status']=='completed',complete.get('error')
        assert fake.reviews==0
        assert original.read_text()=='export default function App(){return <main>OK</main>}'
        proposals=c.get(f'/api/projects/{project}/workspace').json()['proposals']
        assert any(x['status']=='pending' for x in proposals)
        assert 'QA Testador IA' in complete['output']
        assert 'LoadingSpinner' in complete['output']


def test_team_adds_testing_before_reviewer(tmp_path):
    with TestClient(app) as c:
        project=setup(c,tmp_path);prepare(c,project)
        agents=c.get('/api/agents').json()
        assigned=[x for x in agents if worker_role(x) in ('frontend','backend','review')]
        tester=next(x for x in agents if worker_role(x)=='testing')
        assert tester['name']=='Testador IA'
        from central.engine import create_plan
        # Team orchestration creates the test worker automatically at create_run.
        # We test the plan via a local run (no providers are needed to verify the nodes).
        from central.database import uid
        cid=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()['id']
        # Avoid scheduling an actual model call for this structural check.
        original=ENGINE.schedule
        ENGINE.schedule=lambda rid:None
        try:
            run_id=ENGINE.create_run(c.get('/api/me').json()['id'],cid,
               'Crie loja React e FastAPI e revise os testes.','team',
               [x['id'] for x in assigned])
            stages=ENGINE.db.all('SELECT * FROM steps WHERE run_id=?',(run_id,))
        finally:
            ENGINE.schedule=original
        test_step=next(x for x in stages if x['agent_id']==tester['id'])
        frontback={x['id'] for x in stages if x['agent_id'] in
                   [a['id'] for a in assigned if worker_role(a) in ('frontend','backend')]}
        assert set(__import__('json').loads(test_step['deps']))==frontback
        review=next(x for x in stages if x['agent_id']==next(
               a['id'] for a in assigned if worker_role(a)=='review'))
        assert test_step['id'] in __import__('json').loads(review['deps'])
