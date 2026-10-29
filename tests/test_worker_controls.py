"""Real SQLite cooperative control transitions, tenancy and durability."""
import json

import pytest
from fastapi import HTTPException

from central.database import Database, utcnow
from central.worker_controls import (SCHEMA, request_control, check_control,
                                     list_controls, WorkerControlPaused,
                                     WorkerControlCancelled)


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / 'controls.sqlite')
    for sql in SCHEMA:
        db.execute(sql)
    now = utcnow()
    for user in ('u', 'other'):
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, user + '@test.local', 'hash', now))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', (user, user, user, None, now, now))
        db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (user, user, user, 'task', 'running', 'team', '[]', '[]', now, now))
        db.execute('INSERT INTO organizations(id,name,created_by,created_at) VALUES(?,?,?,?)', (user, user, user, now))
        db.execute('INSERT INTO organization_members VALUES(?,?,?,?)', (user, user, 'admin', now))
        db.execute('INSERT INTO organization_runs VALUES(?,?)', (user, user))
    for sid, status, deps in [('a', 'running', []), ('b', 'queued', ['a'])]:
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
                   (sid, 'u', sid, 'code', '', now))
        db.execute('INSERT INTO steps(id,run_id,agent_id,name,status,deps,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                   (sid, 'u', sid, sid, status, json.dumps(deps), now, now))
    yield db
    db.close()


def test_pause_consumed_once_but_stop_persists_and_explicit_resume_requeues(db):
    first = request_control(db, 'u', 'u', 'a', 'pause')
    assert request_control(db, 'u', 'u', 'a', 'pause') == first
    assert db.one("SELECT status FROM steps WHERE id='a'")['status'] == 'running'
    with pytest.raises(WorkerControlPaused):
        check_control(db, 'u', 'u', 'a')
    applied = db.one("SELECT * FROM worker_controls WHERE step_id='a'")
    assert not applied['pending'] and applied['applied_at']
    with pytest.raises(WorkerControlPaused):
        check_control(db, 'u', 'u', 'a')
    assert db.one("SELECT * FROM worker_controls WHERE step_id='a'") == applied
    db.execute("UPDATE steps SET status='paused_operator',error='paused' WHERE id='a'")
    db.execute("UPDATE runs SET status='paused_operator' WHERE id='u'")
    resumed = request_control(db, 'u', 'u', 'a', 'resume')
    assert resumed['request_id'] != first['request_id']
    assert db.one("SELECT status,error FROM steps WHERE id='a'") == {'status': 'queued', 'error': None}
    assert check_control(db, 'u', 'u', 'a')['operation'] == 'resume'
    assert check_control(db, 'u', 'u', 'a') is None
    assert request_control(db, 'u', 'u', 'a', 'resume')['request_id'] == resumed['request_id']


def test_cancel_queued_is_durable_and_cannot_resume(db):
    requested = request_control(db, 'u', 'u', 'b', 'cancel')
    path = db.one('PRAGMA database_list')['file']
    second = Database(path)
    try:
        for _ in range(2):
            with pytest.raises(WorkerControlCancelled):
                check_control(second, 'u', 'u', 'b')
        assert not second.conn.in_transaction
        assert request_control(second, 'u', 'u', 'b', 'cancel')['request_id'] == requested['request_id']
        for operation in ('resume', 'pause'):
            with pytest.raises(HTTPException):
                request_control(second, 'u', 'u', 'b', operation)
        second.execute("UPDATE steps SET status='cancelled' WHERE id='b'")
        assert request_control(second, 'u', 'u', 'b', 'cancel')['request_id'] == requested['request_id']
    finally:
        second.close()


@pytest.mark.parametrize('user,rid,sid,org', [('other', 'u', 'a', None),
    ('u', 'other', 'a', None), ('u', 'u', 'missing', None), ('u', 'u', 'a', 'other')])
def test_scope_rejections_do_not_write(db, user, rid, sid, org):
    with pytest.raises(HTTPException):
        request_control(db, user, rid, sid, 'pause', organization_id=org)
    assert db.all('SELECT * FROM worker_controls') == []
    assert not db.conn.in_transaction


def test_org_write_role_and_membership_are_rechecked(db):
    request_control(db, 'u', 'u', 'a', 'pause', organization_id='u')
    db.execute("UPDATE organization_members SET role='analyst' WHERE user_id='u'")
    with pytest.raises(HTTPException) as error:
        request_control(db, 'u', 'u', 'a', 'resume')
    assert error.value.status_code == 403
    db.execute("DELETE FROM organization_members WHERE user_id='u'")
    with pytest.raises(HTTPException):
        list_controls(db, 'u', 'u')
    with pytest.raises(HTTPException):
        check_control(db, 'u', 'u', 'a')


@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled', 'skipped'])
def test_terminal_step_rejected(db, status):
    db.execute('UPDATE steps SET status=? WHERE id=?', (status, 'a'))
    with pytest.raises(HTTPException):
        request_control(db, 'u', 'u', 'a', 'pause')


@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled'])
def test_terminal_run_rejected(db, status):
    db.execute('UPDATE runs SET status=? WHERE id=?', (status, 'u'))
    with pytest.raises(HTTPException):
        request_control(db, 'u', 'u', 'a', 'pause')


def test_invalid_resume_and_operation_and_dependency_diagnostics(db):
    for operation in ('resume', 'invalid'):
        with pytest.raises(HTTPException):
            request_control(db, 'u', 'u', 'a', operation)
    request_control(db, 'u', 'u', 'a', 'pause')
    result = list_controls(db, 'u', 'u')
    assert len(result['pending_controls']) == 1
    assert result['steps'][1]['blockers'] == [{'step_id': 'a', 'name': 'a', 'status': 'paused'}]
    assert result['steps'][1]['deps'] == ['a']
    db.execute("UPDATE steps SET status='completed' WHERE id='a'")
    assert list_controls(db, 'u', 'u')['steps'][1]['blockers']


def test_queued_pause_then_resume_does_not_mark_step_running(db):
    request_control(db, 'u', 'u', 'b', 'pause')
    request_control(db, 'u', 'u', 'b', 'resume')
    assert check_control(db, 'u', 'u', 'b')['operation'] == 'resume'
    assert db.one("SELECT status FROM steps WHERE id='b'")['status'] == 'queued'
