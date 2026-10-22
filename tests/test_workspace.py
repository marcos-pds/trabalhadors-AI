"""Workspace integration: sandbox, diff, approval and multi-agent staging."""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_app import HEADERS, register, add_provider, wait_for  # sets isolated CENTRAL_DATA_DIR first
from central.main import app, ENGINE
from central.workspace import Workspaces


def setup(c, tmp_path):
    register(c)
    ENGINE.workspaces = Workspaces(ENGINE.db,root=tmp_path/'root')
    ENGINE.skills.workspaces = ENGINE.workspaces
    r=c.post('/api/projects',json={'name':'Loja Virtual','description':'Testes'},headers=HEADERS)
    assert r.status_code==200,r.text
    return r.json()['id']


def prepare(c,project):
    response=c.post(f'/api/projects/{project}/workspace',headers=HEADERS)
    assert response.status_code==200,response.text
    return Path(response.json()['folder'])


def stage(c,project,path,content=None,action='write'):
    item={'path':path,'action':action}
    if content is not None:item['content']=content
    return c.post(f'/api/projects/{project}/workspace/proposals',json={'files':[item]},headers=HEADERS)


def decide(c,project,proposal,approved=True,confirmation='APLICAR'):
    return c.post(f'/api/projects/{project}/workspace/proposals/{proposal}/decision',
                  json={'approved':approved,'confirmation':confirmation},headers=HEADERS)


def test_create_replace_delete_preview_requires_approval(tmp_path):
    with TestClient(app) as c:
        project=setup(c,tmp_path)
        folder=prepare(c,project)
        proposal=stage(c,project,'frontend/src/App.jsx','export default () => <h1>Oi</h1>')
        assert proposal.status_code==200,proposal.text
        assert not (folder/'frontend/src/App.jsx').exists()
        assert proposal.json()['files'][0]['replace'] is False
        assert '+++ depois/frontend/src/App.jsx' in proposal.json()['files'][0]['diff']
        pid=proposal.json()['id']
        assert decide(c,project,pid,confirmation='').status_code==422
        assert not (folder/'frontend/src/App.jsx').exists()
        assert decide(c,project,pid).json()['status']=='applied'
        assert (folder/'frontend/src/App.jsx').read_text()=='export default () => <h1>Oi</h1>'
        assert decide(c,project,pid).status_code==409
        read=c.get(f'/api/projects/{project}/workspace/file',params={'path':'frontend/src/App.jsx'})
        assert read.json()['content']=='export default () => <h1>Oi</h1>'
        # Rejection leaves an existing file untouched.
        r=stage(c,project,'frontend/src/App.jsx','new')
        assert r.json()['files'][0]['replace'] is True
        assert decide(c,project,r.json()['id'],approved=False).json()['status']=='rejected'
        assert (folder/'frontend/src/App.jsx').read_text().startswith('export')
        r=stage(c,project,'frontend/src/App.jsx','different')
        (folder/'frontend/src/App.jsx').write_text('external change')
        assert decide(c,project,r.json()['id']).status_code==409
        assert (folder/'frontend/src/App.jsx').read_text()=='external change'
        r=stage(c,project,'frontend/src/App.jsx',action='delete')
        assert r.status_code==200
        assert (folder/'frontend/src/App.jsx').exists()
        assert decide(c,project,r.json()['id']).json()['status']=='applied'
        assert not (folder/'frontend/src/App.jsx').exists()


@pytest.mark.parametrize('unsafe',[ '../escape.txt','../escape.txt','/tmp/nope.txt',r'C:\Windows\x.txt',
    '..\\escape.txt','.env','.env.production','.git/config','node_modules/x.js',
    'folder/../../outside','CON.txt','trailing./name','nul.txt','a//b', 'a|b'])
def test_blocks_unsafe_paths(tmp_path,unsafe):
    with TestClient(app) as c:
        project=setup(c,tmp_path);prepare(c,project)
        r=stage(c,project,unsafe,'evil')
        assert r.status_code in (403,422),r.text


