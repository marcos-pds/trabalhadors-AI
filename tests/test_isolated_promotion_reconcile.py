"""Real Git promotion, SQLite reconciliation and HTTP recovery; no inference."""
import asyncio
import json
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest
from fastapi import HTTPException

from central.computer_access import set_policy
from central.database import Database, utcnow
from central.engine import Engine
from central import isolated_workspaces as isolation
from central.organizations import ensure_personal
from central.worker_checkpoint import MAX_RESUMES, save_checkpoint
from central.workspace_guard import bind_run


pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='Real Git required')


def git(root, *args):
    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, timeout=15)


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_JOB_MODE', 'api')  # actual durable queue, no provider execution
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'host')
    root = tmp_path / 'workspace'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Lab')
    git(root, 'config', 'user.email', 'lab@example.invalid')
    (root / 'app.py').write_text('value = 1\n', encoding='utf-8')
    git(root, 'add', 'app.py')
    git(root, 'commit', '-qm', 'initial')
    db = Database(tmp_path / 'lab.sqlite')
    now = utcnow()
    for user in ('owner', 'other'):
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, user + '@example.test', 'hash', now))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', (user, user, user, None, now, now))
    org = ensure_personal(db, 'owner')
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,'
               'created_at,updated_at,autonomous) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
               ('run', 'owner', 'owner', 'Crie um app', 'running', 'team', '[]', '[]', now, now, 1))
    db.execute('INSERT INTO organization_runs VALUES(?,?)', ('run', org))
    for sid, role, state, deps in [('implement', 'backend', 'running', []),
                                   ('review', 'review', 'queued', ['implement'])]:
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
                   (sid, 'owner', sid, role, 'Do work', now))
        db.execute('INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,output,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (sid, 'run', sid, 'agent', sid, json.dumps(deps), state,
                    'Implemented and tested' if sid == 'implement' else None, now, now))
    set_policy(db, 'owner', 'full', str(root))
    bind_run(db, 'owner', 'run')
    isolation.configure_run(db, 'owner', 'run', True)
    worker = Path(isolation.prepare_step(db, 'owner', 'run', 'implement'))
    (worker / 'app.py').write_text('value = 2\n', encoding='utf-8')
    save_checkpoint(db, 'owner', 'run', 'implement', str(worker),
                    [{'role': 'user', 'content': 'original request'},
                     {'role': 'assistant', 'content': 'saved tool history'}],
                    changed_files=['app.py'], observed_actions=['write'], validation_failures=0,
                    rounds_total=7, actions_total=5, state='completed')
    assert isolation.finish_step(db, 'owner', 'run', 'implement')['state'] == 'pending_review'
    db.execute("UPDATE steps SET status='awaiting_integration' WHERE id='implement'")
    db.execute("UPDATE runs SET status='awaiting_integration' WHERE id='run'")
    engine = Engine(db, None)
    yield db, root, worker, engine
    db.close()


def promote(lab):
    db, root, _, _ = lab
    plan = isolation.review(db, 'owner', 'run', 'implement')
    assert isolation.approve(db, 'owner', 'run', 'implement', plan['confirmation'])['applied']
    assert (root / 'app.py').read_text(encoding='utf-8') == 'value = 2\n'
    return plan


def counts(db):
    return (db.one('SELECT COUNT(*) n FROM agent_messages')['n'],
            db.one("SELECT COUNT(*) n FROM events WHERE event='isolated_step_reconciled'")['n'])


def test_real_promotion_completes_once_with_atomic_handoff_and_unchanged_checkpoint(lab):
    db, root, _, engine = lab
    checkpoint = db.one('SELECT * FROM worker_checkpoints')
    promote(lab)
    assert engine.finish_promoted_step('run', 'implement', user_id='owner')['changed'] is True
    assert db.one("SELECT status FROM steps WHERE id='implement'")['status'] == 'completed'
    assert db.one("SELECT status FROM steps WHERE id='review'")['status'] == 'queued'
    assert counts(db) == (1, 1)
    mail = db.one('SELECT * FROM agent_messages')
    assert mail['recipient_agent_id'] == 'review' and mail['content'] == 'Implemented and tested'
    assert db.one('SELECT * FROM worker_checkpoints') == checkpoint
    # A downstream change cannot invalidate the historical receipt or replay mail.
    (root / 'app.py').write_text('value = 3\n', encoding='utf-8')
    assert engine.finish_promoted_step('run', 'implement', user_id='owner')['changed'] is False
    assert counts(db) == (1, 1)


