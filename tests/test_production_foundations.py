import json
import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from central.database import Database, utcnow
from central.security import Security
from central import backups, invitations
from central.migrations import migrate
from central.runtime_config import validate_runtime, registration_allowed
from central.organizations import create_organization
from central.exports import run_report, markdown
from test_memory import user, project, convo


def test_encrypted_backup_restore_integrity_and_no_overwrite(tmp_path, monkeypatch):
    folder = tmp_path / 'original'; folder.mkdir()
    db = Database(folder / 'central.sqlite3')
    security = Security(db, folder)
    user(db, 'one')
    monkeypatch.setenv('CENTRAL_BACKUP_KEY', Fernet.generate_key().decode())
    destination = tmp_path / 'snapshot.enc'
    backups.create(db, folder, destination)
    assert b'one@example.com' not in destination.read_bytes()
    with pytest.raises(FileExistsError):
        backups.create(db, folder, destination)
    restored = tmp_path / 'recovered'
    backups.restore(destination, restored)
    recovered = Database(restored / 'central.sqlite3')
    assert recovered.one('SELECT email FROM users')['email'] == 'one@example.com'
    assert (restored / 'secret.key').read_bytes() == (folder / 'secret.key').read_bytes()
    with pytest.raises(ValueError):
        backups.restore(destination, restored)
    monkeypatch.setenv('CENTRAL_BACKUP_KEY', Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        backups.restore(destination, tmp_path / 'wrong-key')
    assert not (tmp_path / 'wrong-key').exists()
    recovered.close(); db.close()


def test_migration_ledger_is_idempotent_and_rejects_tampering():
    db = Database(':memory:')
    migrate(db)
    assert len(db.all('SELECT * FROM schema_migrations')) == 4
    db.execute("UPDATE schema_migrations SET checksum='altered'")
    with pytest.raises(RuntimeError, match='checksum'):
        migrate(db)
    db.close()


def test_invitation_bound_to_account_expiry_and_single_use():
    db = Database(':memory:')
    for name in ('admin', 'invited', 'outsider'):
        user(db, name)
    org = create_organization(db, 'admin', 'Empresa')
    invitation = invitations.create(db, 'admin', org, 'invited', 'operator')
    assert invitation['token'] not in json.dumps(db.all('SELECT * FROM organization_invitations'))
    with pytest.raises(HTTPException):
        invitations.accept(db, 'outsider', invitation['token'])
    invitations.accept(db, 'invited', invitation['token'])
    with pytest.raises(HTTPException):
        invitations.accept(db, 'invited', invitation['token'])
    assert db.one('SELECT role FROM organization_members WHERE user_id=?', ('invited',))['role'] == 'operator'
    expired = invitations.create(db, 'admin', org, 'outsider')
    db.execute("UPDATE organization_invitations SET expires_at='2000-01-01' WHERE id=?", (expired['id'],))
    with pytest.raises(HTTPException):
        invitations.accept(db, 'outsider', expired['token'])
    db.close()


def test_server_mode_rejects_incomplete_configuration(monkeypatch):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'server')
    monkeypatch.delenv('CENTRAL_PUBLIC_ORIGIN', raising=False)
    assert not registration_allowed()
    with pytest.raises(ValueError, match='HTTPS'):
        validate_runtime()
    monkeypatch.setenv('CENTRAL_PUBLIC_ORIGIN', 'https://central.example.com')
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'host')
    with pytest.raises(ValueError, match='Docker'):
        validate_runtime()
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'docker')
    monkeypatch.setenv('CENTRAL_SECRET_KEY', Fernet.generate_key().decode())
    assert validate_runtime() == 'server'


def test_run_export_requires_owner_and_omits_workspace_and_credentials():
    db = Database(':memory:')
    user(db, 'one'); user(db, 'two'); convo(db, 'one', 'chat')
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,output,created_at,updated_at) '
               'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
               ('run', 'one', 'chat', 'Solicitação', 'completed', 'auto', '[]', '[]', 'Resultado', utcnow(), utcnow()))
    report = run_report(db, 'one', 'run')
    assert 'Resultado' in markdown(report)
    assert 'workspace_binding' not in report and 'api_key_enc' not in report
    with pytest.raises(HTTPException):
        run_report(db, 'two', 'run')
    db.close()
