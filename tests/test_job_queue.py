"""Durable SQLite job queue: atomic claims, leases, tenancy and recovery."""
import asyncio
import threading
import time

import pytest

from central.database import Database, utcnow
from central.job_queue import JobQueue
from central.engine import Engine


def seed(db, user_id, rid):
    db.execute('INSERT OR IGNORE INTO users VALUES(?,?,?,?)',
               (user_id, user_id + '@example.org', 'hash', utcnow()))
    cid = 'chat-' + user_id
    db.execute('INSERT OR IGNORE INTO conversations VALUES(?,?,?,?,?,?)',
               (cid, user_id, 'Task', None, utcnow(), utcnow()))
    db.execute(
        'INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,'
        'agent_ids,plan,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
        (rid, user_id, cid, 'Explain', 'queued', 'auto', '[]', '[]', utcnow(), utcnow()))


def test_claim_exclusive_across_two_connections(tmp_path):
    path = tmp_path / 'queue.db'
    first = Database(path)
    second = Database(path)
    try:
        seed(first, 'u1', 'job1')
        q1, q2 = JobQueue(first), JobQueue(second)
        assert q1.enqueue('job1')
        barrier = threading.Barrier(2)
        got = []
        def claim(queue, owner):
            barrier.wait()
            got.append(queue.claim(owner))
        t1 = threading.Thread(target=claim, args=(q1,'owner-1'))
        t2 = threading.Thread(target=claim, args=(q2,'owner-2'))
        t1.start(); t2.start(); t1.join(); t2.join()
        claimed = [x for x in got if x]
        assert len(claimed) == 1
        assert claimed[0]['run_id'] == 'job1'
        assert q1.details('job1')['state'] == 'claimed'
        assert not q2.finish('job1', 'unknown-owner', 'completed', lease_token=claimed[0]['lease_token'])
        assert q1.finish('job1', claimed[0]['owner'], 'completed', lease_token=claimed[0]['lease_token'])
        assert q2.details('job1')['state'] == 'completed'
    finally:
        first.close()
        second.close()


def test_expired_lease_recovers_and_stale_owner_cannot_ack(tmp_path):
    db = Database(tmp_path / 'recover.db')
    now = [1000.0]
    q = JobQueue(db, lease_seconds=30, clock=lambda: now[0])
    try:
        seed(db, 'owner', 'r1')
        q.enqueue('r1')
        old = q.claim('worker-one')
        assert old['attempt'] == 1
        now[0] += 20
        assert q.heartbeat('r1','worker-one',old['lease_token'])
        now[0] += 15
        assert q.claim('worker-two') is None
        now[0] += 16
        recovered = q.claim('worker-two')
        assert recovered and recovered['recovered'] is True
        assert recovered['attempt'] == 2
        assert not q.finish('r1','worker-one','completed',lease_token=old['lease_token'])
        assert q.finish('r1','worker-two','completed',lease_token=recovered['lease_token'])
        assert q.details('r1')['attempts'] == 2
    finally:
        db.close()


def test_user_fair_limit_and_cancel_pending(tmp_path):
    db = Database(tmp_path / 'fair.db')
    try:
        seed(db,'u1','a')
        seed(db,'u1','b')
        seed(db,'u2','c')
        q=JobQueue(db)
        for rid in ('a','b','c'):
            q.enqueue(rid)
        one=q.claim('first-worker', per_user_limit=1)
        assert one['run_id'] == 'a'
        two=q.claim('second-worker', per_user_limit=1)
        assert two['run_id'] == 'c'
        db.execute("UPDATE runs SET status='cancelled' WHERE id='b'")
        q.cancel('b')
        assert q.details('b')['state']=='cancelled'
        assert q.claim('third-worker', per_user_limit=1) is None
        assert q.finish('a','first-worker','completed',lease_token=one['lease_token'])
        assert not q.enqueue('b')  # cancelled business run is not allowed to restart
    finally:
        db.close()


def test_engine_starts_job_via_persistent_queue_and_ack(tmp_path, monkeypatch):
    db=Database(tmp_path / 'engine.db')
    seed(db, 'u', 'run')
    engine=Engine(db, None)
    engine.job_mode='embedded'
    async def fake_process(run_id):
        assert engine.queue.details(run_id)['state']=='claimed'
        db.execute("UPDATE runs SET status='completed' WHERE id=?", (run_id,))
    try:
        monkeypatch.setattr(engine,'process',fake_process)
        async def go():
            engine.schedule('run')
            for _ in range(60):
                if not engine.running and engine.queue.details('run')['state']=='completed':
                    return
                await asyncio.sleep(.01)
            raise AssertionError('Durable job did not complete')
        asyncio.run(go())
        assert engine.queue.details('run')['attempts']==1
    finally:
        db.close()



