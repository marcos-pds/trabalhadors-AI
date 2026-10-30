"""Quotas are server-owned, per-user and enforced within an atomic run insert."""
import uuid
import pytest
from fastapi.testclient import TestClient

from central.database import Database, utcnow
from central.engine import Engine
from central.quotas import QuotaExceeded, limits, usage
from central.main import app


def fresh(db):
    db.execute('INSERT INTO users VALUES(?,?,?,?)',
               ('user','user@local.test','hash',utcnow()))
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
               ('chat','user','Chat',None,utcnow(),utcnow()))
    db.execute(
        'INSERT INTO agents(id,user_id,name,specialty,instructions,avatar,created_at) '
        'VALUES(?,?,?,?,?,?,?)',
        ('agent','user','Pesquisa','research','Responda','◉',utcnow()))


def create(engine, idempotency=None):
    return engine.create_run('user','chat','Analise tendências de design',
                             'manual',agent_ids=['agent'],
                             idempotency_key=idempotency)


def test_daily_quota_preserves_idempotent_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_MAX_RUNS_PER_DAY','1')
    monkeypatch.setenv('CENTRAL_MAX_ACTIVE_RUNS','4')
    db=Database(tmp_path / 'quota.db')
    try:
        fresh(db)
        engine=Engine(db,None)
        monkeypatch.setattr(engine,'schedule',lambda _:None)
        rid=create(engine,'request-one')
        assert create(engine,'request-one')==rid
        with pytest.raises(QuotaExceeded,match='diária'):
            create(engine,'request-two')
        assert usage(db,'user')['runs_last_24h']==1
        assert len(db.all('SELECT id FROM steps'))==1
    finally:db.close()


def test_active_run_quota_frees_when_job_completes(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_MAX_RUNS_PER_DAY','50')
    monkeypatch.setenv('CENTRAL_MAX_ACTIVE_RUNS','1')
    db=Database(tmp_path / 'active.db')
    try:
        fresh(db)
        engine=Engine(db,None)
        monkeypatch.setattr(engine,'schedule',lambda _:None)
        rid=create(engine)
        with pytest.raises(QuotaExceeded,match='simultâneas'):
            create(engine)
        db.execute("UPDATE runs SET status='completed' WHERE id=?",(rid,))
        assert create(engine)!=rid
        assert usage(db,'user')['active_runs']==1
    finally:db.close()


def test_http_quota_rejection_returns_429(monkeypatch):
    monkeypatch.setenv('CENTRAL_MAX_RUNS_PER_DAY','1')
    monkeypatch.setenv('CENTRAL_MAX_ACTIVE_RUNS','4')
    headers={'X-Central-Request':'1'}
    with TestClient(app) as client:
        account=client.post('/api/register',headers=headers,json={
            'email':uuid.uuid4().hex+'@example.org','password':'longenoughpassword'})
        assert account.status_code==200,account.text
        convo=client.post('/api/conversations',headers=headers,
                          json={'title':'Quota'})
        assert convo.status_code==200,convo.text
        payload={'conversation_id':convo.json()['id'],
                 'prompt':'Explique design de software','mode':'auto'}
        first=client.post('/api/runs',headers=headers,json=payload)
        assert first.status_code==200,first.text
        second=client.post('/api/runs',headers=headers,json=payload)
        assert second.status_code==429,second.text
