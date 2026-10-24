"""Encrypted recovery point checks must not restore over a live database."""
import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from central.backups import create, verify
from central.cli import main as cli
from central.database import Database, utcnow
from central.release_checks import report
from central.security import Security


@pytest.fixture
def encrypted_snapshot(tmp_path, monkeypatch):
    directory = tmp_path / 'data'
    directory.mkdir()
    db = Database(directory / 'central.sqlite3')
    Security(db, directory)
    db.execute('INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)',
               ('person','person@example.org','not-real-hash',utcnow()))
    key = Fernet.generate_key().decode()
    monkeypatch.setenv('CENTRAL_BACKUP_KEY',key)
    output = tmp_path / 'snapshot.enc'
    create(db,directory,output)
    yield db,directory,output,key
    db.close()


def test_verify_valid_backup_never_restores_or_exposes_secrets(encrypted_snapshot,tmp_path):
    db, data, file, key = encrypted_snapshot
    before = (data / 'central.sqlite3').read_bytes()
    folder_listing = {x.name for x in tmp_path.iterdir()}
    result=verify(file)
    assert result['verified'] is True
    assert result['encrypted'] is True
    assert result['restored'] is False
    assert result['integrity'] == 'ok'
    assert result['database_bytes'] > 0
    assert key not in json.dumps(result)
    assert 'person@example.org' not in json.dumps(result)
    assert {x.name for x in tmp_path.iterdir()} == folder_listing
    assert (data / 'central.sqlite3').read_bytes() == before
    assert db.one('SELECT email FROM users WHERE id=?',('person',))['email'] == 'person@example.org'


def test_cli_verify_backup_does_not_require_live_database(encrypted_snapshot,
                                                          tmp_path,capsys):
    db, data, file, key = encrypted_snapshot
    # The requested data directory does not exist: verification is standalone.
    assert cli(['--data-dir',str(tmp_path/'nonexistent'),
                'verify-backup',str(file)]) == 0
    info=json.loads(capsys.readouterr().out)
    assert info['verified'] is True
    assert info['restored'] is False
    assert not (tmp_path/'nonexistent').exists()


def test_release_check_uses_real_backup_verification_not_ready_flag(
        encrypted_snapshot,monkeypatch,capsys):
    db, data, file, key = encrypted_snapshot
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE','local')
    result=report(db,backup_file=str(file))
    checks={x['name']:x for x in result['checks']}
    assert checks['encrypted_backup_recovery_point']['status']=='passed'
    assert result['production_ready'] is False
    assert checks['independent_security_review']['status']=='requires_external_validation'
    code=cli(['--data-dir',str(data),'release-check','--backup-file',str(file)])
    assert code == 2
    output=json.loads(capsys.readouterr().out)
    assert any(row['name']=='encrypted_backup_recovery_point' and row['status']=='passed'
               for row in output['checks'])


def test_bad_key_and_corrupt_backups_are_not_reported_as_approved(
        encrypted_snapshot,monkeypatch):
    db, data, file, correct_key = encrypted_snapshot
    monkeypatch.setenv('CENTRAL_BACKUP_KEY',Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        verify(file)
    failed=report(db,backup_file=str(file))
    assert not failed['production_ready']
    entry=next(c for c in failed['checks']
               if c['name']=='encrypted_backup_recovery_point')
    assert entry['status']=='failed'
    assert correct_key not in json.dumps(failed)
    monkeypatch.setenv('CENTRAL_BACKUP_KEY',correct_key)
    content=bytearray(file.read_bytes())
    content[-8] ^= 1
    tampered=file.with_name('corrupt.enc')
    tampered.write_bytes(content)
    with pytest.raises(InvalidToken):
        verify(tampered)
    assert report(db,backup_file=str(tampered))['production_ready'] is False


def test_absent_backup_is_not_silently_accepted(tmp_path,monkeypatch):
    monkeypatch.setenv('CENTRAL_BACKUP_KEY',Fernet.generate_key().decode())
    with pytest.raises(ValueError,match='not a file'):
        verify(tmp_path/'missing.enc')
    db=Database(':memory:')
    try:
        checks=report(db)
        status=next(c['status'] for c in checks['checks']
                    if c['name']=='encrypted_backup_recovery_point')
        assert status=='not_checked'
    finally:
        db.close()