def test_api_only_enqueue_is_consumed_by_dedicated_worker(tmp_path, monkeypatch):
    path = tmp_path / 'split.db'
    db_api = Database(path)
    db_worker = Database(path)
    try:
        seed(db_api, 'u', 'split')
        api_engine = Engine(db_api, None)
        api_engine.job_mode = 'api'
        worker = Engine(db_worker, None)
        worker.job_mode = 'worker'
        async def finish(run_id):
            db_worker.execute("UPDATE runs SET status='completed' WHERE id=?",
                              (run_id,))
        monkeypatch.setattr(worker,'process',finish)
        async def go():
            api_engine.schedule('split')
            assert not api_engine.running
            assert api_engine.queue.details('split')['state'] == 'queued'
            worker.dispatch_ready()
            for _ in range(80):
                if worker.queue.details('split')['state'] == 'completed':
                    return
                await asyncio.sleep(.01)
            raise AssertionError('Worker could not dispatch shared SQLite job')
        asyncio.run(go())
        assert db_api.one("SELECT status FROM runs WHERE id='split'")['status'] == 'completed'
    finally:
        db_api.close()
        db_worker.close()


def test_cancel_is_visible_across_processes_without_false_completion(tmp_path, monkeypatch):
    path = tmp_path / 'shared.db'
    db_api, db_worker = Database(path), Database(path)
    try:
        seed(db_api, 'u', 'task')
        api = Engine(db_api,None)
        api.job_mode = 'api'
        worker = Engine(db_worker,None)
        worker.job_mode = 'worker'
        running = asyncio.Event()
        stopped = asyncio.Event()
        async def process(run_id):
            running.set()
            try:
                await asyncio.sleep(10)
                db_worker.execute("UPDATE runs SET status='completed' WHERE id=?",
                                  (run_id,))
            except asyncio.CancelledError:
                stopped.set()
                raise
        monkeypatch.setattr(worker,'process',process)
        async def go():
            api.schedule('task')
            worker.dispatch_ready()
            await asyncio.wait_for(running.wait(), timeout=2)
            api.cancel('task')
            await asyncio.wait_for(stopped.wait(), timeout=4)
            for _ in range(50):
                if not worker.running:
                    break
                await asyncio.sleep(.02)
        asyncio.run(go())
        assert db_worker.one("SELECT status FROM runs WHERE id='task'")['status'] == 'cancelled'
        assert api.queue.details('task')['state'] == 'cancelled'
    finally:
        db_api.close()
        db_worker.close()



def test_recovery_attempt_limit_moves_abandoned_run_to_failed_atomically(tmp_path):
    db=Database(tmp_path/'exhaust.db')
    now=[1000.0]
    q=JobQueue(db,lease_seconds=30,clock=lambda:now[0],max_attempts=2)
    try:
        seed(db,'u','abandoned')
        assert q.enqueue('abandoned')
        first=q.claim('worker-one')
        assert first['attempt']==1
        now[0]+=31
        second=q.claim('worker-two')
        assert second['recovered'] is True and second['attempt']==2
        now[0]+=31
        assert q.claim('worker-three') is None
        status=q.details('abandoned')
        assert status['state']=='failed'
        assert status['last_error']=='lease_attempts_exhausted'
        assert status['attempts']==2
        run=db.one('SELECT status,error FROM runs WHERE id=?',('abandoned',))
        assert run['status']=='failed'
        assert '2 tentativas' in run['error']
        events=db.all("SELECT event,payload FROM events WHERE run_id=?",('abandoned',))
        assert [r['event'] for r in events]==['queue_attempts_exhausted']
        assert not q.finish('abandoned','worker-two','completed',lease_token=second['lease_token'])
        assert not q.heartbeat('abandoned','worker-two',second['lease_token'])
    finally:
        db.close()


def test_expired_lease_owner_cannot_renew_or_ack_even_before_reclaim(tmp_path):
    db=Database(tmp_path/'expired.db')
    now=[1000.0]
    q=JobQueue(db,lease_seconds=30,clock=lambda:now[0])
    try:
        seed(db,'u','late')
        q.enqueue('late')
        old=q.claim('old')
        assert old['attempt']==1
        now[0]+=31
        assert not q.heartbeat('late','old',old['lease_token'])
        assert not q.finish('late','old','completed',lease_token=old['lease_token'])
        assert q.details('late')['state']=='claimed'
        fresh=q.claim('fresh')
        assert fresh['recovered'] is True
        assert q.finish('late','fresh','completed',lease_token=fresh['lease_token'])
    finally:
        db.close()


def test_manual_resume_after_exhaustion_resets_attempt_budget(tmp_path):
    db=Database(tmp_path/'resume.db')
    now=[1000.0]
    q=JobQueue(db,lease_seconds=30,clock=lambda:now[0],max_attempts=1)
    try:
        seed(db,'u','task')
        q.enqueue('task')
        old=q.claim('old')
        assert old['attempt']==1
        now[0]+=31
        assert q.claim('another') is None
        assert q.details('task')['state']=='failed'
        db.execute("UPDATE runs SET status='queued' WHERE id='task'")
        assert q.enqueue('task')
        assert q.details('task')['attempts']==0
        restarted=q.claim('new')
        assert restarted['attempt']==1 and not restarted['recovered']
    finally:
        db.close()


