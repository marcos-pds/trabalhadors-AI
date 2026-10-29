"""Agent mail integration checks against real, file-backed SQLite."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from central.database import Database, utcnow
from central import agent_messages as mail


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / 'mail.sqlite')
    for sql in mail.SCHEMA:
        database.execute(sql)
    now = utcnow()
    for owner in ('u', 'other'):
        database.execute('INSERT INTO users VALUES(?,?,?,?)', (owner, owner + '@test.local', 'hash', now))
        database.execute('INSERT INTO projects(id,user_id,name,created_at) VALUES(?,?,?,?)', (owner, owner, owner, now))
        database.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', (owner, owner, 'chat', owner, now, now))
    for run, owner in (('r', 'u'), ('r2', 'u'), ('foreign', 'other')):
        database.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (run, owner, owner, 'task', 'running', 'ask', '[]', '{}', now, now))
    for i in range(11):
        agent = str(i)
        database.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
                         (agent, 'other' if i == 10 else 'u', agent, 'code', '', now))
        if i != 9:
            database.execute('INSERT INTO steps(id,run_id,agent_id,name,deps,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                             (agent, 'r', agent, agent, '[]', 'pending', now, now))
    yield database
    database.close()


def send(db, **kwargs):
    values = dict(user_id='u', run_id='r', project_id='u', sender_agent_id='0',
                  recipient_agent_id='1', message_type='question', content='hello')
    values.update(kwargs)
    return mail.create_message(db, **values)


@pytest.mark.parametrize('kind', mail.MESSAGE_TYPES)
def test_roundtrip_delivery_and_reopen(db, kind):
    row = send(db, message_type=kind, artifacts=[{'path': 'src/main.py', 'lines': [1, 2]}])
    assert row['state'] == 'created' and row['delivered_at'] is None
    path = db.one('PRAGMA database_list')['file']
    second = Database(path)
    try:
        assert mail.list_messages(second, 'u', 'r', 'u')[0] == row
        delivered = mail.acknowledge_message(second, 'u', 'r', 'u', row['id'], '1')
        assert delivered['state'] == 'delivered' and delivered['delivered_at']
        assert mail.acknowledge_message(db, 'u', 'r', 'u', row['id'], '1') == delivered
        assert mail.list_messages(db, 'u', 'r', 'u', state='created') == []
        assert mail.list_messages(db, 'u', 'r', 'u', recipient_agent_id='1') == [delivered]
    finally:
        second.close()


@pytest.mark.parametrize('changes', [dict(user_id='other'), dict(project_id=None),
    dict(project_id='other'), dict(run_id='foreign'), dict(sender_agent_id='9'),
    dict(recipient_agent_id='10'), dict(run_id='r2'), dict(message_type='unknown'),
    dict(content=' '), dict(content='é' * 16385), dict(artifacts={}),
    dict(artifacts=[{'bad': float('nan')}]), dict(artifacts=[{'bad': object()}]),
    dict(artifacts=[{}] * 65), dict(artifacts=[{'data': 'x' * 65536}])])
def test_rejected_creation_leaves_no_rows(db, changes):
    with pytest.raises(ValueError):
        send(db, **changes)
    assert mail.list_messages(db, 'u', 'r', 'u') == []
    assert not db.conn.in_transaction


def test_scope_and_acknowledgement_cannot_be_bypassed(db):
    row = send(db)
    for owner, run, project, recipient in [('other', 'r', 'u', '1'),
            ('u', 'r2', 'u', '1'), ('u', 'r', None, '1'), ('u', 'r', 'u', '0')]:
        with pytest.raises(ValueError):
            mail.acknowledge_message(db, owner, run, project, row['id'], recipient)
    with pytest.raises(ValueError):
        mail.list_messages(db, 'other', 'r', 'u')
    assert mail.list_messages(db, 'u', 'r2', 'u') == []
    with pytest.raises(ValueError):
        send(db, parent_message_id='missing')
    db.execute('UPDATE agent_messages SET run_id=? WHERE id=?', ('r2', row['id']))
    with pytest.raises(ValueError, match='outside'):
        send(db, parent_message_id=row['id'])


def test_delegation_depth_cycles_and_parent_authority(db):
    parent = send(db, message_type='task_request')
    with pytest.raises(ValueError, match='recipient'):
        send(db, message_type='task_request', parent_message_id=parent['id'])
    with pytest.raises(ValueError, match='cycle'):
        send(db, message_type='task_request', sender_agent_id='1', recipient_agent_id='0', parent_message_id=parent['id'])
    for i in range(1, 8):
        parent = send(db, message_type='task_request', sender_agent_id=str(i),
                      recipient_agent_id=str(i + 1), parent_message_id=parent['id'])
    with pytest.raises(ValueError, match='depth'):
        send(db, message_type='task_request', sender_agent_id='8', recipient_agent_id='0', parent_message_id=parent['id'])
    db.execute('UPDATE agent_messages SET parent_message_id=id WHERE id=?', (parent['id'],))
    with pytest.raises(ValueError, match='cycle'):
        send(db, parent_message_id=parent['id'])


def test_task_budget_is_atomic_across_connections(db):
    for _ in range(mail.MAX_TASKS_PER_RUN - 1):
        send(db, message_type='task_request')
    path = db.one('PRAGMA database_list')['file']
    connections = [Database(path), Database(path)]
    def attempt(connection):
        try:
            send(connection, message_type='task_request')
            return True
        except ValueError as exc:
            assert 'task limit' in str(exc)
            return False
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(attempt, connections)) == [False, True]
        assert db.one("SELECT count(*) n FROM agent_messages WHERE message_type='task_request'")['n'] == mail.MAX_TASKS_PER_RUN
        assert send(db, message_type='result')['state'] == 'created'
    finally:
        for connection in connections:
            connection.close()


def test_null_project_and_pagination(db):
    db.execute('UPDATE conversations SET project_id=NULL WHERE id=?', ('u',))
    send(db, project_id=None)
    send(db, project_id=None)
    assert len(mail.list_messages(db, 'u', 'r', None, limit=1, offset=1)) == 1
    for kwargs in ({'limit': 0}, {'limit': 501}, {'offset': -1}, {'state': 'bad'}):
        with pytest.raises(ValueError):
            mail.list_messages(db, 'u', 'r', None, **kwargs)
