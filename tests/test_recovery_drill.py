import json
import tempfile

import pytest
from cryptography.fernet import Fernet, InvalidToken

from central.backups import create, verify
from central.cli import main as cli
from central.database import utcnow
from central.git_integrations import connect
from central.recovery_drill import rehearse
from central.security import Security
from test_backup_verification import encrypted_snapshot


def with_credentials(snapshot, tmp_path):
    db, directory, _, _ = snapshot
    security = Security(db, directory)
    db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,api_key_enc,created_at) '
               'VALUES(?,?,?,?,?,?,?,?)',
               ('p', 'person', 'Test', 'openai', 'https://example.test', 'test',
                security.encrypt('PRIVATE_PROVIDER_SECRET'), utcnow()))
    connect(db, security, 'person', 'github', 'owner/repository', 'PRIVATE_GIT_SECRET')
    output = tmp_path / 'with-credentials.enc'
    create(db, directory, output)
    return output


def test_drill_restores_both_credential_stores_and_cleans_up(
        encrypted_snapshot, tmp_path, monkeypatch):
    file = with_credentials(encrypted_snapshot, tmp_path)
    db, directory, _, backup_key = encrypted_snapshot
    source_before = file.read_bytes()
    database_before = (directory / 'central.sqlite3').read_bytes()
    scratch = tmp_path / 'drill # temporary'
    scratch.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(scratch))
    # An unrelated active deployment key must not affect restoration.
    monkeypatch.setenv('CENTRAL_SECRET_KEY', Fernet.generate_key().decode())
    result = rehearse(file)
    assert result['verified'] is True
    assert result['credential_counts'] == {'providers': 1, 'git_connections': 1}
    assert result['credential_check'] == 'passed'
    assert result['temporary_copy_removed'] is True
    assert result['production_ready'] is False
    assert not list(scratch.iterdir())
    assert file.read_bytes() == source_before
    assert (directory / 'central.sqlite3').read_bytes() == database_before
    output = json.dumps(result)
    for secret in ('PRIVATE_', backup_key, 'person@example.org', str(directory)):
        assert secret not in output
    assert db.one('SELECT COUNT(*) AS n FROM providers')['n'] == 1


def test_empty_credential_store_does_not_claim_a_decryption_test(encrypted_snapshot):
    result = rehearse(encrypted_snapshot[2])
    assert result['credential_check'] == 'no_credentials_present'
    assert result['credential_counts'] == {'providers': 0, 'git_connections': 0}


def test_valid_archive_with_wrong_embedded_key_fails_drill(
        encrypted_snapshot, tmp_path, monkeypatch):
    with_credentials(encrypted_snapshot, tmp_path)
    db, directory, _, _ = encrypted_snapshot
    monkeypatch.setenv('CENTRAL_SECRET_KEY', Fernet.generate_key().decode())
    wrong = tmp_path / 'wrong-embedded-key.enc'
    create(db, directory, wrong)
    assert verify(wrong)['verified'] is True  # Structural checks alone cannot catch this.
    scratch = tmp_path / 'temporary'
    scratch.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(scratch))
    with pytest.raises(InvalidToken):
        rehearse(wrong)
    assert not list(scratch.iterdir())


@pytest.mark.parametrize('change', [
    "UPDATE schema_migrations SET checksum='modified' WHERE version=1",
    "DELETE FROM schema_migrations WHERE version=8",
    "INSERT INTO schema_migrations VALUES(999,'future','unknown','2099-01-01')",
])
def test_drill_rejects_incompatible_ledger_without_migrating(
        encrypted_snapshot, tmp_path, change):
    db, directory, _, _ = encrypted_snapshot
    db.execute(change)
    backup = tmp_path / 'incompatible.enc'
    create(db, directory, backup)
    original = backup.read_bytes()
    with pytest.raises(ValueError, match='migration ledger'):
        rehearse(backup)
    assert backup.read_bytes() == original


def test_cli_drill_is_standalone_and_sanitizes_errors(
        encrypted_snapshot, tmp_path, monkeypatch, capsys):
    file = with_credentials(encrypted_snapshot, tmp_path)
    absent = tmp_path / 'not-an-active-database'
    assert cli(['--data-dir', str(absent), 'recovery-drill', str(file)]) == 0
    assert json.loads(capsys.readouterr().out)['credential_check'] == 'passed'
    assert not absent.exists()
    monkeypatch.setenv('CENTRAL_BACKUP_KEY', 'PRIVATE_INVALID_KEY')
    assert cli(['recovery-drill', str(file)]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)['verified'] is False
    assert 'PRIVATE_' not in output and str(file) not in output


def test_oversized_credential_fails_and_does_not_leak_value(
        encrypted_snapshot, tmp_path, monkeypatch):
    from central import recovery_drill
    file = with_credentials(encrypted_snapshot, tmp_path)
    monkeypatch.setattr(recovery_drill, 'MAX_TOKEN_BYTES', 10)
    with pytest.raises(ValueError, match='oversized'):
        rehearse(file)


def test_credential_limit_is_global_across_stores(encrypted_snapshot, tmp_path, monkeypatch):
    from central import recovery_drill
    file = with_credentials(encrypted_snapshot, tmp_path)
    monkeypatch.setattr(recovery_drill, 'MAX_CREDENTIALS', 1)
    with pytest.raises(ValueError, match='count exceeds'):
        rehearse(file)


@pytest.mark.parametrize('table,column', [
    ('providers', 'api_key_enc'), ('git_connections', 'token_enc'),
])
def test_corrupted_credential_in_either_store_fails_drill(
        encrypted_snapshot, tmp_path, table, column):
    with_credentials(encrypted_snapshot, tmp_path)
    db, directory, _, _ = encrypted_snapshot
    db.execute('UPDATE ' + table + ' SET ' + column + '=?', ('INVALID_PRIVATE_TOKEN',))
    file = tmp_path / 'corrupt-credential.enc'
    create(db, directory, file)
    with pytest.raises(InvalidToken):
        rehearse(file)
