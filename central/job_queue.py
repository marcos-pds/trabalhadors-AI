"""Durable SQLite job dispatch with atomic leases for a local or split-process MVP.

Queue status is not business run status. The queue is an execution transport.
A fresh opaque lease_token identifies each claim, even if a worker ID is reused.
Acknowledgements without that token fail closed. Tokens are never in summaries.
Workers acquire with BEGIN IMMEDIATE to prevent simultaneous claims across
connections/processes. Crashed jobs are reclaimable only after lease expiry.
"""
import os
import time
import uuid
from .database import utcnow


class JobQueue:
    def __init__(self, db, lease_seconds=90, clock=None, max_attempts=None):
        self.db = db
        self.lease_seconds = max(20, int(lease_seconds))
        self.clock = clock or time.time
        try:
            self.max_attempts = int(
                os.environ.get('CENTRAL_MAX_JOB_ATTEMPTS', '5')
                if max_attempts is None else max_attempts)
        except (TypeError, ValueError) as exc:
            raise ValueError('CENTRAL_MAX_JOB_ATTEMPTS deve ser entre 1 e 20.') from exc
        if not 1 <= self.max_attempts <= 20:
            raise ValueError('CENTRAL_MAX_JOB_ATTEMPTS deve ser entre 1 e 20.')

    def enqueue(self, run_id):
        with self.db.lock, self.db.conn:
            row = self.db.conn.execute(
                'SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None or row['status'] not in ('queued', 'running', 'awaiting_approval'):
                return False
            self.db.conn.execute(
                """INSERT INTO job_queue(run_id,state,lease_owner,lease_until,
                   available_at,queued_at,updated_at)
                   VALUES(?,'queued',NULL,NULL,0,?,?)
                   ON CONFLICT(run_id) DO UPDATE SET
                       state=CASE WHEN job_queue.state='claimed'
                                 THEN job_queue.state ELSE 'queued' END,
                       available_at=CASE WHEN job_queue.state='claimed'
                                         THEN job_queue.available_at ELSE 0 END,
                       attempts=CASE WHEN job_queue.state IN
                            ('completed','paused','failed','cancelled')
                            THEN 0 ELSE job_queue.attempts END,
                       last_error=CASE WHEN job_queue.state IN
                            ('completed','paused','failed','cancelled')
                            THEN NULL ELSE job_queue.last_error END,
                       lease_token=CASE WHEN job_queue.state IN
                            ('completed','paused','failed','cancelled')
                            THEN NULL ELSE job_queue.lease_token END,
                       updated_at=excluded.updated_at""",
                (run_id, utcnow(), utcnow()))
        return True

    def claim(self, owner=None, per_user_limit=2):
        """Atomically claim one job or dead-letter exhausted abandoned leases.

        Each expired lease is fenced by its last owner and counted. A job
        repeatedly abandoned by dead workers is marked failed rather than
        endlessly replayed. Re-queued jobs that were explicitly resumed by
        a user start with a fresh attempt budget.
        """
        if type(per_user_limit) is not int or per_user_limit < 1:
            raise ValueError('per_user_limit must be positive')
        owner = owner or uuid.uuid4().hex
        now = self.clock()
        with self.db.lock:
            self.db.conn.execute('BEGIN IMMEDIATE')
            try:
                row = None
                # Bound maintenance work so one call cannot monopolize SQLite.
                for _ in range(24):
                    candidate = self.db.conn.execute(
                        """SELECT q.run_id,q.state,q.attempts,
                                  q.lease_until,r.user_id
                           FROM job_queue q JOIN runs r ON r.id=q.run_id
                           WHERE r.status IN ('queued','running','awaiting_approval')
                             AND ((q.state='queued' AND q.available_at <= ?)
                               OR (q.state='claimed' AND q.lease_until <= ?))
                             AND (SELECT COUNT(*) FROM job_queue active
                                  JOIN runs ar ON ar.id=active.run_id
                                  WHERE ar.user_id=r.user_id AND active.state='claimed'
                                    AND active.lease_until > ?) < ?
                           ORDER BY q.available_at, q.queued_at, q.run_id
                           LIMIT 1""", (now,now,now,per_user_limit)).fetchone()
                    if candidate is None:
                        break
                    if (candidate['state'] == 'claimed'
                            and candidate['attempts'] >= self.max_attempts):
                        rid = candidate['run_id']
                        message = ('Tarefa interrompida após '
                                   + str(self.max_attempts)
                                   + ' tentativas de execução; verifique o worker '
                                     'e retome manualmente se for seguro.')
                        self.db.conn.execute(
                            """UPDATE job_queue SET state='failed',lease_owner=NULL,
                               lease_until=NULL,lease_token=NULL,last_error=?,updated_at=?
                               WHERE run_id=? AND state='claimed'""",
                            ('lease_attempts_exhausted',utcnow(),rid))
                        self.db.conn.execute(
                            """UPDATE runs SET status='failed',error=?,updated_at=?
                               WHERE id=? AND status IN
                               ('queued','running','awaiting_approval')""",
                            (message,utcnow(),rid))
                        self.db.conn.execute(
                            'INSERT INTO events(run_id,event,payload,created_at) VALUES(?,?,?,?)',
                            (rid,'queue_attempts_exhausted',
                             '{"reason":"lease_attempts_exhausted"}',utcnow()))
                        continue
                    lease_token = uuid.uuid4().hex
                    self.db.conn.execute(
                        """UPDATE job_queue SET state='claimed',lease_owner=?,
                           lease_token=?,lease_until=?,attempts=attempts+1,updated_at=?
                           WHERE run_id=?""",
                        (owner,lease_token,now+self.lease_seconds,utcnow(),candidate['run_id']))
                    row = candidate
                    break
                self.db.conn.execute('COMMIT')
            except BaseException:
                self.db.conn.execute('ROLLBACK')
                raise
        return {'run_id':row['run_id'],'owner':owner,
                'lease_token':lease_token,
                'recovered':row['state']=='claimed',
                'attempt':row['attempts']+1} if row else None

    def heartbeat(self, run_id, owner, lease_token=None):
        if not isinstance(lease_token, str) or not lease_token:
            return False
        with self.db.lock, self.db.conn:
            changed = self.db.conn.execute(
                """UPDATE job_queue SET lease_until=?,updated_at=?
                   WHERE run_id=? AND state='claimed' AND lease_owner=?
                         AND lease_token=? AND lease_until>?""",
                (self.clock()+self.lease_seconds,utcnow(),run_id,owner,lease_token,self.clock())).rowcount
        return bool(changed)

    def finish(self, run_id, owner, state, error=None, lease_token=None):
        if state not in ('completed','paused','failed','cancelled','queued'):
            raise ValueError('Invalid queue terminal state')
        if not isinstance(lease_token, str) or not lease_token:
            return False
        with self.db.lock, self.db.conn:
            changed = self.db.conn.execute(
                """UPDATE job_queue SET state=?,lease_owner=NULL,
                       lease_until=NULL,lease_token=NULL,last_error=?,updated_at=?
                   WHERE run_id=? AND lease_owner=? AND lease_token=? AND state='claimed'
                         AND lease_until>?""",
                (state,str(error)[:240] if error else None,utcnow(),run_id,owner,lease_token,self.clock())).rowcount
        return bool(changed)

    def cancel(self, run_id):
        with self.db.lock, self.db.conn:
            self.db.conn.execute(
                """UPDATE job_queue SET state='cancelled',
                   lease_owner=NULL,lease_until=NULL,lease_token=NULL,updated_at=?
                   WHERE run_id=?""", (utcnow(),run_id))

    def reconcile(self):
        """Repair jobs whose business run finished before the worker could ack."""
        with self.db.lock, self.db.conn:
            for status, queue_state in (
                ('completed','completed'), ('failed','failed'),
                ('paused_limit','paused'), ('cancelled','cancelled')):
                self.db.conn.execute(
                    """UPDATE job_queue SET state=?,lease_owner=NULL,
                       lease_until=NULL,lease_token=NULL,updated_at=?
                       WHERE run_id IN (SELECT id FROM runs WHERE status=?)
                         AND state!=?""",
                    (queue_state,utcnow(),status,queue_state))
        return True

    def details(self, run_id):
        return self.db.one(
            'SELECT run_id,state,attempts,queued_at,updated_at,'
            'lease_until,available_at,last_error FROM job_queue WHERE run_id=?',
            (run_id,))

    def summary(self, user_id):
        return self.db.all(
            """SELECT q.state,COUNT(*) AS total FROM job_queue q
               JOIN runs r ON r.id=q.run_id
               WHERE r.user_id=? GROUP BY q.state""", (user_id,))
