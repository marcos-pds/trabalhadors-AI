"""Persistent agent mail. Install SCHEMA through the application migration ledger.

All public operations require the run owner and its exact project (None for an
unassigned conversation). Task limits count task_request messages, including
completed ones; root delegation has depth one. No engine actions are performed.
"""
import json
from contextlib import contextmanager

from .database import uid, utcnow

MESSAGE_TYPES = ('task_request', 'result', 'question', 'answer', 'blocker',
                 'review', 'correction', 'completion')
MAX_CONTENT_BYTES = 32768
MAX_ARTIFACTS_BYTES = 65536
MAX_ARTIFACTS = 64
MAX_DELEGATION_DEPTH = 8
MAX_TASKS_PER_RUN = 100

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    sender_agent_id TEXT NOT NULL REFERENCES agents(id),
    recipient_agent_id TEXT NOT NULL REFERENCES agents(id),
    message_type TEXT NOT NULL CHECK(message_type IN
      ('task_request','result','question','answer','blocker','review','correction','completion')),
    content TEXT NOT NULL CHECK(length(CAST(content AS BLOB)) BETWEEN 1 AND 32768),
    artifacts_json TEXT NOT NULL DEFAULT '[]'
      CHECK(length(CAST(artifacts_json AS BLOB)) <= 65536),
    parent_message_id TEXT REFERENCES agent_messages(id),
    state TEXT NOT NULL DEFAULT 'created' CHECK(state IN ('created','delivered')),
    created_at TEXT NOT NULL, delivered_at TEXT,
    CHECK((state='created' AND delivered_at IS NULL) OR
          (state='delivered' AND delivered_at IS NOT NULL)))""",
    'CREATE INDEX IF NOT EXISTS idx_agent_messages_run ON agent_messages(user_id,run_id,created_at,id)',
    'CREATE INDEX IF NOT EXISTS idx_agent_messages_inbox ON agent_messages(run_id,recipient_agent_id,state)',
)


@contextmanager
def _transaction(db):
    # BEGIN IMMEDIATE also serializes independent connections/processes, so
    # concurrent delegations cannot both pass the run task budget check.
    with db.lock:
        nested = db.conn.in_transaction
        savepoint = 'mail_' + uid().replace('-', '')
        db.conn.execute('SAVEPOINT ' + savepoint if nested else 'BEGIN IMMEDIATE')
        try:
            yield
            db.conn.execute('RELEASE ' + savepoint if nested else 'COMMIT')
        except BaseException:
            if nested:
                db.conn.execute('ROLLBACK TO ' + savepoint)
                db.conn.execute('RELEASE ' + savepoint)
            else:
                db.conn.execute('ROLLBACK')
            raise


def _scope(db, user_id, run_id, project_id):
    row = db.one('SELECT c.project_id FROM runs r JOIN conversations c '
                 'ON c.id=r.conversation_id WHERE r.id=? AND r.user_id=? '
                 'AND c.user_id=?', (run_id, user_id, user_id))
    if not row or row['project_id'] != project_id:
        raise ValueError('Run/project not found for owner')
    if project_id is not None and not db.one(
            'SELECT id FROM projects WHERE id=? AND user_id=?', (project_id, user_id)):
        raise ValueError('Project not found for owner')


def _participant(db, user_id, run_id, agent_id):
    if not db.one('SELECT a.id FROM agents a JOIN steps s ON s.agent_id=a.id '
                  'WHERE a.id=? AND a.user_id=? AND s.run_id=?',
                  (agent_id, user_id, run_id)):
        raise ValueError('Agent is not an owned participant in this run')


def _decode(row):
    row = dict(row)
    row['artifacts'] = json.loads(row.pop('artifacts_json'))
    return row


def create_message(db, user_id, run_id, project_id, sender_agent_id,
                   recipient_agent_id, message_type, content, *, artifacts=None,
                   parent_message_id=None):
    """Create mail atomically; replies may reference any same-run message.

    A child task must be delegated by the recipient of its parent. Task paths
    cannot revisit an agent; corrupt/cyclic parent chains are rejected too.
    """
    if message_type not in MESSAGE_TYPES:
        raise ValueError('Invalid message type')
    if not isinstance(content, str) or not content.strip() or len(content.encode('utf-8')) > MAX_CONTENT_BYTES:
        raise ValueError('Content must be nonempty and bounded')
    artifacts = [] if artifacts is None else artifacts
    if not isinstance(artifacts, list) or len(artifacts) > MAX_ARTIFACTS or any(
            not isinstance(item, dict) for item in artifacts):
        raise ValueError('Artifacts must be a bounded list of JSON objects')
    try:
        encoded = json.dumps(artifacts, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode('utf-8')) > MAX_ARTIFACTS_BYTES:
            raise ValueError('Artifacts too large')
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('Invalid or oversized artifacts JSON') from exc
    with _transaction(db):
        _scope(db, user_id, run_id, project_id)
        for agent in (sender_agent_id, recipient_agent_id):
            _participant(db, user_id, run_id, agent)
        ancestors, seen = [], set()
        parent = parent_message_id
        while parent is not None:
            if len(ancestors) >= 64:
                raise ValueError('Parent message chain limit')
            if parent in seen:
                raise ValueError('Parent message cycle')
            seen.add(parent)
            row = db.one('SELECT * FROM agent_messages WHERE id=? AND user_id=? AND run_id=?',
                         (parent, user_id, run_id))
            if not row or row['project_id'] != project_id:
                raise ValueError('Parent message outside run/project')
            ancestors.append(row)
            parent = row['parent_message_id']
        if message_type == 'task_request':
            if ancestors and ancestors[0]['recipient_agent_id'] != sender_agent_id:
                raise ValueError('Only parent recipient may delegate')
            tasks = [row for row in ancestors if row['message_type'] == 'task_request']
            if len(tasks) + 1 > MAX_DELEGATION_DEPTH:
                raise ValueError('Delegation depth limit')
            visited = {sender_agent_id}
            for row in tasks:
                visited.update((row['sender_agent_id'], row['recipient_agent_id']))
            if recipient_agent_id in visited:
                raise ValueError('Delegation agent cycle')
            count = db.one("SELECT count(*) AS n FROM agent_messages WHERE run_id=? AND message_type='task_request'", (run_id,))['n']
            if count >= MAX_TASKS_PER_RUN:
                raise ValueError('Run task limit')
        message_id = uid()
        db.execute('INSERT INTO agent_messages '
                   '(id,user_id,run_id,project_id,sender_agent_id,recipient_agent_id,message_type,content,artifacts_json,parent_message_id,created_at) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (message_id, user_id, run_id, project_id, sender_agent_id,
                    recipient_agent_id, message_type, content, encoded,
                    parent_message_id, utcnow()))
        return _decode(db.one('SELECT * FROM agent_messages WHERE id=?', (message_id,)))


def list_messages(db, user_id, run_id, project_id, *, recipient_agent_id=None,
                  state=None, limit=100, offset=0):
    """List in stable creation order; optional recipient filter is validated."""
    if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or offset < 0:
        raise ValueError('Invalid pagination')
    if state is not None and state not in ('created', 'delivered'):
        raise ValueError('Invalid state')
    with db.lock:
        _scope(db, user_id, run_id, project_id)
        query = 'SELECT * FROM agent_messages WHERE user_id=? AND run_id=? AND project_id IS ?'
        args = [user_id, run_id, project_id]
        if recipient_agent_id is not None:
            _participant(db, user_id, run_id, recipient_agent_id)
            query += ' AND recipient_agent_id=?'
            args.append(recipient_agent_id)
        if state is not None:
            query += ' AND state=?'
            args.append(state)
        return [_decode(row) for row in db.all(
            query + ' ORDER BY created_at,id LIMIT ? OFFSET ?', (*args, limit, offset))]


def acknowledge_message(db, user_id, run_id, project_id, message_id, recipient_agent_id):
    """Idempotently mark delivery; only the addressed participant can ack."""
    with _transaction(db):
        _scope(db, user_id, run_id, project_id)
        _participant(db, user_id, run_id, recipient_agent_id)
        row = db.one('SELECT * FROM agent_messages WHERE id=? AND user_id=? '
                     'AND run_id=? AND project_id IS ? AND recipient_agent_id=?',
                     (message_id, user_id, run_id, project_id, recipient_agent_id))
        if not row:
            raise ValueError('Message not found for recipient')
        if row['state'] == 'created':
            db.execute("UPDATE agent_messages SET state='delivered',delivered_at=? WHERE id=?",
                       (utcnow(), message_id))
        return _decode(db.one('SELECT * FROM agent_messages WHERE id=?', (message_id,)))
