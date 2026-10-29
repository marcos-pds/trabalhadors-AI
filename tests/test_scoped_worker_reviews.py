"""Owner-scoped worktree approval with real SQLite and Git on Windows/Linux."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi import HTTPException

from central.database import Database, utcnow
from central.computer_access import set_policy
from central.workspace_guard import bind_run
from central.scoped_worker_reviews import (
    register_worktree, list_worktrees, create_review, get_review, approve_review)
from central.task_contract import delivery_evidence

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='Git unavailable')


def git(folder, *args):
    result = subprocess.run(['git', *args], cwd=folder, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_WORKTREE_REVIEWS_ENABLED', '1')
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    root = tmp_path / 'project'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.email', 'test@example.invalid')
    git(root, 'config', 'user.name', 'Reviewer')
    (root / 'app.txt').write_bytes(b'base\n')
    git(root, 'add', 'app.txt')
    git(root, 'commit', '-qm', 'initial')
    db = Database(tmp_path / 'test.sqlite3')
    now = utcnow()
    for user in ('owner', 'outsider'):
        db.execute('INSERT INTO users VALUES(?,?,?,?)',
                   (user, user+'@example.invalid', 'hash', now))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                   (user,user,'Test',None,now,now))
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at,autonomous) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
               ('run1','owner','owner','Crie app','running','team','[]','[]',now,now,1))
    db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
               ('worker','owner','Worker','code','Do work',now))
    db.execute('INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
               ('step1','run1','worker','agent','Frontend','[]','completed',now,now))
    set_policy(db,'owner','full',str(root))
    bind_run(db,'owner','run1')
    db.execute("UPDATE runs SET status='completed' WHERE id='run1'")
    yield db,root
    db.close()


def test_approval_does_not_consume_wrong_token_and_invalidates_old_tests(setup):
    db,root=setup
    assert list_worktrees(db,'owner','run1')['worktrees'] == []
    prepared=register_worktree(db,'owner','run1','step1')
    worker=Path(prepared['path'])
    worker.joinpath('app.txt').write_bytes(b'worker edit\n')
    plan=create_review(db,'owner','run1','step1')
    assert plan['files'][0]['path']=='app.txt'
    assert 'token_hash' not in json.dumps(get_review(db,'owner','run1',plan['plan_id']))
    with pytest.raises(HTTPException) as wrong:
        approve_review(db,'owner','run1',plan['plan_id'],'wrong-token')
    assert wrong.value.status_code==403
    assert db.one('SELECT state FROM scoped_worktree_reviews')['state']=='pending'
    result=approve_review(db,'owner','run1',plan['plan_id'],plan['confirmation'])
    assert result['validation_required'] and root.joinpath('app.txt').read_bytes()==b'worker edit\n'
    assert worker.joinpath('app.txt').is_file()
    assert not delivery_evidence(db,'run1')['tests_passed']
    with pytest.raises(HTTPException):
        approve_review(db,'owner','run1',plan['plan_id'],plan['confirmation'])


def test_foreign_user_and_revoked_grant_cannot_promote(setup):
    db,root=setup
    with pytest.raises(HTTPException):
        register_worktree(db,'outsider','run1','step1')
    worker=Path(register_worktree(db,'owner','run1','step1')['path'])
    worker.joinpath('app.txt').write_bytes(b'new\n')
    plan=create_review(db,'owner','run1','step1')
    with pytest.raises(HTTPException):
        get_review(db,'outsider','run1',plan['plan_id'])
    set_policy(db,'owner','blocked','')
    with pytest.raises(HTTPException):
        approve_review(db,'owner','run1',plan['plan_id'],plan['confirmation'])
    assert root.joinpath('app.txt').read_bytes()==b'base\n'


def test_active_run_and_disabled_flag_never_create_a_checkout(setup,monkeypatch):
    db,root=setup
    db.execute("UPDATE runs SET status='running' WHERE id='run1'")
    with pytest.raises(HTTPException,match='Aguarde'):
        register_worktree(db,'owner','run1','step1')
    db.execute("UPDATE runs SET status='completed' WHERE id='run1'")
    monkeypatch.setenv('CENTRAL_WORKTREE_REVIEWS_ENABLED','0')
    assert list_worktrees(db,'owner','run1')['enabled'] is False
    with pytest.raises(HTTPException):
        register_worktree(db,'owner','run1','step1')
    assert not root.joinpath('.central-worker-worktrees').exists()


def test_dirty_main_refuses_approval_plan(setup):
    db,root=setup
    worker=Path(register_worktree(db,'owner','run1','step1')['path'])
    worker.joinpath('app.txt').write_bytes(b'worker edit\n')
    root.joinpath('app.txt').write_bytes(b'operator edit\n')
    with pytest.raises(HTTPException):
        create_review(db,'owner','run1','step1')
    assert root.joinpath('app.txt').read_bytes()==b'operator edit\n'