def test_symlinks_user_isolation_and_request_protection(tmp_path):
    with TestClient(app) as a,TestClient(app) as b:
        project=setup(a,tmp_path)
        folder=prepare(a,project)
        register(b)
        assert b.get(f'/api/projects/{project}/workspace').status_code==404
        assert b.post(f'/api/projects/{project}/workspace',headers=HEADERS).status_code==404
        assert a.post(f'/api/projects/{project}/workspace/proposals',json={'files':[{'path':'ok.txt','content':'x'}]}).status_code==403
        outside=tmp_path/'elsewhere';outside.mkdir()
        try: (folder/'shortcut').symlink_to(outside,target_is_directory=True)
        except (OSError,NotImplementedError): pytest.skip('Sistema sem permissão de symlink')
        assert stage(a,project,'shortcut/x.txt','evil').status_code==403
        assert not (outside/'x.txt').exists()


def test_model_run_auto_creates_only_new_files(tmp_path):
    class ProjectFake:
        async def stream(self,provider,key,model,system,messages):
            assert 'central-files' in system
            assert provider.get('_max_tokens') == 4096
            yield '''Arquivo proposto:
```central-files
{"files":[{"path":"backend/extra.py","content":"print('ola')\\n"}]}
```'''
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        add_provider(c,'fake',1)
        ENGINE.client=ProjectFake()
        convo=c.post('/api/conversations',json={'title':'Projeto','project_id':project},headers=HEADERS)
        assert convo.status_code==200
        agent=next(a for a in c.get('/api/agents').json() if a['specialty']=='backend')
        payload={'conversation_id':convo.json()['id'],'mode':'manual','agent_ids':[agent['id']],
                 'prompt':'Crie a estrutura de um projeto com backend'}
        run=c.post('/api/runs',json=payload,headers=HEADERS)
        assert run.status_code==200
        assert wait_for(c,run.json()['id'])['status']=='completed'
        assert (folder/'backend/extra.py').read_text()=="print('ola')\n"
        info=c.get(f'/api/projects/{project}/workspace').json()
        assert len([x for x in info['proposals'] if x['status']=='applied'])==1
        events=ENGINE.db.all('SELECT event FROM events WHERE run_id=?',(run.json()['id'],))
        assert any(event['event']=='workspace_files_created' for event in events)
        # A second run must not overwrite the first file automatically.
        run=c.post('/api/runs',json=payload,headers=HEADERS)
        assert wait_for(c,run.json()['id'])['status']=='completed'
        assert (folder/'backend/extra.py').read_text()=="print('ola')\n"
        info=c.get(f'/api/projects/{project}/workspace').json()
        assert len([x for x in info['proposals'] if x['status']=='pending'])==1


def test_chat_request_creates_real_react_fastapi_project(tmp_path):
    class SummaryOnly:
        async def stream(self,provider,key,model,system,messages):
            yield 'A estrutura inicial está pronta.'
    with TestClient(app) as c:
        setup(c,tmp_path);add_provider(c,'fake',1)
        ENGINE.client=SummaryOnly()
        convo=c.post('/api/conversations',json={'title':'Nova conversa'},headers=HEADERS).json()
        result=c.post('/api/runs',json={
            'conversation_id':convo['id'],'prompt':
            'Crie a estrutura inicial de uma loja virtual com frontend React e backend FastAPI.',
            'mode':'manual'
        },headers=HEADERS)
        assert result.status_code==200,result.text
        assert wait_for(c,result.json()['id'])['status']=='completed'
        current=c.get('/api/conversations').json()
        saved=next(item for item in current if item['id']==convo['id'])
        project=saved['project_id']
        info=c.get(f'/api/projects/{project}/workspace').json()
        folder=Path(info['folder'])
        assert folder.parent==tmp_path/'root'
        assert len(info['files'])>=10
        assert (folder/'backend/main.py').exists()
        assert (folder/'frontend/src/App.tsx').exists()
        assert (folder/'frontend/package.json').exists()
        assert (folder/'README.md').exists()
        assert all(x['status']=='applied' for x in info['proposals'])
        assert not (folder/'frontend/node_modules').exists()
        events=ENGINE.db.all('SELECT event,payload FROM events WHERE run_id=?',(result.json()['id'],))
        assert any(e['event']=='workspace_prepared' for e in events)
        assert any(e['event']=='workspace_stage_error' for e in events)  # model provided no files
        output=c.get(f"/api/runs/{result.json()['id']}").json()['output']
        assert 'Resultado no Windows' in output
        assert str(folder) in output
        assert 'Arquivos existentes' in output
        assert 'A estrutura inicial está pronta.' not in output


