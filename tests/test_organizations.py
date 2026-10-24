"""Organization boundaries, member RBAC, legacy data, and team budget tests."""
import sqlite3
import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest
from central.database import Database, utcnow
from central.main import app, DB, ENGINE

HEADERS={'X-Central-Request':'1'}


def register(client):
    email = uuid.uuid4().hex + '@example.org'
    resp = client.post('/api/register',headers=HEADERS,
        json={'email':email,'password':'secure-password-123'})
    assert resp.status_code==200,resp.text
    return resp.json(), email


def org_create(client,name):
    r=client.post('/api/organizations',headers=HEADERS,json={'name':name})
    assert r.status_code==200,r.text
    return r.json()['id']


def project_create(client,name,org):
    r=client.post('/api/projects',headers=HEADERS,
                  json={'name':name,'organization_id':org})
    assert r.status_code==200,r.text
    return r.json()['id']


def test_projects_are_shared_only_with_members_and_roles_enforced(monkeypatch):
    monkeypatch.setattr(ENGINE,'schedule',lambda _:None)
    with TestClient(app) as alice, TestClient(app) as bob, TestClient(app) as carol:
        a,ae=register(alice)
        b,be=register(bob)
        c,ce=register(carol)
        org=org_create(alice,'Estudio Alpha')
        pid=project_create(alice,'Projeto da equipe',org)
        # Other user, other organization: identical resource URI not discoverable.
        assert bob.put(f'/api/projects/{pid}/memory',headers=HEADERS,
                       json={'notes':'hack'}).status_code==404
        assert carol.get('/api/projects').json()==[]
        assert bob.post('/api/conversations',headers=HEADERS,
                        json={'project_id':pid}).status_code==404
        invited=alice.put(f'/api/organizations/{org}/members',headers=HEADERS,
                          json={'email':be,'role':'analyst'})
        assert invited.status_code==200,invited.text
        assert pid in {p['id'] for p in bob.get('/api/projects').json()}
        # Analyst can see organization project but cannot mutate or run it.
        assert bob.put(f'/api/projects/{pid}/memory',headers=HEADERS,
                       json={'notes':'edited'}).status_code==403
        assert bob.post('/api/conversations',headers=HEADERS,
                        json={'project_id':pid}).status_code==403
        assert bob.put(f'/api/organizations/{org}/members',headers=HEADERS,
                       json={'email':ce,'role':'admin'}).status_code==403
        changed=alice.put(f'/api/organizations/{org}/members',headers=HEADERS,
                          json={'email':be,'role':'operator'})
        assert changed.status_code==200,changed.text
        chat=bob.post('/api/conversations',headers=HEADERS,
                      json={'title':'Projeto interno','project_id':pid})
        assert chat.status_code==200,chat.text
        cid=chat.json()['id']
        own_convo=alice.get('/api/conversations/'+cid)
        assert own_convo.status_code==404  # Private chat is not implicitly shared
        notes=bob.put(f'/api/projects/{pid}/memory',headers=HEADERS,
                      json={'notes':'Contrato verificado'})
        assert notes.status_code==200 and 'Contrato' in notes.json()['memory_notes']
        assert carol.get('/api/projects').json()==[]
        assert carol.get(f'/api/conversations/{cid}').status_code==404
        # Revocation cannot retain access to the shared project/context.
        removed=alice.delete(f'/api/organizations/{org}/members/{b["id"]}',
                             headers=HEADERS)
        assert removed.status_code==200,removed.text
        assert pid not in {p['id'] for p in bob.get('/api/projects').json()}
        assert bob.get('/api/conversations/'+cid).status_code==404
        assert bob.get(f'/api/conversations/{cid}/messages').status_code==404
        assert bob.get('/api/conversations').json()==[]
        assert bob.put(f'/api/projects/{pid}/memory',headers=HEADERS,
                       json={'notes':'new'}).status_code==404
        assert alice.get('/api/organizations/'+org+'/usage').status_code==200
        assert carol.get('/api/organizations/'+org+'/usage').status_code==404


