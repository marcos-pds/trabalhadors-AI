"""Single-use invitations to an existing, explicitly selected user account."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from .database import uid, utcnow
from .organizations import require_org

SCHEMA = '''CREATE TABLE IF NOT EXISTS organization_invitations (
 id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
 invited_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 invited_by TEXT NOT NULL REFERENCES users(id), role TEXT NOT NULL CHECK(role IN ('operator','analyst')),
 token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','accepted','revoked')),
 created_at TEXT NOT NULL
)'''


def create(db, actor, org, invited_user, role='analyst'):
    require_org(db, org, actor, admin=True)
    if role not in ('operator', 'analyst'):
        raise HTTPException(422, 'Convites permitem somente operador ou analista.')
    if not db.one('SELECT id FROM users WHERE id=?', (invited_user,)):
        raise HTTPException(404, 'Conta convidada não encontrada.')
    if db.one('SELECT 1 FROM organization_members WHERE organization_id=? AND user_id=?',
              (org, invited_user)):
        raise HTTPException(409, 'Esta conta já participa da organização.')
    token, identifier = secrets.token_urlsafe(32), uid()
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    db.execute('INSERT INTO organization_invitations '
               '(id,organization_id,invited_user_id,invited_by,role,token_hash,expires_at,created_at) '
               'VALUES(?,?,?,?,?,?,?,?)',
               (identifier, org, invited_user, actor, role,
                hashlib.sha256(token.encode()).hexdigest(), expires, utcnow()))
    return {'id': identifier, 'token': token, 'expires_at': expires,
            'invited_user_id': invited_user, 'role': role}


def accept(db, user_id, token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db.lock:
        db.conn.execute('BEGIN IMMEDIATE')
        try:
            row = db.one('SELECT * FROM organization_invitations '
                         "WHERE token_hash=? AND invited_user_id=? AND state='pending' AND expires_at>?",
                         (digest, user_id, utcnow()))
            if not row:
                raise HTTPException(404, 'Convite inválido, expirado ou indisponível.')
            require_org(db, row['organization_id'], row['invited_by'], admin=True)
            # An invitation never changes a member's current permissions.
            db.conn.execute('INSERT OR IGNORE INTO organization_members VALUES(?,?,?,?)',
                            (row['organization_id'], user_id, row['role'], utcnow()))
            db.conn.execute("UPDATE organization_invitations SET state='accepted' WHERE id=?",
                            (row['id'],))
            db.conn.execute('COMMIT')
        except BaseException:
            db.conn.execute('ROLLBACK')
            raise
    return {'organization_id': row['organization_id'], 'accepted': True}


def revoke(db, actor, org, invitation_id):
    require_org(db, org, actor, admin=True)
    changed = db.execute("UPDATE organization_invitations SET state='revoked' "
                         "WHERE id=? AND organization_id=? AND state='pending'",
                         (invitation_id, org))
    return {'revoked': bool(changed)}
