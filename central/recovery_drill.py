"""Offline recovery rehearsal using only a disposable restored copy.

Does not bootstrap the app, migrate schemas, start workers or call providers.
Only current migration ledgers and the two supported credential stores are
validated. This is not an offsite drill or proof of production readiness.
"""
import hashlib
from pathlib import Path
import sqlite3
import tempfile

from cryptography.fernet import Fernet

from .backups import restore
from .migrations import MIGRATIONS

CREDENTIAL_COLUMNS = (('providers', 'api_key_enc'), ('git_connections', 'token_enc'))
MAX_CREDENTIALS = 100000
MAX_TOKEN_BYTES = 1024 * 1024


def rehearse(source):
    """Restore, check ledger and decrypt credentials; discard temporary data.

    Uses the key INSIDE the backup, never CENTRAL_SECRET_KEY from the running
    installation. Plaintext is not returned, saved to disk, or sent anywhere.
    Errors propagate to callers; the operator CLI emits a sanitized failure.
    """
    with tempfile.TemporaryDirectory(prefix='central-recovery-drill-') as temp:
        destination = Path(temp) / 'restored'
        restore(source, destination)
        cipher = Fernet((destination / 'secret.key').read_bytes())
        connection = sqlite3.connect(
            (destination / 'central.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
        try:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('PRAGMA trusted_schema=OFF')
            expected = {version: hashlib.sha256('\n'.join(statements).encode()).hexdigest()
                        for version, _, statements in MIGRATIONS}
            installed = dict(connection.execute(
                'SELECT version,checksum FROM schema_migrations').fetchall())
            if installed != expected:
                raise ValueError('Recovery requires the current, unmodified migration ledger')
            counts = {}
            total = 0
            for table, column in CREDENTIAL_COLUMNS:
                counts[table] = 0
                # Identifiers come only from the fixed allowlist above.
                # Check lengths before fetching ciphertext into Python memory.
                query = ('SELECT CASE WHEN length(CAST("' + column + '" AS BLOB)) <= ? '
                         'THEN "' + column + '" ELSE NULL END FROM "' + table
                         + '" WHERE "' + column + '" IS NOT NULL AND "' + column + '" != ?')
                for (encrypted,) in connection.execute(query, (MAX_TOKEN_BYTES, '')):
                    total += 1
                    if total > MAX_CREDENTIALS:
                        raise ValueError('Recovery credential count exceeds limit')
                    if not isinstance(encrypted, str):
                        raise ValueError('Invalid or oversized encrypted credential')
                    plaintext = cipher.decrypt(encrypted.encode()).decode('utf-8')
                    del plaintext
                    counts[table] += 1
        finally:
            connection.close()
    # Return only after TemporaryDirectory cleanup succeeds.
    return {'verified': True, 'scope': 'local_disposable_restore',
            'schema_ledger': 'current', 'credential_counts': counts,
            'credential_check': 'passed' if total else 'no_credentials_present',
            'temporary_copy_removed': True, 'active_database_modified': False,
            'external_services_contacted': False, 'production_ready': False}