def test_incomplete_agent_json_does_not_write_fragments(tmp_path):
    class Truncated:
        async def stream(self,provider,key,model,system,messages):
            yield '''Arquivo proposto: ```central-files
{"files":[{"path":"src/test.py","content":"print('sem fim)'''
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        add_provider(c,'fake',1);ENGINE.client=Truncated()
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()
        result=c.post('/api/runs',json={'conversation_id':convo['id'],
              'prompt':'Crie a estrutura inicial de um projeto Python',
              'mode':'manual'},headers=HEADERS)
        assert wait_for(c,result.json()['id'])['status']=='completed'
        assert not (folder/'src/test.py').exists()
        events=ENGINE.db.all('SELECT event FROM events WHERE run_id=?',(result.json()['id'],))
        assert any(e['event']=='workspace_stage_error' for e in events)
        output=c.get(f"/api/runs/{result.json()['id']}").json()['output']
        assert 'Avisos de geração' in output
        assert 'JSON dos arquivos veio incompleto' in output
        assert 'sem fim' not in output


def test_multi_file_preflight_prevents_partial_write(tmp_path):
    with TestClient(app) as c:
        p=setup(c,tmp_path);folder=prepare(c,p)
        s=c.post(f'/api/projects/{p}/workspace/proposals',json={'files':[
          {'path':'new.txt','content':'new'},{'path':'existing.txt','content':'changed'}]},headers=HEADERS)
        assert s.status_code==200
        (folder/'existing.txt').write_text('external')
        assert decide(c,p,s.json()['id']).status_code==409
        assert not (folder/'new.txt').exists()


def test_coding_worker_repairs_missing_manifest_and_writes_real_file(tmp_path):
    """A worker that describes code must be prompted once for a complete JSON file."""
    class NeedsRepair:
        def __init__(self):
            self.calls = []
        async def stream(self, provider, key, model, system, messages):
            self.calls.append({'tokens':provider.get('_max_tokens'),'prompt':messages[0]['content']})
            if len(self.calls)==1:
                yield 'Explicação do frontend, mas sem nenhum arquivo JSON.'
            else:
                assert 'UM ÚNICO arquivo NOVO' in messages[0]['content']
                yield '{"files":[{"path":"frontend/src/components/ProductBadge.tsx",'
                yield '"content":"export default function ProductBadge() { return <span>Novo</span>; }\\n"}]}'
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        add_provider(c,'fake',1)
        fake=NeedsRepair(); ENGINE.client=fake
        convo=c.post('/api/conversations',
                     json={'title':'Frontend','project_id':project},headers=HEADERS).json()
        agent=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        run=c.post('/api/runs',json={
            'conversation_id':convo['id'],'mode':'manual','agent_ids':[agent['id']],
            'prompt':'Crie a estrutura inicial do projeto frontend React com componentes.'},headers=HEADERS)
        assert run.status_code==200,run.text
        result=wait_for(c,run.json()['id'])
        assert result['status']=='completed'
        assert len(fake.calls)==2
        assert fake.calls[0]['tokens']==4096
        assert fake.calls[1]['tokens']==3072
        assert (folder/'frontend/src/components/ProductBadge.tsx').is_file()
        assert (folder/'frontend/src/components/ProductBadge.tsx').read_text().startswith('export default')
        stored=c.get(f"/api/runs/{run.json()['id']}").json()['steps'][0]['output']
        assert 'Explicação do frontend' not in stored
        assert '"files"' in stored
        events=ENGINE.db.all('SELECT event FROM events WHERE run_id=?',(run.json()['id'],))
        assert any(event['event']=='workspace_retry_started' for event in events)
        assert any(event['event']=='workspace_retry_succeeded' for event in events)


