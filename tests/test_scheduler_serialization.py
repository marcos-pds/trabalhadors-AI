"""Exercise the real scheduler with yielding workers and temporary SQLite state."""
import asyncio
import json

import pytest

from central.database import Database, utcnow
from central.engine import RunOrchestrator


@pytest.fixture
def scheduler(tmp_path):
    db = Database(tmp_path / 'scheduler.sqlite')
    now = utcnow()
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('u', 'u@example.test', 'hash', now))
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
               ('chat', 'u', 'Chat', None, now, now))
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,'
               'created_at,updated_at,autonomous) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
               ('r', 'u', 'chat', 'Organize tasks', 'queued', 'team', '[]', '[]', now, now, 1))
    db.execute('INSERT INTO run_workspace_bindings(run_id,user_id,folder,initial_mode,created_at) '
               'VALUES(?,?,?,?,?)', ('r', 'u', str(tmp_path), 'full', now))
    for name in ('first', 'second'):
        db.execute('INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?,?)',
                   (name, 'r', name, 'agent', name, '[]', 'queued', now, now))
    engine = RunOrchestrator.__new__(RunOrchestrator)
    engine.db = db
    engine.emit = lambda *args: None
    yield engine
    db.close()


@pytest.mark.parametrize('autonomous,bound,expected_peak', [
    (True, True, 1), (False, True, 2), (False, False, 2),
])
def test_ready_workers_share_workspace_serially_only_when_autonomous(
        scheduler, autonomous, bound, expected_peak):
    db = scheduler.db
    db.execute('UPDATE runs SET autonomous=? WHERE id=?', (int(autonomous), 'r'))
    if not bound:
        db.execute('DELETE FROM run_workspace_bindings')

    async def exercise():
        active, peak = 0, 0
        both_started = asyncio.Event()
        completed = []

        async def execute(run, step):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                both_started.set()
            if expected_peak == 2:
                # Require real concurrent progress, not merely two calls.
                await asyncio.wait_for(both_started.wait(), timeout=2)
            else:
                # Yield with the shared workspace held; a parallel sibling
                # would enter before this worker releases it.
                await asyncio.sleep(0)
            active -= 1
            completed.append(step['id'])
            db.execute("UPDATE steps SET status='completed',output='done' WHERE id=?", (step['id'],))

        scheduler.execute_step = execute
        await scheduler.process('r')
        assert peak == expected_peak
        assert set(completed) == {'first', 'second'}

    asyncio.run(exercise())
    assert db.one("SELECT status FROM runs WHERE id='r'")['status'] == 'completed'


def test_serial_scheduler_reloads_new_dependencies_before_next_ready_worker(scheduler):
    db = scheduler.db
    order = []

    async def execute(run, step):
        order.append(step['id'])
        if step['id'] == 'first':
            now = utcnow()
            db.execute('INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,created_at,updated_at) '
                       'VALUES(?,?,?,?,?,?,?,?,?)',
                       ('dynamic', 'r', 'delegate', 'agent', 'Delegated task',
                        json.dumps(['first']), 'queued', now, now))
            # second was ready in the previous snapshot. Its new prerequisite
            # must be reloaded rather than executing the rest of that snapshot.
            db.execute('UPDATE steps SET deps=? WHERE id=?', (json.dumps(['dynamic']), 'second'))
        await asyncio.sleep(0)
        db.execute("UPDATE steps SET status='completed',output='done' WHERE id=?", (step['id'],))

    scheduler.execute_step = execute
    asyncio.run(scheduler.process('r'))
    assert order == ['first', 'dynamic', 'second']
    assert db.one("SELECT status FROM runs WHERE id='r'")['status'] == 'completed'