def test_receipt_failure_rolls_back_status_and_mail_then_retries_safely(lab):
    db, _, _, engine = lab
    promote(lab)
    db.execute("CREATE TRIGGER deny_receipt BEFORE INSERT ON events "
               "WHEN NEW.event='isolated_step_reconciled' "
               "BEGIN SELECT RAISE(ABORT, 'receipt failure'); END")
    with pytest.raises(Exception, match='receipt failure'):
        engine.finish_promoted_step('run', 'implement')
    assert db.one("SELECT status FROM steps WHERE id='implement'")['status'] == 'awaiting_integration'
    assert counts(db) == (0, 0)
    assert not db.conn.in_transaction
    db.execute('DROP TRIGGER deny_receipt')
    assert engine.finish_promoted_step('run', 'implement')['changed']
    assert counts(db) == (1, 1)


@pytest.mark.parametrize('change', ['pending', 'forged_approved', 'tampered_root', 'foreign_owner',
                                  'wrong_step', 'revoked', 'switched_folder', 'wrong_agent', 'no_output'])
def test_unverified_promotion_or_scope_never_completes_or_sends_mail(lab, tmp_path, change):
    db, root, _, engine = lab
    if change not in ('pending', 'forged_approved'):
        promote(lab)
    user, step = 'owner', 'implement'
    if change == 'forged_approved':
        db.execute("UPDATE isolated_workspace_steps SET state='approved'")
    elif change == 'tampered_root':
        (root / 'app.py').write_text('operator changed this\n', encoding='utf-8')
    elif change == 'foreign_owner':
        user = 'other'
    elif change == 'wrong_step':
        step = 'review'
    elif change == 'revoked':
        set_policy(db, 'owner', 'blocked', '')
    elif change == 'switched_folder':
        alternate = tmp_path / 'alternate'
        alternate.mkdir()
        set_policy(db, 'owner', 'full', str(alternate))
    elif change == 'wrong_agent':
        db.execute("UPDATE agents SET user_id='other' WHERE id='implement'")
    elif change == 'no_output':
        db.execute("UPDATE steps SET output=NULL WHERE id='implement'")
    with pytest.raises(HTTPException):
        engine.finish_promoted_step('run', step, user_id=user)
    assert db.one("SELECT status FROM steps WHERE id='implement'")['status'] == 'awaiting_integration'
    assert counts(db) == (0, 0)
    assert not db.conn.in_transaction


@pytest.mark.parametrize('state', ['cancelled', 'failed', 'completed', 'running', 'queued', 'paused_limit'])
def test_first_reconciliation_requires_parked_run(lab, state):
    db, _, _, engine = lab
    promote(lab)
    db.execute("UPDATE runs SET status=? WHERE id='run'", (state,))
    with pytest.raises(HTTPException):
        engine.finish_promoted_step('run', 'implement')
    assert counts(db) == (0, 0)


@pytest.mark.parametrize('state', ['cancelled', 'failed', 'running', 'queued', 'completed'])
def test_incorrect_step_state_cannot_be_silently_completed(lab, state):
    db, _, _, engine = lab
    promote(lab)
    db.execute("UPDATE steps SET status=? WHERE id='implement'", (state,))
    with pytest.raises(HTTPException):
        engine.finish_promoted_step('run', 'implement')
    assert counts(db) == (0, 0)