def test_budget_limited_project_does_not_make_unplanned_retry(tmp_path):
    class ExplainerOnly:
        def __init__(self): self.calls=0
        async def stream(self,provider,key,model,system,messages):
            self.calls+=1
            yield 'Explicação sem manifesto'
    with TestClient(app) as c:
        project=setup(c,tmp_path);prepare(c,project);add_provider(c,'fake',1)
        fake=ExplainerOnly();ENGINE.client=fake
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()
        agent=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        run=c.post('/api/runs',json={'conversation_id':convo['id'],'mode':'manual',
            'agent_ids':[agent['id']],'budget_limit':1.0,
            'prompt':'Crie a estrutura inicial do projeto frontend React.'},headers=HEADERS)
        assert run.status_code==200
        assert wait_for(c,run.json()['id'])['status']=='completed'
        assert fake.calls==1


def test_truncated_planner_does_not_block_valid_frontend_worker(tmp_path):
    """A bad architect JSON cannot cause the frontend worker's valid file to be lost."""
    class Mixed:
        async def stream(self, provider, key, model, system, messages):
            if system.startswith('Planeje soluções técnicas'):
                yield '{"files":[{"path":"backend/broken.py","content":"incompleto'
            elif system.startswith('Implemente frontend'):
                yield '{"files":[{"path":"frontend/src/components/SaleTag.tsx",'
                yield '"content":"export default function SaleTag(){ return <b>Oferta</b> }"}]}'
            else:
                yield 'Revisão concluída.'
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        ENGINE.client=Mixed()
        agents=c.get('/api/agents').json()
        selected=[a['id'] for a in agents if a['specialty'] in ('architecture','frontend')]
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()
        run=c.post('/api/runs',json={
            'conversation_id':convo['id'],'mode':'team','agent_ids':selected,
            'prompt':'Crie um projeto React com um componente novo.'},headers=HEADERS)
        assert run.status_code==200,run.text
        done=wait_for(c,run.json()['id'])
        assert done['status']=='completed',done.get('error')
        assert (folder/'frontend/src/components/SaleTag.tsx').is_file()
        assert not (folder/'backend/broken.py').exists()
        assert 'JSON dos arquivos veio incompleto' in done['output']


def test_referenced_existing_file_is_read_fully_without_asking_user(tmp_path):
    """Editing a cited App.tsx must have full authorized file context and create only a pending diff."""
    import json
    from central.workspace import Workspaces
    class ContextAwareFrontend:
        calls=0
        async def stream(self, provider, key, model, system, messages):
            self.calls+=1
            assert '=== INÍCIO DO ARQUIVO EXISTENTE: frontend/src/App.tsx ===' in system
            assert '=== FIM DO ARQUIVO: frontend/src/App.tsx ===' in system
            assert 'CURRENT_APP_FULL_CONTEXT_END' in system
            assert 'existing ProductCard' in system
            assert 'INTERNAL_NOT_REQUESTED' not in system
            assert 'Não peça ao usuário que copie' in system
            yield json.dumps({'files':[{'path':'frontend/src/App.tsx',
                          'content':'import ProductCard from "./components/ProductCard";\\nexport default function App(){return <ProductCard />; }\\n'}]})
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        appfile=folder/'frontend/src/App.tsx'
        appfile.parent.mkdir(parents=True,exist_ok=True)
        original='// existing source\\n' + ('export const n = 1;\\n' * 125) + '// CURRENT_APP_FULL_CONTEXT_END\\n'
        assert len(original)>1800
        appfile.write_text(original)
        component=folder/'frontend/src/components/ProductCard.tsx'
        component.parent.mkdir(parents=True,exist_ok=True)
        component.write_text('// existing ProductCard\\nexport default function ProductCard(){return <div />;}\\n')
        (folder/'private-other.txt').write_text('INTERNAL_NOT_REQUESTED')
        add_provider(c,'fake',1)
        fake=ContextAwareFrontend()
        ENGINE.client=fake
        convo=c.post('/api/conversations',json={'title':'Loja','project_id':project},headers=HEADERS).json()
        agent=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        run=c.post('/api/runs',json={'conversation_id':convo['id'],
          'prompt':'Integre frontend/src/components/ProductCard.tsx ao frontend/src/App.tsx sem alterar outros arquivos.',
          'mode':'manual','agent_ids':[agent['id']]},headers=HEADERS)
        assert run.status_code==200,run.text
        result=wait_for(c,run.json()['id'])
        assert result['status']=='completed'
        assert fake.calls==1
        assert appfile.read_text()==original
        info=c.get(f'/api/projects/{project}/workspace').json()
        pending=[x for x in info['proposals'] if x['status']=='pending']
        assert len(pending)==1
        preview=c.get(f"/api/projects/{project}/workspace/proposals/{pending[0]['id']}").json()
        assert preview['files'][0]['replace'] is True
        assert 'import ProductCard' in preview['files'][0]['diff']
        assert decide(c,project,pending[0]['id'],confirmation='').status_code==422
        assert decide(c,project,pending[0]['id']).status_code==200
        assert 'import ProductCard' in appfile.read_text()