def test_personal_organizations_and_last_admin_protection():
    with TestClient(app) as alice, TestClient(app) as bob:
        a,ae=register(alice)
        b,be=register(bob)
        personal=next(x for x in alice.get('/api/organizations').json() if x['is_personal'])
        assert personal['role']=='admin'
        assert alice.put('/api/organizations/'+personal['id']+'/members',
                         headers=HEADERS,json={'email':be,'role':'admin'}).status_code==403
        org=org_create(alice,'Minha equipe')
        assert alice.put('/api/organizations/'+org+'/members',
                         headers=HEADERS,json={'email':be,'role':'operator'}).status_code==200
        assert alice.put('/api/organizations/'+org+'/members',
                         headers=HEADERS,json={'email':ae,'role':'analyst'}).status_code==409
        assert alice.delete('/api/organizations/'+org+'/members/'+a['id'],
                            headers=HEADERS).status_code==409
        assert bob.get('/api/organizations').json()[-1]['name'] in ('Minha equipe','Meu espaço')


def test_org_limits_enforced_by_engine_in_atomic_transaction(monkeypatch):
    monkeypatch.setattr(ENGINE,'schedule',lambda _:None)
    with TestClient(app) as alice, TestClient(app) as bob:
        a,ae=register(alice)
        b,be=register(bob)
        org=org_create(alice,'Equipe para cotas')
        assert alice.put(f'/api/organizations/{org}/members',headers=HEADERS,
                         json={'email':be,'role':'operator'}).status_code==200
        pid=project_create(alice,'Compartilhado',org)
        cid_a=alice.post('/api/conversations',headers=HEADERS,
                         json={'project_id':pid}).json()['id']
        cid_b=bob.post('/api/conversations',headers=HEADERS,
                       json={'project_id':pid}).json()['id']
        r=alice.put(f'/api/organizations/{org}/limits',headers=HEADERS,
                    json={'daily_run_limit':1,'active_run_limit':1,'estimated_budget_usd':0.25})
        assert r.status_code==200,r.text
        one=alice.post('/api/runs',headers=HEADERS,
                       json={'conversation_id':cid_a,'prompt':'Explique arquitetura',
                             'mode':'auto'})
        assert one.status_code==200,one.text
        two=bob.post('/api/runs',headers=HEADERS,
                     json={'conversation_id':cid_b,'prompt':'Explique arquitetura',
                           'mode':'auto'})
        assert two.status_code==429,two.text
        assert 'organização' in two.json()['detail']
        status=alice.get(f'/api/organizations/{org}/usage').json()
        assert status['daily_runs']==1
        assert status['active_runs']==1
        assert alice.get('/api/runs/'+one.json()['id']).json()['job'] is None  # schedule mocked
        assert bob.get('/api/runs/'+one.json()['id']).status_code==404


def test_upgrade_old_projects_without_copying_or_sharing_other_user_data(tmp_path):
    path=tmp_path/'legacy.db'
    db=Database(path)
    try:
        db.execute('INSERT INTO users VALUES(?,?,?,?)',
                   ('old','old@example.com','hash','now'))
        db.execute('INSERT INTO projects(id,user_id,name,description,created_at) '
                   'VALUES(?,?,?,?,?)',('oldp','old','Privado','Dados','now'))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                   ('oldc','old','Antiga','oldp','now','now'))
    finally:db.close()
    reopened=Database(path)
    try:
        p=reopened.one('SELECT organization_id FROM organization_projects WHERE project_id=?',
                       ('oldp',))
        assert p
        member=reopened.one('SELECT role FROM organization_members '
                            'WHERE organization_id=? AND user_id=?',
                            (p['organization_id'],'old'))
        assert member['role']=='admin'
        assert reopened.one('SELECT name FROM projects WHERE id=?',('oldp',))['name']=='Privado'
        assert reopened.one('SELECT project_id FROM conversations WHERE id=?',('oldc',))['project_id']=='oldp'
        assert len(reopened.all('SELECT id FROM organizations WHERE created_by=?',('old',)))==1
    finally:reopened.close()
    again=Database(path)
    try:
        assert len(again.all('SELECT id FROM organizations WHERE created_by=?',('old',)))==1
    finally:again.close()
