"""Operator-only encrypted SQLite snapshots and non-overwriting restore.

Backups include the local encryption key so provider credentials are recoverable.
The distinct backup encryption key must be supplied by the operator externally.
"""
import base64
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from cryptography.fernet import Fernet

MAX_ARCHIVE = 256 * 1024 * 1024


def _cipher():
    value = os.environ.get('CENTRAL_BACKUP_KEY', '')
    if not value:
        raise ValueError('Set CENTRAL_BACKUP_KEY to an independent Fernet key')
    return Fernet(value.encode())


def create(db, data_dir, destination):
    cipher = _cipher()
    destination = Path(destination)
    # No replacement of a previous recovery point, even under concurrent runs.
    with tempfile.TemporaryDirectory(prefix='central-snapshot-', dir=data_dir) as temp:
        snapshot = Path(temp) / 'central.sqlite3'
        connection = sqlite3.connect(snapshot)
        try:
            with db.lock:
                db.conn.backup(connection)
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Snapshot integrity check failed')
        finally:
            connection.close()
        if snapshot.stat().st_size > MAX_ARCHIVE:
            raise ValueError('Snapshot exceeds backup size limit')
        secret = os.environ.get('CENTRAL_SECRET_KEY')
        key = secret.encode() if secret else (Path(data_dir) / 'secret.key').read_bytes()
        Fernet(key)  # verify the recovery key before writing a backup
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w', zipfile.ZIP_STORED) as archive:
            archive.write(snapshot, 'central.sqlite3')
            archive.writestr('secret.key', key)
            archive.writestr('manifest.json', json.dumps({'format': 1, 'engine': 'sqlite'}))
        encrypted = cipher.encrypt(content.getvalue())
        with destination.open('xb') as output:
            output.write(encrypted)
        os.chmod(destination, 0o600)
    return {'file': destination.name, 'encrypted': True}




def verify(source):
    """Verify an encrypted recovery point without restoring it anywhere permanent.

    Does not expose the embedded credential key or modify the active database.
    This is not a substitute for a real offsite restoration drill.
    """
    source = Path(source)
    if not source.is_file():
        raise ValueError('Backup source is not a file')
    if source.stat().st_size > MAX_ARCHIVE * 2:
        raise ValueError('Encrypted backup exceeds size limit')
    raw = _cipher().decrypt(source.read_bytes())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if set(archive.namelist()) != {'manifest.json', 'central.sqlite3', 'secret.key'}:
            raise ValueError('Unexpected backup members')
        if len(archive.infolist()) != 3 or any(
                entry.file_size > MAX_ARCHIVE for entry in archive.infolist()):
            raise ValueError('Archive member count or size is invalid')
        if json.loads(archive.read('manifest.json')) != {'format': 1, 'engine': 'sqlite'}:
            raise ValueError('Unsupported backup format')
        Fernet(archive.read('secret.key'))
        with tempfile.TemporaryDirectory(prefix='central-backup-verify-') as directory:
            stage = Path(directory) / 'verification.sqlite3'
            # Extract no archive paths: only write the known database member.
            with stage.open('xb') as output:
                with archive.open('central.sqlite3') as data:
                    while True:
                        chunk = data.read(64 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        if output.tell() > MAX_ARCHIVE:
                            raise ValueError('Backup database exceeds size limit')
            db = sqlite3.connect('file:' + stage.as_posix() + '?mode=ro', uri=True)
            try:
                integrity = db.execute('PRAGMA integrity_check').fetchone()
                if not integrity or integrity[0] != 'ok':
                    raise ValueError('Backup SQLite integrity check failed')
            finally:
                db.close()
            return {'verified': True, 'encrypted': True,
                    'engine': 'sqlite', 'database_bytes': stage.stat().st_size,
                    'integrity': 'ok', 'restored': False}


def restore(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Restore destination must not exist')
    if source.stat().st_size > MAX_ARCHIVE * 2:
        raise ValueError('Encrypted backup exceeds size limit')
    raw = _cipher().decrypt(source.read_bytes())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if set(archive.namelist()) != {'manifest.json', 'central.sqlite3', 'secret.key'}:
            raise ValueError('Unexpected backup members')
        if any(entry.file_size > MAX_ARCHIVE for entry in archive.infolist()):
            raise ValueError('Archive member exceeds size limit')
        if json.loads(archive.read('manifest.json')) != {'format': 1, 'engine': 'sqlite'}:
            raise ValueError('Unsupported backup format')
        key = archive.read('secret.key')
        Fernet(key)
        # Stage beside the destination, verify SQLite, then rename atomically.
        with tempfile.TemporaryDirectory(prefix='central-restore-', dir=destination.parent) as temp:
            stage = Path(temp) / 'restore'
            stage.mkdir()
            (stage / 'central.sqlite3').write_bytes(archive.read('central.sqlite3'))
            (stage / 'secret.key').write_bytes(key)
            os.chmod(stage / 'secret.key', 0o600)
            connection = sqlite3.connect(stage / 'central.sqlite3')
            try:
                if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Restored database integrity check failed')
            finally:
                connection.close()
            # Reserve the destination so POSIX rename cannot replace an empty folder.
            destination.mkdir(exist_ok=False)
            try:
                for name in ('central.sqlite3', 'secret.key'):
                    (stage / name).rename(destination / name)
            except BaseException:
                # Retain any partial result for inspection; never destroy recovery data.
                raise
    return {'restored': True, 'destination': str(destination)}
