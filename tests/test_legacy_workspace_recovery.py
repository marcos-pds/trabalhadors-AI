"""Legacy tenant backfill must preserve the existing folder grant and runner."""
import pytest
from fastapi import HTTPException

from central.computer_access import set_policy
from central.database import Database, utcnow
from central.workspace_guard import enforce_run_scope


def legacy(tmp_path, shared=False):
    path = tmp_path / 'legacy.sqlite3'
    folder = tmp_path / 'project'
    folder.mkdir()
    db = Database(path)
    now = utcnow()
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('u', 'u@example.test', 'hash', now))
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', ('c', 'u', 'Legacy', None, now, now))
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at,autonomous) '
               'VALUES(?,?,?,?,?,?,?,?,?,?,?)', ('r', 'u', 'c', 'Continue', 'running', 'manual', '[]', '[]', now, now, 1))
    db.execute('INSERT INTO run_workspace_bindings(run_id,user_id,organization_id,folder,initial_mode,command_runner,created_at) '
               "VALUES('r','u',NULL,?,'full','host',?)", (str(folder), now))
    set_policy(db, 'u', 'full', str(folder))
    if shared:
        db.execute('INSERT INTO organizations(id,name,created_by,is_personal,created_at) VALUES(?,?,?,?,?)',
                   ('shared', 'Team', 'u', 0, now))
        db.execute('INSERT INTO organization_members VALUES(?,?,?,?)', ('shared', 'u', 'admin', now))
        db.execute("INSERT INTO organization_runs VALUES('r','shared')")
    # Emulate a pre-17 database; only the test database's migration marker changes.
    db.execute('DELETE FROM schema_migrations WHERE version=17')
    db.close()
    return path, folder


def test_legacy_personal_binding_recovers_without_changing_grant(tmp_path):
    path, folder = legacy(tmp_path)
    db = Database(path)
    try:
        binding = db.one('SELECT * FROM run_workspace_bindings')
        assert binding['organization_id'] == db.one('SELECT organization_id FROM organization_runs')['organization_id']
        assert binding['folder'] == str(folder) and binding['initial_mode'] == 'full'
        assert binding['command_runner'] == 'host'
        assert enforce_run_scope(db, 'u', 'r') == str(folder)
        assert db.one('SELECT count(*) n FROM workspace_tenant_backfills')['n'] == 1
    finally:
        db.close()
    reopened = Database(path)
    assert reopened.one('SELECT count(*) n FROM workspace_tenant_backfills')['n'] == 1
    reopened.close()


def test_shared_tenant_is_not_silently_adopted(tmp_path):
    path, _ = legacy(tmp_path, shared=True)
    db = Database(path)
    try:
        assert db.one('SELECT organization_id FROM run_workspace_bindings')['organization_id'] is None
        assert db.one('SELECT count(*) n FROM workspace_tenant_backfills')['n'] == 0
        with pytest.raises(HTTPException):
            enforce_run_scope(db, 'u', 'r')
    finally:
        db.close()
