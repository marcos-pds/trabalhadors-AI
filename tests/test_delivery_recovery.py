import json

import pytest

from central.database import Database, utcnow
from central.agent_registry import AgentRegistry
from central.delivery_recovery import queue_delivery_repair
from central.worker_collaboration import send, inbox, acknowledge


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / 'recovery.sqlite3')
    now = utcnow()
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('u', 'local@example.test', 'hash', now))
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', ('c', 'u', 'Test', None, now, now))
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at,autonomous) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
               ('r', 'u', 'c', 'Crie um site', 'running', 'team', '[]', '[]', now, now, 1))
    for role in ('code', 'review'):
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
                   (role, 'u', role, role, 'Check the project', now))
        db.execute('INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                   (role, 'r', role, 'agent', role, '[]', 'completed', now, now))
    yield db
    db.close()


def test_final_contract_recovery_is_persistently_bounded_and_selects_reviewer(setup):
    db = setup
    run = db.one('SELECT * FROM runs WHERE id=?', ('r',))
    registry = AgentRegistry(db)
    emit = lambda *args: None
    for attempt in (1, 2):
        assert queue_delivery_repair(db, registry, run, 'Missing test evidence', emit)
        assert db.one('SELECT status FROM steps WHERE id=?', ('review',))['status'] == 'queued'
        assert db.one('SELECT status FROM steps WHERE id=?', ('code',))['status'] == 'completed'
        db.execute("UPDATE steps SET status='completed' WHERE id='review'")
    assert not queue_delivery_repair(db, registry, run, 'Still missing', emit)
    assert not db.conn.in_transaction
    assert db.one("SELECT count(*) n FROM events WHERE event='delivery_repair_queued'")['n'] == 2


@pytest.mark.parametrize('status', ['cancelled', 'awaiting_approval', 'failed', 'paused_limit'])
def test_recovery_preserves_user_or_permission_stop(setup, status):
    db = setup
    db.execute('UPDATE runs SET status=?', (status,))
    assert not queue_delivery_repair(db, AgentRegistry(db), db.one('SELECT * FROM runs'), 'error', lambda *args: None)
    assert db.one('SELECT status FROM runs')['status'] == status


def test_worker_identity_comes_from_step_and_delivery_is_idempotent(setup):
    db = setup
    result = send(db, 'u', 'r', 'code', {'action': 'agent_message',
                  'recipient_agent_id': 'review', 'message_type': 'result',
                  'content': 'Files are ready for review.'}, lambda *args: None)
    assert result['success']
    messages = inbox(db, 'u', 'r', 'review')
    assert messages[0]['sender_agent_id'] == 'code'
    acknowledge(db, 'u', 'r', 'review', messages)
    acknowledge(db, 'u', 'r', 'review', messages)
    assert inbox(db, 'u', 'r', 'review') == []
    with pytest.raises(ValueError):
        send(db, 'u', 'r', 'code', {'action': 'agent_message', 'sender_agent_id': 'review'}, lambda *args: None)


def test_delegation_refuses_completed_target(setup):
    with pytest.raises(ValueError, match='etapa'):
        send(setup, 'u', 'r', 'code', {'action': 'agent_message',
             'recipient_agent_id': 'review', 'message_type': 'task_request',
             'content': 'Do more work'}, lambda *args: None)


def test_large_message_content_is_delivered_whole_and_artifacts_are_retrievable(setup):
    from central.worker_collaboration import read_message
    db = setup
    content = 'x' * 32768
    artifacts = [{'data': 'z' * 60000}]
    result = send(db, 'u', 'r', 'code', {'action': 'agent_message',
                  'recipient_agent_id': 'review', 'message_type': 'result',
                  'content': content, 'artifacts': artifacts}, lambda *args: None)
    messages = inbox(db, 'u', 'r', 'review')
    assert messages[0]['content'] == content
    assert len(json.dumps(messages, ensure_ascii=False)) < 48000
    encoded, offset = '', 0
    while offset is not None:
        page = read_message(db, 'u', 'r', 'review', {'action': 'agent_message_read',
                            'message_id': result['message_id'], 'offset': offset})
        encoded += page['data']
        offset = page['next_offset']
    assert json.loads(encoded)['artifacts'] == artifacts
    with pytest.raises(ValueError):
        read_message(db, 'u', 'r', 'code', {'action': 'agent_message_read', 'message_id': result['message_id']})


def test_handoff_and_step_status_can_rollback_as_one_transaction(setup):
    from central.worker_collaboration import publish_handoff
    db = setup
    db.execute("UPDATE steps SET status='queued',deps='[\"code\"]' WHERE id='review'")
    db.conn.execute('BEGIN IMMEDIATE')
    db.execute("UPDATE steps SET status='completed' WHERE id='code'")
    publish_handoff(db, db.one('SELECT * FROM runs'), db.one("SELECT * FROM steps WHERE id='code'"),
                    'Verified result', lambda *args: None)
    assert db.one('SELECT COUNT(*) n FROM agent_messages')['n'] == 1
    db.conn.execute('ROLLBACK')
    assert db.one('SELECT COUNT(*) n FROM agent_messages')['n'] == 0


def test_message_acknowledgement_can_rollback_with_step_completion(setup):
    db = setup
    send(db, 'u', 'r', 'code', {'action': 'agent_message', 'recipient_agent_id': 'review',
         'message_type': 'result', 'content': 'Ready'}, lambda *args: None)
    received = inbox(db, 'u', 'r', 'review')
    db.conn.execute('BEGIN IMMEDIATE')
    acknowledge(db, 'u', 'r', 'review', received)
    assert inbox(db, 'u', 'r', 'review') == []
    db.conn.execute('ROLLBACK')
    assert inbox(db, 'u', 'r', 'review')[0]['state'] == 'created'
