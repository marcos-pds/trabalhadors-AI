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



def test_vite_css_import_is_valid_when_css_is_part_of_same_pending_proposals():
    """Reported on Windows: pending index.css was wrongly ignored as non-TypeScript."""
    files={
        'frontend/src/App.tsx': (
            'import LoadingSpinner from "./components/LoadingSpinner";\n'
            'export default function App(){ return <LoadingSpinner /> }'),
        'frontend/src/components/LoadingSpinner.tsx': (
            'export default function LoadingSpinner(){ return <div>Carregando</div> }'),
        'frontend/src/main.tsx': (
            'import "./index.css";\n'
            'import App from "./App";\n'
            'export default App;'),
        'frontend/src/index.css': (
            'body { margin: 0; background: #fff; }\n')
    }
    assert inspect_sources(lambda _:None,files)==[]
    # Removing the CSS proposal before it exists on disk is a REAL error.
    without_css={path:source for path,source in files.items() if not path.endswith('.css')}
    assert inspect_sources(lambda _:None,without_css)==[
        'frontend/src/main.tsx: módulo relativo não encontrado: ./index.css']
    # A CSS already saved on disk also satisfies the import.
    assert inspect_sources(
        lambda name: files.get(name) if name=='frontend/src/index.css' else None,
        without_css)==[]


def test_vite_css_modules_do_not_need_typescript_default_export():
    proposed={
      'frontend/src/App.tsx':
         'import styles from "./App.module.css";\nexport default function App(){return styles.root}',
      'frontend/src/App.module.css':'.root {display: block}',
      'frontend/src/main.tsx':'import "./index.css";\nimport App from "./App";',
      'frontend/src/index.css':'body{margin:0}'
    }
    assert inspect_sources(lambda _:None,proposed)==[]


def test_vite_css_not_confused_with_missing_named_react_export():
    files={
        'frontend/src/main.tsx':
            'import "./index.css";\nimport { LoadingSpinner } from "./components/LoadingSpinner";',
        'frontend/src/index.css':'body{margin:0}',
        'frontend/src/components/LoadingSpinner.tsx':
            'export default function LoadingSpinner(){return <span/>}'
    }
    issues=inspect_sources(lambda _:None,files)
    assert len(issues)==1 and 'LoadingSpinner' in issues[0]
    assert 'index.css' not in issues[0]


def test_repaired_react_files_with_new_css_are_staged_for_review_without_false_qa(tmp_path):
    """Same scenario as Windows output: proposed LoadingSpinner, main.tsx, index.css.

    Existing files must stay untouched, proposals must stay pending, and no
    unsupported TypeScript-only QA error should be raised for the CSS import.
    """
    import json
    class ReactRepair:
        async def stream(self,provider,key,model,system,messages):
            yield json.dumps({'files':[
                {'path':'frontend/src/components/LoadingSpinner.tsx',
                 'content':'export function LoadingSpinner(){return <span>Carregando</span>}'},
                {'path':'frontend/src/main.tsx',
                 'content':'import "./index.css";\nimport App from "./App";\nexport default App;'},
                {'path':'frontend/src/index.css',
                 'content':'body {margin: 0;}'}
            ]})
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        root=folder/'frontend/src'
        (root/'components').mkdir(parents=True,exist_ok=True)
        appfile=root/'App.tsx'
        appfile.write_text(
            'import { LoadingSpinner } from "./components/LoadingSpinner";\n'
            'export default function App(){return <LoadingSpinner />;}')
        component=root/'components/LoadingSpinner.tsx'
        component.write_text('export default function LoadingSpinner(){return <span/>}')
        main=root/'main.tsx'
        main.write_text('import "./index.css";\nimport App from "./App";\nexport default App;')
        original=(component.read_text(),main.read_text())
        worker=next(a for a in c.get('/api/agents').json()
                    if worker_role(a)=='frontend')
        cid=c.post('/api/conversations',json={'project_id':project},
                   headers=HEADERS).json()['id']
        ENGINE.client=ReactRepair()
        run=c.post('/api/runs',json={
            'conversation_id':cid,'mode':'manual','agent_ids':[worker['id']],
            'prompt':'Corrija os erros QA dos imports LoadingSpinner e index.css.'},
            headers=HEADERS)
        assert run.status_code==200,run.text
        done=wait_for(c,run.json()['id'])
        assert done['status']=='completed',done.get('error')
        assert 'QA Testador IA: frontend/src/main.tsx' not in done['output']
        assert 'Aguardando revisão e aprovação' in done['output']
        proposals=c.get(f'/api/projects/{project}/workspace').json()['proposals']
        pending=[p for p in proposals if p['status']=='pending']
        paths={part['path'] for p in pending for part in p['files']}
        assert paths=={
          'frontend/src/components/LoadingSpinner.tsx',
          'frontend/src/main.tsx','frontend/src/index.css'}
        assert (component.read_text(),main.read_text())==original
        assert not (root/'index.css').exists()



