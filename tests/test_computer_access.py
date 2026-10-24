"""Local folder permissions and explicit one-time approval tests."""
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from central.database import Database, utcnow
from central.computer_access import (
    allowed_folder, decide_action, inspect, policy, request_action, set_policy,
)


@pytest.fixture
def access_db(tmp_path):
    db = Database(':memory:')
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('alice','alice@test.local','hash',utcnow()))
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('bob','bob@test.local','hash',utcnow()))
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_text("print('approved')", encoding='utf-8')
    (workspace / 'secret.key').write_text('SECRET', encoding='utf-8')
    (workspace / 'src').mkdir()
    (workspace / 'src' / 'view.jsx').write_text('export default 1', encoding='utf-8')
    yield db, workspace
    db.close()


def test_blocked_by_default(access_db):
    db, folder = access_db
    assert policy(db, 'alice') == {'mode': 'blocked', 'folder': ''}
    with pytest.raises(HTTPException) as exc:
        request_action(db, 'alice', 'list', '')
    assert exc.value.status_code == 403


def test_full_mode_is_scoped_to_a_specific_folder(access_db):
    db, folder = access_db
    configured = set_policy(db, 'alice', 'full', str(folder))
    assert configured == {'mode': 'full', 'folder': str(folder.resolve())}
    listed = request_action(db, 'alice', 'list', '')
    assert listed['status'] == 'completed'
    assert {item['name'] for item in listed['result']['items']} == {'src', 'app.py'}
    read = request_action(db, 'alice', 'read', 'src/view.jsx')
    assert read['result']['content'] == 'export default 1'
    with pytest.raises(HTTPException):
        request_action(db, 'alice', 'read', '../outside.txt')
    with pytest.raises(HTTPException):
        request_action(db, 'alice', 'read', '/etc/passwd')
    with pytest.raises(HTTPException):
        request_action(db, 'alice', 'read', 'secret.key')
    with pytest.raises(HTTPException):
        request_action(db, 'alice', 'write', 'app.py')
    assert policy(db, 'bob')['mode'] == 'blocked'


def test_each_ask_action_requires_one_time_expiring_approval(access_db):
    db, folder = access_db
    set_policy(db, 'alice', 'ask', str(folder))
    asked = request_action(db, 'alice', 'read', 'app.py')
    assert asked['status'] == 'approval_required'
    aid = asked['request_id']
    with pytest.raises(HTTPException) as exc:
        decide_action(db, 'bob', aid, True)
    assert exc.value.status_code == 404
    done = decide_action(db, 'alice', aid, True)
    assert done['status'] == 'completed'
    assert done['result']['content'] == "print('approved')"
    with pytest.raises(HTTPException):
        decide_action(db, 'alice', aid, True)
    second = request_action(db, 'alice', 'read', 'app.py')
    assert second['request_id'] != aid
    denied = decide_action(db, 'alice', second['request_id'], False)
    assert denied == {'status': 'denied'}
    with pytest.raises(HTTPException):
        decide_action(db, 'alice', second['request_id'], True)


def test_revoke_clears_pending_and_blocks_all_access(access_db):
    db, folder = access_db
    set_policy(db, 'alice', 'ask', str(folder))
    ticket = request_action(db, 'alice', 'list', '')
    set_policy(db, 'alice', 'blocked', '')
    assert policy(db, 'alice') == {'mode': 'blocked', 'folder': ''}
    with pytest.raises(HTTPException):
        decide_action(db, 'alice', ticket['request_id'], True)
    with pytest.raises(HTTPException):
        request_action(db, 'alice', 'list', '')


def test_expired_approval_denied(access_db):
    db, folder = access_db
    set_policy(db, 'alice', 'ask', str(folder))
    ticket = request_action(db, 'alice', 'list', '')
    db.execute('UPDATE computer_access_approvals SET expires_at=? WHERE id=?',
               ('2001-01-01T00:00:00+00:00', ticket['request_id']))
    with pytest.raises(HTTPException) as exc:
        decide_action(db, 'alice', ticket['request_id'], True)
    assert exc.value.status_code == 409


def test_folder_must_be_explicit_and_not_home_or_disk_root(access_db, tmp_path):
    db, workspace = access_db
    for unsafe in ['', str(Path.home()), str(Path('/')), 'relative/path']:
        with pytest.raises(HTTPException):
            set_policy(db, 'alice', 'full', unsafe)
    assert set_policy(db, 'alice', 'full', str(workspace))['folder'] == str(workspace)


def test_symlink_does_not_escape_authorized_folder(access_db, tmp_path):
    db, workspace = access_db
    outside = tmp_path / 'outside.txt'
    outside.write_text('OUTSIDE', encoding='utf-8')
    try:
        (workspace / 'shortcut.txt').symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip('Symbolic links require elevated Windows privileges in this environment.')
    set_policy(db, 'alice', 'full', str(workspace))
    with pytest.raises(HTTPException) as exc:
        request_action(db, 'alice', 'read', 'shortcut.txt')
    assert exc.value.status_code == 403


def test_read_size_and_text_format_are_limited(access_db):
    db, workspace = access_db
    (workspace / 'large.txt').write_bytes(b'A' * 65537)
    (workspace / 'bytes.bin').write_bytes(b'\x00\x10')
    set_policy(db, 'alice', 'full', str(workspace))
    with pytest.raises(HTTPException) as exc:
        request_action(db, 'alice', 'read', 'large.txt')
    assert exc.value.status_code == 413
    with pytest.raises(HTTPException) as exc:
        request_action(db, 'alice', 'read', 'bytes.bin')
    assert exc.value.status_code == 422


def test_api_requires_authentication_and_enforces_request_headers(tmp_path):
    from central.main import app
    workspace = tmp_path / 'my-project'
    workspace.mkdir()
    (workspace / 'notes.md').write_text('Hello', encoding='utf-8')
    with TestClient(app) as client:
        assert client.get('/api/computer-access').status_code == 401
        import uuid
        email = uuid.uuid4().hex + '@example.com'
        r = client.post('/api/register', json={'email': email, 'password': 'strongpassword123'},
                        headers={'X-Central-Request': '1'})
        assert r.status_code == 200, r.text
        assert client.get('/api/computer-access').json()['mode'] == 'blocked'
        assert client.put('/api/computer-access', json={'mode': 'full', 'folder': str(workspace)}).status_code == 403
        grant = client.put('/api/computer-access', json={'mode': 'ask', 'folder': str(workspace)},
                           headers={'X-Central-Request': '1'})
        assert grant.status_code == 200, grant.text
        request = client.post('/api/computer-access/action', json={'action': 'read', 'relative_path': 'notes.md'},
                              headers={'X-Central-Request': '1'})
        assert request.status_code == 200, request.text
        assert request.json()['status'] == 'approval_required'
        ticket = request.json()['request_id']
        approval = client.post('/api/computer-access/approvals/' + ticket + '/decision',
                               json={'approve': True}, headers={'X-Central-Request': '1'})
        assert approval.status_code == 200, approval.text
        assert approval.json()['result']['content'] == 'Hello'