def test_exhausted_work_does_not_starve_other_pending_user(tmp_path):
    db=Database(tmp_path/'fair-dead-letter.db')
    now=[1000.0]
    q=JobQueue(db,lease_seconds=30,clock=lambda:now[0],max_attempts=1)
    try:
        seed(db,'u1','bad')
        seed(db,'u2','good')
        q.enqueue('bad')
        assert q.claim('dead')['run_id']=='bad'
        now[0]+=31
        q.enqueue('good')
        next_run=q.claim('live')
        assert next_run['run_id']=='good'
        assert q.details('bad')['state']=='failed'
    finally:
        db.close()


@pytest.mark.parametrize('value', ['0','21','banana','-1'])
def test_queue_attempt_configuration_fails_closed(tmp_path,monkeypatch,value):
    db=Database(':memory:')
    try:
        monkeypatch.setenv('CENTRAL_MAX_JOB_ATTEMPTS',value)
        with pytest.raises(ValueError,match='1 e 20'):
            JobQueue(db)
    finally:
        db.close()


def test_worker_liveness_distinguishes_active_and_stale_without_exposing_ids(tmp_path):
    from central.worker_liveness import beat, snapshot, forget, cleanup_stale
    from datetime import datetime, timedelta, timezone
    db=Database(tmp_path/'workers.db')
    try:
        beat(db,'worker-private-id','worker',2)
        beat(db,'other-private-id','embedded',1)
        result=snapshot(db)
        assert result['active_workers']==2 and result['active_jobs_reported']==3
        assert result['distributed'] is False
        assert 'worker-private-id' not in str(result)
        yesterday=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        db.execute("UPDATE worker_liveness SET last_seen_at=? WHERE worker_id=?",
                   (yesterday,'other-private-id'))
        result=snapshot(db)
        assert result['active_workers']==1
        assert result['stale_workers']==1
        assert cleanup_stale(db)==1
        forget(db,'worker-private-id')
        assert snapshot(db)['active_workers']==0
    finally:
        db.close()


def test_background_worker_emits_heartbeat_and_unregisters_when_stopped(tmp_path):
    from central.worker_liveness import snapshot
    db=Database(tmp_path/'registry.db')
    engine=Engine(db,None)
    engine.job_mode='worker'
    async def go():
        task=asyncio.create_task(engine.poll_jobs())
        for _ in range(90):
            if snapshot(db)['active_workers']==1:
                break
            await asyncio.sleep(.02)
        assert snapshot(db)['active_workers']==1
        engine.shutting_down=True
        await asyncio.wait_for(task,timeout=2)
        assert snapshot(db)['active_workers']==0
    try:
        asyncio.run(go())
    finally:
        db.close()


def test_migration_v8_is_additive_and_idempotent(tmp_path):
    from central.migrations import migrate
    db=Database(tmp_path/'migrate.db')
    try:
        assert [r['version'] for r in db.all('SELECT version FROM schema_migrations')] == list(range(1,9))
        migrate(db)
        assert len(db.all('SELECT version FROM schema_migrations'))==8
        assert db.one("SELECT name FROM sqlite_master WHERE name='worker_liveness'")
    finally:
        db.close()


def test_fencing_token_blocks_stale_completion_even_when_worker_id_reused(tmp_path):
    db = Database(tmp_path / 'fencing.db')
    now = [1000.0]
    queue = JobQueue(db, lease_seconds=30, clock=lambda: now[0])
    try:
        seed(db, 'u', 'same-owner')
        assert queue.enqueue('same-owner')
        old = queue.claim('restarted-worker')
        assert old and old['lease_token']
        assert not queue.heartbeat('same-owner', 'restarted-worker')
        assert not queue.finish('same-owner', 'restarted-worker', 'completed')
        now[0] += 31
        latest = queue.claim('restarted-worker')
        assert latest and latest['recovered'] is True
        assert latest['lease_token'] != old['lease_token']
        assert not queue.heartbeat('same-owner', 'restarted-worker', old['lease_token'])
        assert not queue.finish('same-owner', 'restarted-worker', 'completed',
                                lease_token=old['lease_token'])
        assert queue.heartbeat('same-owner', 'restarted-worker', latest['lease_token'])
        assert queue.finish('same-owner', 'restarted-worker', 'completed',
                            lease_token=latest['lease_token'])
        assert 'lease_token' not in queue.details('same-owner')
    finally:
        db.close()


def test_fencing_token_invalid_after_cancel_and_manual_resume(tmp_path):
    db = Database(tmp_path / 'cancel-fencing.db')
    try:
        seed(db, 'u', 'cancel')
        queue = JobQueue(db)
        assert queue.enqueue('cancel')
        old = queue.claim('worker')
        queue.cancel('cancel')
        assert not queue.heartbeat('cancel', 'worker', old['lease_token'])
        assert not queue.finish('cancel', 'worker', 'completed',
                                lease_token=old['lease_token'])
        db.execute("UPDATE runs SET status='queued' WHERE id='cancel'")
        assert queue.enqueue('cancel')
        new = queue.claim('worker')
        assert new['lease_token'] != old['lease_token']
        assert queue.finish('cancel', 'worker', 'completed',
                            lease_token=new['lease_token'])
    finally:
        db.close()