def test_context_basename_lookup_and_oversize_no_partial_leak(tmp_path):
    with TestClient(app) as c:
        p=setup(c,tmp_path);folder=prepare(c,p)
        path=folder/'frontend/src/App.tsx';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('// visible App source\\n')
        hidden=folder/'backend/secret-data.py';hidden.parent.mkdir(parents=True,exist_ok=True)
        hidden.write_text('SECRET_SHOULD_NOT_SEND')
        user=c.get('/api/me').json()['id']
        convo=c.post('/api/conversations',json={'project_id':p},headers=HEADERS).json()['id']
        prompt=ENGINE.workspaces.prompt(user,convo,request='Modifique App.tsx')
        assert '// visible App source' in prompt
        assert 'SECRET_SHOULD_NOT_SEND' not in prompt
        path.write_text('x'*13_000)
        prompt=ENGINE.workspaces.prompt(user,convo,request='Modifique App.tsx')
        assert 'arquivo grande demais para contexto completo' in prompt
        assert 'x'*300 not in prompt


def test_architect_asks_for_app_file_then_repairs_from_workspace_context(tmp_path):
    """The exact reported problem: architect requests a file it already has; retry stages edit."""
    import json

    class RequestsFile:
        def __init__(self): self.calls=0
        async def stream(self, provider, key, model, system, messages):
            self.calls+=1
            assert '=== INÍCIO DO ARQUIVO EXISTENTE: frontend/src/App.tsx ===' in system
            assert 'old App content' in system
            if self.calls==1:
                yield 'Para continuar, envie o conteúdo de frontend/src/App.tsx.'
            else:
                assert 'NÃO peça que ele envie o arquivo' in messages[0]['content']
                assert 'old App content' in system
                yield json.dumps({'files':[{'path':'frontend/src/App.tsx',
                     'content':'export default function App(){return <main>Cartão integrado</main>}'}]})

    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        file=folder/'frontend/src/App.tsx';file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text('export default function App(){return <main>old App content</main>}')
        add_provider(c,'fake',1)
        fake=RequestsFile();ENGINE.client=fake
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()
        architect=next(a for a in c.get('/api/agents').json() if a['specialty']=='architecture')
        run=c.post('/api/runs',json={'conversation_id':convo['id'],'mode':'manual',
            'agent_ids':[architect['id']],
            'prompt':'Integre o componente ProductCard ao arquivo frontend/src/App.tsx. '
                     'Não sobrescreva sem aprovação.'},headers=HEADERS)
        assert run.status_code==200,run.text
        result=wait_for(c,run.json()['id'])
        assert result['status']=='completed'
        assert fake.calls==2
        assert file.read_text().endswith('old App content</main>}')
        pending=[item for item in c.get(f'/api/projects/{project}/workspace').json()['proposals']
                 if item['status']=='pending']
        assert len(pending)==1
        assert pending[0]['files'][0]['path']=='frontend/src/App.tsx'
        assert pending[0]['files'][0]['replace'] is True
        assert decide(c,project,pending[0]['id'],confirmation='').status_code==422
        assert file.read_text().endswith('old App content</main>}')
        assert decide(c,project,pending[0]['id']).status_code==200
        assert 'Cartão integrado' in file.read_text()