def test_resume_recovers_promotion_without_reusing_token_or_replaying_implementer(lab):
    db, _, worker, engine = lab
    promote(lab)
    db.execute('UPDATE worker_checkpoints SET resumes=?', (MAX_RESUMES,))
    checkpoint = db.one('SELECT * FROM worker_checkpoints')
    engine.resume_run('run')
    assert db.one("SELECT status FROM runs WHERE id='run'")['status'] == 'queued'
    assert db.one("SELECT status FROM steps WHERE id='implement'")['status'] == 'completed'
    assert db.one('SELECT * FROM worker_checkpoints') == checkpoint
    assert db.one('SELECT folder FROM worker_checkpoints')['folder'] == str(worker)
    assert db.one("SELECT state FROM job_queue WHERE run_id='run'")['state'] == 'queued'
    assert counts(db) == (1, 1)
    order = []

    async def review_only(run, step):
        order.append(step['id'])
        # Avoid inference: the real scheduler should only dispatch the reviewer.
        raise RuntimeError('review boundary reached without inference')

    engine.execute_step = review_only
    asyncio.run(engine.process('run'))
    assert order == ['review']
    assert db.one('SELECT * FROM worker_checkpoints') == checkpoint


def test_premature_resume_does_not_requeue_or_spend_checkpoint_budget(lab):
    db, _, _, engine = lab
    checkpoint = db.one('SELECT * FROM worker_checkpoints')
    with pytest.raises(HTTPException):
        engine.resume_run('run')
    assert db.one("SELECT status FROM runs WHERE id='run'")['status'] == 'awaiting_integration'
    assert db.one('SELECT * FROM worker_checkpoints') == checkpoint
    assert db.one('SELECT * FROM job_queue') is None


def test_cancelled_isolated_run_can_resolve_checkpoint_without_reviving_tools(lab):
    db, _, worker, engine = lab
    db.execute("UPDATE isolated_workspace_steps SET state='active'")
    db.execute("UPDATE steps SET status='queued' WHERE id='implement'")
    db.execute("UPDATE runs SET status='cancelled' WHERE id='run'")
    with pytest.raises(HTTPException):
        isolation.execution_folder(db, 'owner', 'run', 'implement')
    assert isolation.checkpoint_folder(db, 'owner', 'run', 'implement') == str(worker)
    assert isolation.status(db, 'owner', 'run')['enabled']
    engine.resume_run('run')
    assert db.one("SELECT status FROM runs WHERE id='run'")['status'] == 'queued'
    assert db.one('SELECT folder FROM worker_checkpoints')['folder'] == str(worker)
    set_policy(db, 'owner', 'blocked', '')
    with pytest.raises(HTTPException):
        isolation.checkpoint_folder(db, 'owner', 'run', 'implement')


@pytest.mark.parametrize('recovery', [False, True], ids=['approve-endpoint', 'resume-after-promotion'])
def test_http_uses_real_approval_reconciliation_and_queue(lab, monkeypatch, recovery):
    import central.main as main
    db, root, _, engine = lab
    monkeypatch.setattr(main, 'DB', db)
    monkeypatch.setattr(main, 'ENGINE', engine)
    monkeypatch.setitem(main.app.dependency_overrides, main.current_user, lambda: {'id': 'owner'})

    async def scenario():
        transport = httpx.ASGITransport(app=main.app, client=('127.0.0.1', 1234))
        async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                     headers={'x-central-request': '1'}) as client:
            plan = await client.post('/api/runs/run/steps/implement/isolated-review')
            assert plan.status_code == 200, plan.text
            token = plan.json()['confirmation']
            if recovery:
                isolation.approve(db, 'owner', 'run', 'implement', token)
                response = await client.post('/api/runs/run/resume')
            else:
                response = await client.post('/api/runs/run/steps/implement/isolated-approve',
                                             json={'confirmation': token})
            assert response.status_code == 200, response.text
            assert (root / 'app.py').read_text(encoding='utf-8') == 'value = 2\n'
            assert db.one("SELECT status FROM steps WHERE id='implement'")['status'] == 'completed'
            assert db.one("SELECT status FROM runs WHERE id='run'")['status'] == 'queued'
            assert counts(db) == (1, 1)
            replay = await client.post('/api/runs/run/steps/implement/isolated-approve',
                                       json={'confirmation': token})
            assert replay.status_code == 409
            assert counts(db) == (1, 1)

    asyncio.run(scenario())
