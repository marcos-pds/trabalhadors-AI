"""Delegated Architect authority is explicit, scoped and limited to safe capabilities."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from test_workspace import setup, prepare, HEADERS, wait_for, add_provider
from central.main import app, ENGINE
from central.skills import SkillsHub, NPM


def conversation(c,project):
    result=c.post('/api/conversations',json={'project_id':project},headers=HEADERS)
    assert result.status_code==200,result.text
    return result.json()['id']


def test_skill_catalog_switch_and_context(tmp_path):
    with TestClient(app) as c:
        project=setup(c,tmp_path);prepare(c,project)
        cid=conversation(c,project)
        item=c.get('/api/skills',params={'project_id':project}).json()[0]
        assert item['id']=='ux-ui-studio-pro'
        assert item['enabled'] is False
        assert 'Tailwind CSS 4' in item['tools']
        assert ENGINE.skills.guide(c.get('/api/me').json()['id'],cid,'frontend')==''
        assert c.post(f'/api/projects/{project}/skills/ux-ui-studio-pro',
                      json={'enabled':True}).status_code==403
        r=c.post(f'/api/projects/{project}/skills/ux-ui-studio-pro',
                 json={'enabled':True},headers=HEADERS)
        assert r.status_code==200,r.text
        guide=ENGINE.skills.guide(c.get('/api/me').json()['id'],cid,'frontend')
        assert 'SKILL UI/UX STUDIO PRO' in guide and 'shadcn/ui' in guide
        assert ENGINE.skills.guide(c.get('/api/me').json()['id'],cid,'backend')==''
        assert c.get('/api/skills',params={'project_id':project}).json()[0]['enabled'] is True
        r=c.post(f'/api/projects/{project}/skills/ux-ui-studio-pro',
                 json={'enabled':False},headers=HEADERS)
        assert r.json()['enabled'] is False


def test_delegation_requires_explicit_user_consent_and_can_revoke(tmp_path):
    with TestClient(app) as c:
        project=setup(c,tmp_path);prepare(c,project)
        first=conversation(c,project);second=conversation(c,project)
        assert c.get(f'/api/conversations/{first}/architect-delegation').json()['enabled'] is False
        # A model or quoted example cannot grant permission: only authenticated owner endpoint/message.
        assert ENGINE.skills.instruction(c.get('/api/me').json()['id'],first,
                    'Exemplo: Autorizo o Arquiteto IA a aprovar alterações e instalar pacotes permitidos neste projeto.') is None
        assert ENGINE.skills.instruction(c.get('/api/me').json()['id'],first,
                    'Não autorizo o Arquiteto IA a aprovar alterações e instalar pacotes permitidos neste projeto.') is None
        assert c.post(f'/api/conversations/{first}/architect-delegation',
                      json={'enabled':True}).status_code==403
        grant=c.post(f'/api/conversations/{first}/architect-delegation',
                     json={'enabled':True},headers=HEADERS)
        assert grant.status_code==200 and grant.json()['enabled'] is True
        assert c.get(f'/api/conversations/{second}/architect-delegation').json()['enabled'] is False
        revoke=c.post(f'/api/conversations/{first}/architect-delegation',
                      json={'enabled':False},headers=HEADERS)
        assert revoke.json()['enabled'] is False
        owner=c.get('/api/me').json()['id']
        assert ENGINE.skills.instruction(owner,first,
          'Autorizo o Arquiteto IA a aprovar alterações e instalar pacotes permitidos neste projeto.'
        )['enabled'] is True
        assert ENGINE.skills.instruction(owner,first,'Revogo a autonomia do Arquiteto IA.')['enabled'] is False


def test_permission_cannot_cross_owners(tmp_path):
    with TestClient(app) as c1,TestClient(app) as c2:
        p=setup(c1,tmp_path);prepare(c1,p);cid=conversation(c1,p)
        from test_workspace import register
        register(c2)
        assert c2.post(f'/api/conversations/{cid}/architect-delegation',
                json={'enabled':True},headers=HEADERS).status_code==404
        assert c2.post(f'/api/projects/{p}/skills/ux-ui-studio-pro',
                json={'enabled':True},headers=HEADERS).status_code==404


def test_architect_approves_normal_code_only_after_grant(tmp_path):
    class Reviewer:
        def __init__(self):self.reviews=0
        async def stream(self,provider,key,model,system,messages):
            if 'ARQUITETO REVISOR AUTORIZADO' in system:
                self.reviews+=1
                assert '+++ depois/frontend/src/App.tsx' in messages[0]['content']
                yield json.dumps({'decision':'approve','reason':'Importação e renderização coerentes.'})
            else:
                yield json.dumps({'files':[{'path':'frontend/src/App.tsx','content':
                  'import ProductCard from "./components/ProductCard";\nexport default function App(){return <main><ProductCard /></main>}\n'}]})
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        source=folder/'frontend/src/App.tsx';source.parent.mkdir(parents=True,exist_ok=True)
        source.write_text('export default function App(){return <main>Original</main>}')
        cid=conversation(c,project)
        grant=c.post(f'/api/conversations/{cid}/architect-delegation',
                 json={'enabled':True},headers=HEADERS)
        assert grant.status_code==200,grant.text
        fake=Reviewer();ENGINE.client=fake
        frontend=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        run=c.post('/api/runs',json={'conversation_id':cid,'mode':'manual','agent_ids':[frontend['id']],
                'prompt':'Integre frontend/src/App.tsx ao ProductCard'},headers=HEADERS)
        assert run.status_code==200,run.text
        finished=wait_for(c,run.json()['id'])
        assert finished['status']=='completed'
        assert fake.reviews==1
        assert 'import ProductCard' in source.read_text()
        audit=ENGINE.db.all('SELECT * FROM architect_approval_log WHERE run_id=?',(run.json()['id'],))
        assert len(audit)==1 and audit[0]['decision']=='approved'
        assert 'Arquiteto autorizado' in finished['output']


def test_delegation_never_auto_approves_configs_or_deletes(tmp_path):
    class Model:
        def __init__(self):self.review_calls=0
        async def stream(self,provider,key,model,system,messages):
            if 'ARQUITETO REVISOR AUTORIZADO' in system:
                self.review_calls+=1
                yield '{"decision":"approve","reason":"Tudo certo"}'
            else:
                yield '{"files":[{"path":"frontend/package.json","content":"{\\"name\\":\\"bad\\"}"}]}'
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        conf=folder/'frontend/package.json';conf.parent.mkdir(parents=True,exist_ok=True)
        conf.write_text('{"name":"safe"}')
        cid=conversation(c,project)
        c.post(f'/api/conversations/{cid}/architect-delegation',json={'enabled':True},headers=HEADERS)
        fake=Model();ENGINE.client=fake
        frontend=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        r=c.post('/api/runs',json={'conversation_id':cid,'mode':'manual','agent_ids':[frontend['id']],
                                  'prompt':'Atualize frontend/package.json'},headers=HEADERS)
        assert wait_for(c,r.json()['id'])['status']=='completed'
        assert conf.read_text()=='{"name":"safe"}'
        pending=[p for p in c.get(f'/api/projects/{project}/workspace').json()['proposals']
                 if p['status']=='pending']
        assert pending
        assert fake.review_calls==0


def test_install_catalog_and_audit_with_no_real_install(tmp_path,monkeypatch):
    class Architect:
        async def stream(self,provider,key,model,system,messages):
            assert 'AUTONOMIA EXPLICITAMENTE DELEGADA' in system
            ticks=chr(96)*3
            yield ticks+'central-packages\n{"manager":"npm","packages":["lucide-react","motion"]}\n'+ticks
    with TestClient(app) as c:
        project=setup(c,tmp_path);prepare(c,project);add_provider(c,'fake',1)
        cid=conversation(c,project)
        assert c.post(f'/api/conversations/{cid}/architect-delegation',
                      json={'enabled':True},headers=HEADERS).status_code==200
        calls=[]
        def fake_install(self,user,project,manager,packages):
            calls.append((user,project,manager,packages))
            return {'ok':True,'manager':manager,'packages':packages,'exit_code':0,'output':'faked'}
        monkeypatch.setattr(SkillsHub,'_install_sync',fake_install)
        ENGINE.client=Architect()
        architect=next(a for a in c.get('/api/agents').json() if a['specialty']=='architecture')
        run=c.post('/api/runs',json={'conversation_id':cid,'mode':'manual','agent_ids':[architect['id']],
            'prompt':'Instale as dependências de ícones e Motion para melhorar o e-commerce.'},headers=HEADERS)
        assert run.status_code==200
        assert wait_for(c,run.json()['id'])['status']=='completed'
        assert len(calls)==1 and calls[0][2:] == ('npm',['lucide-react','motion'])
        history=c.get(f'/api/projects/{project}/package-installs')
        assert history.status_code==200 and history.json()[0]['status']=='completed'


@pytest.mark.parametrize('manifest',[
  {'manager':'npm','packages':['bad-evil-lib']},
  {'manager':'npm','packages':['lucide-react;rm -rf /']},
  {'manager':'pip','packages':['httpx --extra-index-url=https://evil.example']},
  {'manager':'npx','packages':['shadcn']},
  {'manager':'npm','packages':['motion']*6},
])
def test_unlisted_dependency_request_never_executes(manifest):
    source=chr(96)*3+'central-packages\n'+json.dumps(manifest)+'\n'+chr(96)*3
    from central.workspace import WorkspaceError
    with pytest.raises(WorkspaceError):
        SkillsHub.manifest(source)


def test_no_delegation_means_no_package_actions(tmp_path,monkeypatch):
    with TestClient(app) as c:
        project=setup(c,tmp_path);prepare(c,project)
        cid=conversation(c,project)
        def fail(*args,**kwargs):raise AssertionError('No installation without delegation')
        monkeypatch.setattr(SkillsHub,'_install_sync',fail)
        result=__import__('asyncio').run(ENGINE.skills.install_for_run(
          {'user_id':c.get('/api/me').json()['id'],'conversation_id':cid,'id':'dummy-run'}))
        assert result==[]


def test_installer_refuses_redirected_npm_lockfile(tmp_path,monkeypatch):
    from central.workspace import WorkspaceError
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        front=folder/'frontend';front.mkdir()
        (front/'package.json').write_text('{"name":"safe-ui"}')
        outside=tmp_path/'outside-lock.json';outside.write_text('{"unsafe":true}')
        try:
            (front/'package-lock.json').symlink_to(outside)
        except (OSError,NotImplementedError):
            pytest.skip('Sistema não permite criar symlinks no teste.')
        def never(*args,**kwargs):
            raise AssertionError('No subprocess should be invoked with a linked lockfile')
        monkeypatch.setattr('subprocess.run',never)
        with pytest.raises(WorkspaceError):
            ENGINE.skills._install_sync(c.get('/api/me').json()['id'],project,'npm',['lucide-react'])
        assert outside.read_text()=='{"unsafe":true}'


def test_modernization_with_manual_architect_creates_real_worker_tasks_and_approved_files(tmp_path, monkeypatch):
    """Regression: user asks Architect to coordinate UX/UI, must not stop at a text plan."""
    from central.engine import ui_execution_plan
    class Workers:
        def __init__(self):self.workers=[]
        async def stream(self, provider, key, model, system, messages):
            self.workers.append(system)
            if 'ARQUITETO REVISOR AUTORIZADO' in system:
                yield json.dumps({'decision':'approve','reason':'Diff seguro e escopo compatível.'})
            elif 'UI_STAGE_PLANNING' in system:
                fence=chr(96)*3
                yield ('Direção técnica: preservar o FastAPI e modernizar componentes.\\n'
                       +fence+'central-packages\n{"manager":"npm","packages":["lucide-react"]}\n'+fence)
            elif 'UI_STAGE_DESIGN' in system:
                yield 'Paleta premium, grid responsivo, foco visível, reduced-motion.'
            elif 'UI_STAGE_IMPLEMENT' in system:
                if 'Frontend · Vitrine' in system: raise AssertionError('Unexpected step name in system')
                if 'UMA alteração completa para frontend/src/App.tsx' in system:
                    yield json.dumps({'files':[{'path':'frontend/src/App.tsx',
                      'content':'import { getProducts } from "./api";\nimport ProductCard from "./components/ProductCard";\nexport default function App(){return <main><h1>Loja Premium</h1><ProductCard /></main>}\n'}]})
                elif 'UMA alteração completa para frontend/src/index.css' in system:
                    yield json.dumps({'files':[{'path':'frontend/src/index.css',
                      'content':':root{color:#151e32;background:#f7f5f1} main{max-width:1200px;margin:auto}' }]})
                elif 'UMA alteração completa para frontend/src/components/ProductCard.tsx' in system:
                    yield json.dumps({'files':[{'path':'frontend/src/components/ProductCard.tsx',
                      'content':'export default function ProductCard(){return <article>Vitrine</article>}' }]})
                else: raise AssertionError('No file task instructions')
            elif 'UI_STAGE_TEST' in system:
                yield 'Análise QA concluída.'
            elif 'UI_STAGE_REVIEW' in system:
                yield 'Checklist aprovado, o servidor deve verificar os diffs.'
            else:
                raise AssertionError('Unexpected agent instructions: '+system[:120])
    with TestClient(app) as c:
        p=setup(c,tmp_path);folder=prepare(c,p);add_provider(c,'fake',1)
        frontend=folder/'frontend/src';frontend.mkdir(parents=True,exist_ok=True)
        (frontend/'components').mkdir()
        (frontend/'App.tsx').write_text('export default function App(){return <p>Antiga loja</p>}')
        (frontend/'index.css').write_text('body{background:white}')
        (frontend/'components/ProductCard.tsx').write_text('export default function ProductCard(){return <div>Produto</div>}')
        backend=folder/'backend';backend.mkdir()
        (backend/'main.py').write_text("print('backend preservado')")
        c.post(f'/api/projects/{p}/skills/ux-ui-studio-pro',
              json={'enabled':True},headers=HEADERS)
        cid=conversation(c,p)
        c.post(f'/api/conversations/{cid}/architect-delegation',
               json={'enabled':True},headers=HEADERS)
        installations=[]
        def install(self,user,project,manager,packages):
            installations.append((manager,packages))
            return {'ok':True,'manager':manager,'packages':packages,'exit_code':0,'output':'mock'}
        monkeypatch.setattr(SkillsHub,'_install_sync',install)
        workers=Workers();ENGINE.client=workers
        architect=next(a for a in c.get('/api/agents').json() if a['specialty']=='architecture')
        prompt=('Modernize o UX/UI da Loja Virtual utilizando a Skill UI/UX Studio Pro. '
                'O Arquiteto IA deve coordenar o Frontend IA e o Designer IA, '
                'avaliar bibliotecas necessárias, preparar instalações autorizadas e revisar alterações. '
                'Quero layout responsivo, cards premium, ícones e animações discretas.')
        response=c.post('/api/runs',json={'conversation_id':cid,'mode':'manual',
            'agent_ids':[architect['id']],'prompt':prompt},headers=HEADERS)
        assert response.status_code==200,response.text
        run=wait_for(c,response.json()['id'],timeout=8)
        assert run['status']=='completed',run.get('error')
        specialties=[step['name'] for step in run['steps']]
        assert len(run['steps'])==7
        assert any('Designer' in name for name in specialties)
        assert len([n for n in specialties if n.startswith('Frontend')])==3
        assert 'Loja Premium' in (frontend/'App.tsx').read_text()
        assert 'background:#f7f5f1' in (frontend/'index.css').read_text()
        assert 'Vitrine' in (frontend/'components/ProductCard.tsx').read_text()
        assert (backend/'main.py').read_text()=="print('backend preservado')"
        assert installations==[('npm',['lucide-react'])]
        assert c.get(f'/api/projects/{p}/package-installs').json()[0]['status']=='completed'
        assert len(ENGINE.db.all('SELECT * FROM architect_approval_log WHERE run_id=?',(run['id'],)))==3
        assert 'Arquiteto autorizado' in run['output']


def test_ui_mode_without_skill_keeps_manual_architect_only(tmp_path):
    from central.engine import ui_execution_plan
    with TestClient(app) as c:
        p=setup(c,tmp_path);prepare(c,p)
        architect=next(a for a in c.get('/api/agents').json() if a['specialty']=='architecture')
        agents=c.get('/api/agents').json()
        prompt='Modernize o UX/UI da Loja Virtual. Arquiteto deve coordenar Frontend e Designer.'
        assert ui_execution_plan(agents,prompt,'manual',[architect['id']],False) is None
        assert ui_execution_plan(agents,'Faça apenas um plano de modernização UX/UI da loja',
                                 'manual',[architect['id']],True) is None


def test_architect_markdown_npm_plan_is_normalized_without_shell_execution(tmp_path,monkeypatch):
    """Plain npm commands are NEVER executed; only a validated second-turn manifest."""
    class Planner:
        def __init__(self):self.normalizations=0
        async def stream(self,provider,key,model,system,messages):
            if 'REPAIR_PACKAGE_MANIFEST' in system:
                self.normalizations+=1
                fence=chr(96)*3
                yield fence+'central-packages\n{"manager":"npm","packages":["tailwindcss","@tailwindcss/vite","lucide-react"]}\n'+fence
            elif 'UI_STAGE_PLANNING' in system:
                yield 'Bibliotecas sugeridas: npm install tailwindcss @tailwindcss/vite lucide-react; '
                yield 'não há manifesto estruturado.'
            elif 'UI_STAGE_DESIGN' in system:
                yield 'Layout premium e contraste acessível.'
            elif 'UI_STAGE_IMPLEMENT' in system:
                import re
                path=re.search(r'UMA alteração completa para (\S+)\.',system)
                assert path,system
                target=path.group(1)
                yield json.dumps({'files':[{'path':target,'content':'// arquivo modernizado\n'}]})
            elif 'UI_STAGE_TEST' in system:
                yield 'Análise QA concluída.'
            elif 'UI_STAGE_REVIEW' in system:
                yield 'Os arquivos estão com a etapa de revisão concluída.'
            elif 'ARQUITETO REVISOR AUTORIZADO' in system:
                yield '{"decision":"approve","reason":"Revisado"}'
            else:
                raise AssertionError('Unexpected step')
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        fdir=folder/'frontend/src/components';fdir.mkdir(parents=True)
        for name in ('frontend/src/App.tsx','frontend/src/index.css','frontend/src/components/ProductCard.tsx'):
            (folder/name).write_text('// original\n')
        c.post(f'/api/projects/{project}/skills/ux-ui-studio-pro',
               json={'enabled':True},headers=HEADERS)
        cid=conversation(c,project)
        c.post(f'/api/conversations/{cid}/architect-delegation',
               json={'enabled':True},headers=HEADERS)
        calls=[]
        def fake_install(self,uid,pid,manager,packages):
            calls.append((manager,packages))
            return {'ok':True,'manager':manager,'packages':packages,'exit_code':0,'output':'mock'}
        monkeypatch.setattr(SkillsHub,'_install_sync',fake_install)
        model=Planner();ENGINE.client=model
        architect=next(a for a in c.get('/api/agents').json() if a['specialty']=='architecture')
        r=c.post('/api/runs',json={'conversation_id':cid,'mode':'manual',
             'agent_ids':[architect['id']],
             'prompt':'Modernize o UX/UI da Loja Virtual. Arquiteto IA deve coordenar Frontend IA e Designer IA.'},
             headers=HEADERS)
        assert r.status_code==200,r.text
        finished=wait_for(c,r.json()['id'],timeout=8)
        assert finished['status']=='completed',finished.get('error')
        assert model.normalizations==1
        assert calls==[('npm',['tailwindcss','@tailwindcss/vite','lucide-react'])]
        assert any('Instalação autorizada' in finished['output'] for x in [1])
        assert 'npm install' not in finished['output']


def test_ui_worker_cannot_write_an_unassigned_file(tmp_path):
    """A component task cannot modify another project file even if the model proposes it."""
    from central.database import uid, utcnow
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        owner=c.get('/api/me').json()['id']
        cid=conversation(c,project)
        runid=uid();stepid=uid();now=utcnow()
        ENGINE.db.execute('''INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,
                 created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (runid,owner,cid,'Modernize o UX/UI','completed','team','[]','[]',now,now))
        frontend=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        ENGINE.db.execute('''INSERT INTO steps(id,run_id,agent_id,kind,name,deps,instructions,
                  status,output,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (stepid,runid,frontend['id'],'agent','Frontend · Vitrine','[]',
             'UI_STAGE_IMPLEMENT. Gere UMA alteração completa para frontend/src/App.tsx. '
             'Proponha apenas este arquivo.','completed',
             '{"files":[{"path":"frontend/src/index.css","content":"body{color:red}"}]}',now,now))
        result=ENGINE.workspaces.stage_run({'id':runid,'conversation_id':cid,'user_id':owner,
                                           'prompt':'Modernize o UX/UI'})
        assert result['auto_applied']==[] and result['pending']==[]
        assert any('fora de sua responsabilidade' in err for err in result['errors'])
        assert not (folder/'frontend/src/index.css').exists()



def test_explicit_skill_ux_request_ignores_stale_manual_frontend_selection(tmp_path):
    """User requests Architect-coordinated storefront redesign: always plan 6 stages."""
    class UIWorkers:
        async def stream(self,provider,key,model,system,messages):
            if 'UI_STAGE_PLANNING' in system:
                # An architect may propose unrelated components, but not stage them.
                yield '{"files":[{"path":"frontend/src/components/NavBar.tsx","content":"unrelated"}]}'
            elif 'UI_STAGE_DESIGN' in system:
                yield 'Direção visual aprovada: contraste, espaços, responsividade.'
            elif 'UI_STAGE_IMPLEMENT' in system:
                import re
                target=re.search(r'UMA alteração completa para ([\w./-]+)\.',system)
                assert target,system[:900]
                path=target.group(1)
                yield json.dumps({'files':[{'path':path,'content':'/* modernization: '+path+' */\n'}]})
            elif 'UI_STAGE_TEST' in system:
                yield 'Análise QA concluída.'
            elif 'UI_STAGE_REVIEW' in system:
                yield 'Revisão de integração: comparar os diffs antes de aprovar.'
            else:raise AssertionError('Etapa desconhecida '+system[:100])
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        files=('frontend/src/App.tsx','frontend/src/index.css',
               'frontend/src/components/ProductCard.tsx')
        for path in files:
            target=folder/path
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text('original: '+path)
        cid=conversation(c,project)
        selected=next(a for a in c.get('/api/agents').json() if a['specialty']=='frontend')
        ENGINE.client=UIWorkers()
        prompt=('Modernize o UX/UI da Loja Virtual utilizando a Skill UI/UX Studio Pro. '
                'O Arquiteto IA deve coordenar o Frontend IA e o Designer IA, avaliar bibliotecas '
                'do catálogo e revisar alterações, com visual premium e responsivo.')
        r=c.post('/api/runs',json={'conversation_id':cid,'mode':'manual',
             'agent_ids':[selected['id']],'prompt':prompt},headers=HEADERS)
        assert r.status_code==200,r.text
        done=wait_for(c,r.json()['id'],timeout=9)
        assert done['status']=='completed',done.get('error')
        names=[step['name'] for step in done['steps']]
        assert len(names)==7,names
        assert names[0].startswith('Arquiteto')
        assert 'Designer' in names[1]
        assert len([name for name in names if name.startswith('Frontend')])==3
        assert c.get('/api/skills',params={'project_id':project}).json()[0]['enabled']
        assert not (folder/'frontend/src/components/NavBar.tsx').exists()
        for path in files:assert (folder/path).read_text()=='original: '+path
        proposals=c.get(f'/api/projects/{project}/workspace').json()['proposals']
        pending=[p for p in proposals if p['status']=='pending']
        assert len(pending)==3,pending
        assert all(p['files'][0]['replace'] for p in pending)
        assert 'Aguardando revisão e aprovação' in done['output']
        assert 'planejamento/revisão' in done['output']
        events=ENGINE.db.all('SELECT event,payload FROM events WHERE run_id=?',(r.json()['id'],))
        import json as jsonlib
        assert any(e['event']=='ui_skill_activated' for e in events)
        assert any(e['event']=='run_created' and jsonlib.loads(e['payload']).get('ui_implementation')
                   for e in events)


def test_chat_project_selector_rebinds_only_empty_drafts_and_revokes_authority(tmp_path):
    """Switching a draft project must clear old architect authority and use new skill scope."""
    with TestClient(app) as c:
        first=setup(c,tmp_path);prepare(c,first)
        second_response=c.post('/api/projects',json={'name':'Outro Projeto',
                              'description':'Separado'},headers=HEADERS)
        assert second_response.status_code==200,second_response.text
        second=second_response.json()['id']
        cid=conversation(c,first)
        activate=c.post(f'/api/projects/{first}/skills/ux-ui-studio-pro',
                        json={'enabled':True},headers=HEADERS)
        assert activate.status_code==200
        assert c.post(f'/api/conversations/{cid}/architect-delegation',
                      json={'enabled':True},headers=HEADERS).json()['enabled']
        owner=c.get('/api/me').json()['id']
        assert 'SKILL UI/UX STUDIO PRO' in ENGINE.skills.guide(owner,cid,'frontend')
        assert c.post(f'/api/conversations/{cid}/project',
                      json={'project_id':second}).status_code==403
        switched=c.post(f'/api/conversations/{cid}/project',
                        json={'project_id':second},headers=HEADERS)
        assert switched.status_code==200,switched.text
        assert switched.json()['project_id']==second
        assert c.get(f'/api/conversations/{cid}/architect-delegation').json()['enabled'] is False
        assert ENGINE.skills.guide(owner,cid,'frontend')==''
        assert c.get('/api/skills',params={'project_id':first}).json()[0]['enabled']
        assert not c.get('/api/skills',params={'project_id':second}).json()[0]['enabled']
        enabled=c.post(f'/api/projects/{second}/skills/ux-ui-studio-pro',
                       json={'enabled':True},headers=HEADERS)
        assert enabled.status_code==200
        assert 'SKILL UI/UX STUDIO PRO' in ENGINE.skills.guide(owner,cid,'frontend')
        unbound=c.post(f'/api/conversations/{cid}/project',
                       json={'project_id':None},headers=HEADERS)
        assert unbound.status_code==200
        assert unbound.json()['project_id'] is None
        assert ENGINE.skills.guide(owner,cid,'frontend')==''


def test_chat_project_selector_never_moves_an_existing_conversation_history(tmp_path):
    with TestClient(app) as c:
        first=setup(c,tmp_path);prepare(c,first)
        second=c.post('/api/projects',json={'name':'Segundo','description':''},
                      headers=HEADERS).json()['id']
        cid=conversation(c,first)
        owner=c.get('/api/me').json()['id']
        from central.database import uid, utcnow
        ENGINE.db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                          (uid(),cid,owner,'user',None,'Pedido feito no primeiro projeto',utcnow()))
        response=c.post(f'/api/conversations/{cid}/project',
                        json={'project_id':second},headers=HEADERS)
        assert response.status_code==409
        assert 'nova conversa' in response.json()['detail'].lower()
        assert c.get('/api/conversations').json()[0]['project_id']==first
        assert c.get(f'/api/conversations/{cid}/messages').json()[0]['content']=='Pedido feito no primeiro projeto'
        # A new conversation, as used by the UI, can safely select the other project.
        fresh=conversation(c,second)
        assert c.get('/api/conversations').json()[0]['id']==fresh


def test_chat_project_selector_respects_owner_and_does_not_grant_skills(tmp_path):
    from test_workspace import register
    with TestClient(app) as c1,TestClient(app) as c2:
        first=setup(c1,tmp_path);prepare(c1,first)
        second=c1.post('/api/projects',json={'name':'Outros','description':''},
                       headers=HEADERS).json()['id']
        own_chat=conversation(c1,first)
        register(c2)
        other=c2.post('/api/projects',json={'name':'Alheio','description':''},
                      headers=HEADERS).json()['id']
        assert c1.post(f'/api/conversations/{own_chat}/project',
                       json={'project_id':other},headers=HEADERS).status_code==404
        assert c2.post(f'/api/conversations/{own_chat}/project',
                       json={'project_id':second},headers=HEADERS).status_code==404
        assert c1.get(f'/api/conversations/{own_chat}/architect-delegation').json()['enabled'] is False


def test_chat_project_selector_protects_run_bound_to_draft(tmp_path):
    from central.database import uid, utcnow
    with TestClient(app) as c:
        first=setup(c,tmp_path);prepare(c,first)
        second=c.post('/api/projects',json={'name':'Outro','description':''},headers=HEADERS).json()['id']
        cid=conversation(c,first)
        owner=c.get('/api/me').json()['id']
        runid=uid();now=utcnow()
        ENGINE.db.execute('''INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,
                   created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                   (runid,owner,cid,'Projeto anterior','completed','manual','[]','[]',now,now))
        assert c.post(f'/api/conversations/{cid}/project',
                      json={'project_id':second},headers=HEADERS).status_code==409
        assert c.get('/api/conversations').json()[0]['project_id']==first



def test_disabled_designer_explains_exact_blocker_without_duplicate_chat_bubbles(tmp_path):
    """Regression for screenshot: UI selected, Skill active, but run silently rejected."""
    with TestClient(app) as c:
        project=setup(c,tmp_path);prepare(c,project)
        cid=conversation(c,project)
        enabled=c.post(f'/api/projects/{project}/skills/ux-ui-studio-pro',
                       json={'enabled':True},headers=HEADERS)
        assert enabled.status_code==200,enabled.text
        agents=c.get('/api/agents').json()
        designer=next(a for a in agents if a['specialty']=='design')
        ENGINE.db.execute('UPDATE agents SET enabled=0 WHERE id=?',(designer['id'],))
        prompt=('Modernize o UX/UI da Loja Virtual utilizando a Skill UI/UX Studio Pro. '
                'O Arquiteto IA deve coordenar o Frontend IA e o Designer IA, '
                'avaliar quais bibliotecas são necessárias e revisar as alterações.')
        for attempt in range(3):
            response=c.post('/api/runs',json={
                'conversation_id':cid,'mode':'auto','prompt':prompt},headers=HEADERS)
            assert response.status_code==422,response.text
            assert 'Designer IA está desativado' in response.json()['detail']
            assert c.get(f'/api/conversations/{cid}/messages').json()==[]
            assert not [r for r in c.get('/api/runs').json() if r['conversation_id']==cid]
        ENGINE.db.execute('UPDATE agents SET enabled=1 WHERE id=?',(designer['id'],))
        from central.engine import ui_execution_plan
        plan=ui_execution_plan(c.get('/api/agents').json(),prompt,'auto',[],True)
        assert plan is not None and len(plan)==7


def test_unbound_project_explains_skill_issue_without_chat_ghost_message(tmp_path):
    with TestClient(app) as c:
        from test_workspace import register
        register(c)
        response=c.post('/api/conversations',json={'title':'Sem projeto'},headers=HEADERS)
        cid=response.json()['id']
        prompt='Modernize o UX/UI da Loja Virtual utilizando a Skill UI/UX Studio Pro.'
        result=c.post('/api/runs',json={
            'conversation_id':cid,'mode':'auto','prompt':prompt},headers=HEADERS)
        assert result.status_code==422,result.text
        assert 'não está vinculada a um projeto' in result.json()['detail']
        assert c.get(f'/api/conversations/{cid}/messages').json()==[]
        assert not [r for r in c.get('/api/runs').json() if r['conversation_id']==cid]



def test_modified_specialties_keep_default_agent_roles_without_rewriting_database(tmp_path, monkeypatch):
    """Regression for screenshot: UI shows three available names but their freeform
    specialty fields are descriptive Portuguese text, not canonical role identifiers.
    The architect can coordinate the real 6-stage workflow with explicit delegation.
    """
    from central.roles import worker_role, role_source
    from central.engine import ui_execution_plan
    from test_workspace import add_provider
    from central.main import ENGINE

    descriptors={
        'Arquiteto IA': 'Coordenar tarefas e resultados',
        'Frontend IA': 'React, HTML, CSS e interfaces',
        'Designer IA': 'UI/UX, estilos e experiências',
    }
    expected={'Arquiteto IA':'architecture','Frontend IA':'frontend','Designer IA':'design'}

    class CompatWorkers:
        async def stream(self,provider,key,model,system,messages):
            if 'ARQUITETO REVISOR AUTORIZADO' in system:
                yield '{"decision":"approve","reason":"Alteração revisada conforme a delegação."}'
            elif 'UI_STAGE_PLANNING' in system:
                ticks=chr(96)*3
                yield 'Plano de execução real.\n'+ticks+'central-packages\n'
                yield '{"manager":"npm","packages":["lucide-react"]}\n'+ticks
            elif 'UI_STAGE_DESIGN' in system:
                yield 'Design system premium, mobile-first e acessível.'
            elif 'UI_STAGE_IMPLEMENT' in system:
                import re
                target=re.search(r'UMA alteração completa para ([\w./-]+)\.',system)
                assert target is not None
                name=target.group(1)
                content=(':root{color:#293047}' if name.endswith('.css') else
                         'export default function App(){return <main>Nova vitrine</main>}'
                         if name.endswith('/App.tsx') else
                         'export default function ProductCard(){return <article>Produto</article>}')
                yield json.dumps({'files':[{'path':name,'content':content}]})
            elif 'UI_STAGE_TEST' in system:
                yield 'Análise QA concluída.'
            elif 'UI_STAGE_REVIEW' in system:
                yield 'Revisado: preservar endpoint FastAPI.'
            else:
                raise AssertionError('Unexpected system role: '+system[:150])

    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project);add_provider(c,'fake',1)
        for name,descriptive_specialty in descriptors.items():
            agent=next(a for a in c.get('/api/agents').json() if a['name']==name)
            ENGINE.db.execute('UPDATE agents SET specialty=? WHERE id=?',
                              (descriptive_specialty,agent['id']))
        agents=c.get('/api/agents').json()
        for name,role in expected.items():
            a=next(a for a in agents if a['name']==name)
            assert a['enabled']==1
            assert a['specialty']==descriptors[name]
            assert a['resolved_role']==worker_role(a)==role
            assert a['role_source']==role_source(a)=='name'
        assert len([a for a in agents if a['name'] in descriptors])==3
        frontend=folder/'frontend/src';(frontend/'components').mkdir(parents=True)
        originals=['frontend/src/App.tsx','frontend/src/index.css',
                   'frontend/src/components/ProductCard.tsx']
        for name in originals:
            (folder/name).write_text('old '+name)
        backend=folder/'backend';backend.mkdir()
        (backend/'main.py').write_text('preserve FastAPI')
        cid=conversation(c,project)
        assert c.post(f'/api/projects/{project}/skills/ux-ui-studio-pro',
                      json={'enabled':True},headers=HEADERS).status_code==200
        assert c.post(f'/api/conversations/{cid}/architect-delegation',
                      json={'enabled':True},headers=HEADERS).json()['enabled'] is True
        plan=ui_execution_plan(agents,
            'Modernize o UX/UI da Loja Virtual utilizando a Skill UI/UX Studio Pro. '
            'O Arquiteto IA deve coordenar o Frontend IA e Designer IA.',
            'auto',[],True)
        assert plan is not None and len(plan)==7
        calls=[]
        def fake_install(self,owner,proj,manager,packages):
            calls.append((manager,packages))
            return {'ok':True,'manager':manager,'packages':packages,
                    'exit_code':0,'output':'mock'}
        monkeypatch.setattr(SkillsHub,'_install_sync',fake_install)
        ENGINE.client=CompatWorkers()
        prompt=('Modernize o UX/UI da Loja Virtual utilizando a Skill UI/UX Studio Pro. '
                'O Arquiteto IA deve coordenar o Frontend IA e o Designer IA, '
                'avaliar bibliotecas do catálogo e revisar alterações.')
        r=c.post('/api/runs',json={'conversation_id':cid,'prompt':prompt,'mode':'auto'},
                 headers=HEADERS)
        assert r.status_code==200,r.text
        done=wait_for(c,r.json()['id'],timeout=9)
        assert done['status']=='completed',done.get('error')
        assert len(done['steps'])==7
        for name in originals:
            assert (folder/name).read_text()!=('old '+name)
        assert (backend/'main.py').read_text()=='preserve FastAPI'
        assert len(ENGINE.db.all('SELECT * FROM architect_approval_log WHERE run_id=?',
                                 (r.json()['id'],)))==3
        assert calls==[('npm',['lucide-react'])]
        # User profile is preserved, not rewritten to our canonical codes.
        for name in descriptors:
            a=next(a for a in c.get('/api/agents').json() if a['name']==name)
            assert a['specialty']==descriptors[name]


def test_custom_role_alias_never_overrides_conflicting_canonical_specialty():
    from central.roles import worker_role,role_source
    assert worker_role({'name':'Arquiteto IA','specialty':'backend'})=='backend'
    assert role_source({'name':'Arquiteto IA','specialty':'backend'})=='canonical'
    assert worker_role({'name':'Qualquer usuário','specialty':'texto livre'})=='texto livre'
    assert worker_role({'name':'Designer IA','specialty':'UI/UX'})=='design'
    assert worker_role({'name':'Frontend IA','specialty':'front-end'})=='frontend'