def test_run_report_preserves_applied_files_when_full_explorer_info_is_unavailable(tmp_path,monkeypatch):
    """A UIUX run cannot turn successful file creation into a generic Windows-folder failure."""
    class CreatedFile:
        async def stream(self, provider, key, model, system, messages):
            yield '{"files":[{"path":"frontend/src/components/QualityMark.tsx",'
            yield '"content":"export default function QualityMark(){return <span>Qualidade</span>}"}]}'
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        ENGINE.client=CreatedFile()
        conversation=c.post('/api/conversations',json={'project_id':project},
                            headers=HEADERS).json()['id']
        def explode(*args,**kwargs):
            raise RuntimeError('old proposals cannot be decoded')
        monkeypatch.setattr(ENGINE.workspaces,'info',explode)
        agent=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        response=c.post('/api/runs',json={'conversation_id':conversation,
            'mode':'manual','agent_ids':[agent['id']],
            'prompt':'Adicione um novo componente React ao frontend.'},headers=HEADERS)
        assert response.status_code==200,response.text
        run=wait_for(c,response.json()['id'])
        assert run['status']=='completed',run.get('error')
        output=run['output']
        assert 'Resultado no Windows' in output
        assert 'QualityMark.tsx' in output
        assert 'Novos arquivos criados automaticamente' in output
        assert 'Não foi possível consultar a pasta local' not in output
        assert (folder/'frontend/src/components/QualityMark.tsx').exists()


def test_run_report_keeps_proposals_when_file_count_scan_fails(tmp_path,monkeypatch):
    """An unreadable or changing directory must not hide pending diffs from the user."""
    class ChangedFile:
        async def stream(self,provider,key,model,system,messages):
            yield '{"files":[{"path":"frontend/src/App.tsx","content":"export default function App(){return <main>Modernizada</main>}"}]}'
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        current=folder/'frontend/src/App.tsx';current.parent.mkdir(parents=True,exist_ok=True)
        original='export default function App(){return <div>Original</div>}'
        current.write_text(original)
        ENGINE.client=ChangedFile()
        convo=c.post('/api/conversations',json={'project_id':project},headers=HEADERS).json()['id']
        calls=[0]
        real_tree=ENGINE.workspaces.tree
        def flaky_tree(*args,**kwargs):
            calls[0]+=1
            if calls[0]>=2:
                raise PermissionError('Windows file temporarily inaccessible')
            return real_tree(*args,**kwargs)
        monkeypatch.setattr(ENGINE.workspaces,'tree',flaky_tree)
        agent=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        response=c.post('/api/runs',json={'conversation_id':convo,'mode':'manual',
            'agent_ids':[agent['id']],'prompt':'Atualize frontend/src/App.tsx mantendo as funcionalidades.'},
            headers=HEADERS)
        assert response.status_code==200,response.text
        result=wait_for(c,response.json()['id'])
        assert result['status']=='completed',result.get('error')
        assert current.read_text()==original
        assert 'contagem indisponível' in result['output']
        assert 'Aguardando revisão e aprovação' in result['output']
        assert 'frontend/src/App.tsx' in result['output']
        assert 'Não foi possível consultar a pasta local' not in result['output']
        events=ENGINE.db.all('SELECT event,payload FROM events WHERE run_id=?',
                             (response.json()['id'],))
        assert any(e['event']=='workspace_summary_warning' for e in events)
        # Pending proposal survives the file-count failure and stays reviewable.
        rows=ENGINE.db.all('SELECT * FROM workspace_proposals WHERE run_id=?',
                           (response.json()['id'],))
        assert len(rows)==1 and rows[0]['status']=='pending'
