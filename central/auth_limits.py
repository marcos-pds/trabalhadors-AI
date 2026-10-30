"""Persistent login lockout by salted/keyed identity fingerprint.

Never store the submitted password or raw e-mail in this rate-limit table.
"""
import hashlib
import time
from fastapi import HTTPException

WINDOW = 15 * 60
MAX_FAILURES = 6


def fingerprint(identity):
    return hashlib.sha256(
        ('central-login|' + identity.strip().casefold()).encode('utf-8')).hexdigest()


def ensure_allowed(db, email, now=None):
    now = time.time() if now is None else now
    found = db.one(
        'SELECT COUNT(*) AS n,MIN(attempted_at) AS oldest FROM login_failures '
        'WHERE identity_hash=? AND attempted_at>?',
        (fingerprint(email), now - WINDOW))
    if found and found['n'] >= MAX_FAILURES:
        remaining = max(1, int(found['oldest'] + WINDOW - now + 1))
        raise HTTPException(
            429, 'Muitas tentativas de login. Tente novamente mais tarde.',
            headers={'Retry-After': str(remaining)})


def failed(db, email, now=None):
    now = time.time() if now is None else now
    with db.lock, db.conn:
        db.conn.execute('DELETE FROM login_failures WHERE attempted_at<?',
                        (now - WINDOW,))
        db.conn.execute(
            'INSERT INTO login_failures(identity_hash,attempted_at) VALUES(?,?)',
            (fingerprint(email), now))


def succeeded(db, email):
    db.execute('DELETE FROM login_failures WHERE identity_hash=?',
               (fingerprint(email),))
