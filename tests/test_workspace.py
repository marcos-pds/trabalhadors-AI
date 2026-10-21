"""Workspace integration: sandbox, diff, approval and multi-agent staging."""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from central.main import app, ENGINE
from central.workspace import Workspaces
from test_app import HEADERS, register, add_provider, wait_for


def setup(c, tmp_path):
    register(c)
    ENGINE.workspaces = Workspaces(ENGINE.db,root=tmp_path/'root')
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


def test_model_run_stages_files_without_writing(tmp_path):
    class ProjectFake:
        async def stream(self,provider,key,model,system,messages):
            assert 'central-files' in system
            assert 'Arquivos atuais:' in system
            yield '''Arquivo proposto:\n```central-files\n{"files":[{"path":"backend/main.py","content":"print('ola')\\n"}]}\n```'''
    with TestClient(app) as c:
        project=setup(c,tmp_path);folder=prepare(c,project)
        add_provider(c,'fake',1)
        ENGINE.client=ProjectFake()
        conversation=c.post('/api/conversations',json={'title':'Projeto','project_id':project},headers=HEADERS)
        assert conversation.status_code==200
        run=c.post('/api/runs',json={'conversation_id':conversation.json()['id'],
                   'mode':'team','prompt':'Crie backend API e frontend React'},headers=HEADERS)
        assert run.status_code==200
        assert wait_for(c,run.json()['id'])['status']=='completed'
        info=c.get(f'/api/projects/{project}/workspace').json()
        pending=[x for x in info['proposals'] if x['status']=='pending']
        assert pending,'Executores devem preparar as alterações do modelo'
        assert not (folder/'backend/main.py').exists()
        assert decide(c,project,pending[0]['id']).status_code==200
        assert (folder/'backend/main.py').read_text()=="print('ola')\n"


def test_multi_file_preflight_prevents_partial_write(tmp_path):
    with TestClient(app) as c:
        p=setup(c,tmp_path);folder=prepare(c,p)
        s=c.post(f'/api/projects/{p}/workspace/proposals',json={'files':[
          {'path':'new.txt','content':'new'},{'path':'existing.txt','content':'changed'}]},headers=HEADERS)
        assert s.status_code==200
        (folder/'existing.txt').write_text('external')
        assert decide(c,p,s.json()['id']).status_code==409
        assert not (folder/'new.txt').exists()
