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
        assert not q2.finish('job1', 'unknown-owner', 'completed')
        assert q1.finish('job1', claimed[0]['owner'], 'completed')
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
        assert q.heartbeat('r1','worker-one')
        now[0] += 15
        assert q.claim('worker-two') is None
        now[0] += 16
        recovered = q.claim('worker-two')
        assert recovered and recovered['recovered'] is True
        assert recovered['attempt'] == 2
        assert not q.finish('r1','worker-one','completed')
        assert q.finish('r1','worker-two','completed')
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
        assert q.finish('a','first-worker','completed')
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