def test_scans_lucide_react_import_from_local_product_card():
    """Regressão Windows: Vite could not resolve lucide-react in ProductCard.tsx."""
    from central.quality import inspect_npm_imports
    changes={'frontend/src/components/ProductCard.tsx':
             'import { ShoppingCart, Star } from "lucide-react";\n'
             'export function ProductCard(){return null}'}
    pkg={'dependencies':{'react':'^18.0.0'}}
    problems,missing=inspect_npm_imports(changes,pkg,installed=lambda p:False,check_installed=True)
    assert missing==['lucide-react']
    assert len(problems)==1 and 'ProductCard.tsx' in problems[0]
    assert 'dependência npm não declarada: lucide-react' in problems[0]
    declared={'dependencies':{'lucide-react':'^0.500.0'}}
    problems,missing=inspect_npm_imports(changes,declared,installed=lambda p:False,check_installed=True)
    assert missing==['lucide-react']
    assert 'não instalada' in problems[0]
    assert inspect_npm_imports(changes,declared,installed=lambda p:True,check_installed=True)==([],[])


def test_project_qa_reads_real_product_card_and_package_manifest(tmp_path):
    import json
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        RUNTIME.workspaces=ENGINE.workspaces
        component=folder/'frontend/src/components/ProductCard.tsx'
        component.parent.mkdir(parents=True,exist_ok=True)
        component.write_text('import { ShoppingCart, Star } from "lucide-react";\n'
                             'export function ProductCard(){return null}')
        pkg=folder/'frontend/package.json'
        pkg.write_text(json.dumps({'dependencies':{'react':'^18'}}))
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()['id']
        response=c.get(f'/api/conversations/{convo}/quality')
        assert response.status_code==200,response.text
        data=response.json()
        assert data['status']=='failed'
        assert data['missing_packages']==['lucide-react']
        assert 'ProductCard.tsx' in ' '.join(data['issues'])
        assert 'não declarada' in ' '.join(data['issues'])
        assert pkg.read_text()==json.dumps({'dependencies':{'react':'^18'}})
        # No package installation until an explicit post with authorization.
        assert not (folder/'frontend/node_modules/lucide-react').exists()


def test_dependency_install_requires_user_click_and_current_qa_evidence(tmp_path,monkeypatch):
    import json
    from central.main import ENGINE as engine
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        RUNTIME.workspaces=ENGINE.workspaces
        front=folder/'frontend';component=front/'src/components/ProductCard.tsx'
        component.parent.mkdir(parents=True,exist_ok=True)
        component.write_text('import {ShoppingCart,Star} from "lucide-react";\n'
                             'export const ProductCard=()=>null')
        manifest=front/'package.json';manifest.write_text('{"dependencies":{"react":"^18"}}')
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()['id']
        endpoint=f'/api/conversations/{convo}/dependencies/install'
        calls=[]
        def safe_fake_install(user_id,pid,manager,packages):
            calls.append((pid,manager,packages))
            new=front/'node_modules/lucide-react'
            new.mkdir(parents=True)
            (new/'package.json').write_text('{"name":"lucide-react"}')
            manifest.write_text(json.dumps({'dependencies':{'react':'^18','lucide-react':'^0.5'}}))
            return {'ok':True,'manager':manager,'packages':packages,'exit_code':0,'output':'mocked install'}
        monkeypatch.setattr(engine.skills,'_install_sync',safe_fake_install)
        assert c.post(endpoint,json={'package':'lucide-react'}).status_code==403
        assert c.post(endpoint,json={'package':'unapproved-library'},headers=HEADERS).status_code==403
        assert calls==[]
        approved=c.post(endpoint,json={'package':'lucide-react'},headers=HEADERS)
        assert approved.status_code==200,approved.text
        assert approved.json()['result']['ok']
        assert approved.json()['quality']['missing_packages']==[]
        assert calls==[(project,'npm',['lucide-react'])]
        assert c.post(endpoint,json={'package':'lucide-react'},headers=HEADERS).status_code==409
        assert len(calls)==1


def test_dependency_install_is_not_accessible_to_other_user(tmp_path,monkeypatch):
    from test_workspace import register
    with TestClient(app) as owner, TestClient(app) as attacker:
        project=setup(owner,tmp_path);prepare(owner,project)
        RUNTIME.workspaces=ENGINE.workspaces
        register(attacker)
        convo=owner.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()['id']
        endpoint=f'/api/conversations/{convo}/dependencies/install'
        assert attacker.post(endpoint,json={'package':'lucide-react'},
                             headers=HEADERS).status_code==404


def test_worker_receives_product_card_and_package_json_on_dependency_error(tmp_path):
    import json
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        src=folder/'frontend/src/components/ProductCard.tsx'
        src.parent.mkdir(parents=True,exist_ok=True)
        src.write_text('import {Star} from "lucide-react";\nexport const ProductCard=()=>null')
        (folder/'frontend/package.json').write_text(json.dumps({'dependencies':{'react':'^18'}}))
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()['id']
        context=ENGINE.workspaces.prompt(c.get('/api/me').json()['id'],convo,
            request='Corrija frontend/src/components/ProductCard.tsx: '
                    'dependência npm ausente lucide-react')
        assert '=== INÍCIO DO ARQUIVO EXISTENTE: frontend/src/components/ProductCard.tsx' in context
        assert '=== INÍCIO DO ARQUIVO EXISTENTE: frontend/package.json' in context
        assert 'import {Star} from "lucide-react"' in context
