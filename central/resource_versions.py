"""Static, owner-only resource replacement. No installation or activation.

SCHEMA is exported for migration 20; importing this module does not migrate.
All public results deliberately exclude payloads, ciphertext and freeform metadata.
"""
import base64
import hashlib
import hmac
import json
import re

from fastapi import HTTPException

from . import addon_packages as packages
from .addon_catalog import Catalog, transaction
from .database import uid, utcnow
from .ops import audit
from .organizations import require_org

MAX_ACCOUNT_BYTES = 64 * 1024 * 1024
MAX_VERSIONS = 20  # Current package plus at most 19 archived packages.
SCHEMA = (
    """CREATE TABLE resource_revisions(
        id TEXT PRIMARY KEY,
        resource_id TEXT NOT NULL REFERENCES ai_resources(id) ON DELETE CASCADE,
        owner_id TEXT NOT NULL REFERENCES users(id),
        kind TEXT NOT NULL CHECK(kind IN ('skill','vsix','mcp')),
        metadata_json TEXT NOT NULL, payload_enc TEXT NOT NULL,
        sha256 TEXT NOT NULL, origin TEXT NOT NULL,
        byte_size INTEGER NOT NULL CHECK(byte_size > 0),
        state TEXT NOT NULL CHECK(state IN ('inactive','active','revoked')),
        integrity_enc TEXT NOT NULL,
        operation TEXT NOT NULL CHECK(operation IN ('update','rollback')),
        created_at TEXT NOT NULL
    )""",
    'CREATE INDEX resource_revisions_owner ON resource_revisions(owner_id,resource_id,created_at)',
    "CREATE TRIGGER resource_revisions_no_update BEFORE UPDATE ON resource_revisions "
    "BEGIN SELECT RAISE(ABORT,'Resource history is immutable'); END",
    "CREATE TRIGGER resource_revisions_no_delete BEFORE DELETE ON resource_revisions "
    "WHEN EXISTS(SELECT 1 FROM ai_resources WHERE id=OLD.resource_id) "
    "BEGIN SELECT RAISE(ABORT,'Resource history is immutable'); END",
)


def _error(status=409):
    raise HTTPException(status, 'Recurso, confirmação ou histórico inválido; revise novamente.')


def _owner(db, user, rid):
    # Unlike Catalog's shared-admin writes, version replacement cannot take over
    # another owner's resource, even when the caller administers its organization.
    row = db.one('SELECT * FROM ai_resources WHERE id=? AND owner_id=?', (rid, user))
    if not row or not db.one('SELECT id FROM users WHERE id=?', (user,)):
        _error(404)
    if row['organization_id'] is not None:
        org = db.one('SELECT id FROM organizations WHERE id=? AND created_by=? AND is_personal=1',
                     (row['organization_id'], user))
        if not org:
            _error(403)
        if db.one('SELECT 1 FROM organization_members WHERE organization_id=? AND user_id<>? LIMIT 1',
                  (org['id'], user)):
            _error(403)
        require_org(db, org['id'], user, admin=True)
    return row


def _inspect(kind, filename, raw):
    try:
        packages.safe_name(filename)
        return packages.inspect(kind, filename, raw)
    except (ValueError, TypeError, AttributeError, RecursionError):
        _error(422)


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _confirm(actual, supplied):
    if (not isinstance(supplied, str) or not re.fullmatch('[0-9a-f]{64}', supplied)
            or not hmac.compare_digest(actual, supplied)):
        _error()


def _decode(db, security, row):
    try:
        filename, raw = Catalog(db, security).payload(row)
        _confirm(_digest(raw), row['sha256'])
        if len(raw) != row['byte_size']:
            _error()
        info = _inspect(row['kind'], filename, raw)
        metadata = json.loads(security.decrypt(row['metadata_json']))
        # Persisted inspection metadata must still describe the actual bytes.
        # Catalog may append provenance and installation facts; these are never
        # interpreted as grants or copied to the new package.
        expected = {k: v for k, v in info.items() if k != 'instructions'}
        if not isinstance(metadata, dict) or any(metadata.get(k) != v for k, v in expected.items()):
            _error()
        return filename, raw, info
    except HTTPException:
        raise
    except Exception:
        # Includes invalid Fernet authentication; never disclose decrypted text.
        _error()


def _identity(info):
    return tuple(info.get(key) for key in ('name', 'publisher', 'server_id'))


def _review(row, info):
    # No descriptions, instructions, source URLs, endpoints, schemas or credentials.
    return dict(kind=row['kind'], sha256=row['sha256'], byte_size=row['byte_size'],
                state=row['state'], version=info['version'],
                file_count=info.get('file_count', 0), tool_count=len(info.get('tools', [])),
                execution_enabled=False)


def _quota(db, user, rid, new_size):
    count = db.one('SELECT COUNT(*) n FROM resource_revisions WHERE resource_id=?', (rid,))['n']
    total = db.one('SELECT COALESCE(SUM(byte_size),0) n FROM ai_resources WHERE owner_id=?', (user,))['n']
    total += db.one('SELECT COALESCE(SUM(byte_size),0) n FROM resource_revisions WHERE owner_id=?', (user,))['n']
    # Old current bytes remain as an archive, so the net increment is new_size.
    if count + 1 >= MAX_VERSIONS or total + new_size > MAX_ACCOUNT_BYTES:
        raise HTTPException(409, 'Limite atingido: 20 versões por recurso / 64 MiB por conta incluindo histórico.')


def preview_update(db, security, user, resource_id, filename, raw):
    """Read-only static review. Digests must be confirmed again on apply."""
    with db.lock:
        row = _owner(db, user, resource_id)
        _, _, old_info = _decode(db, security, row)
        new_info = _inspect(row['kind'], filename, raw)
        if _identity(old_info) != _identity(new_info):
            _error(422)
        _quota(db, user, resource_id, len(raw))
        candidate = dict(row, sha256=_digest(raw), byte_size=len(raw), state='inactive')
        return dict(resource_id=resource_id, current=_review(row, old_info),
                    new=_review(candidate, new_info), bindings_will_be_removed=True,
                    activation_required=True)


_SEALED_FIELDS = ('resource_id', 'owner_id', 'kind', 'metadata_json', 'payload_enc',
                  'sha256', 'origin', 'byte_size', 'state', 'operation', 'created_at', 'id')


def _seal(row):
    return json.dumps({key: row[key] for key in _SEALED_FIELDS}, sort_keys=True)


def _replace(db, security, user, row, filename, raw, info, origin, operation):
    _quota(db, user, row['id'], len(raw))
    revision = {key: row[key] for key in
                ('owner_id', 'kind', 'metadata_json', 'payload_enc', 'sha256', 'origin', 'byte_size', 'state')}
    revision.update(id=uid(), resource_id=row['id'], operation=operation, created_at=utcnow())
    revision['integrity_enc'] = security.encrypt(_seal(revision))
    columns = tuple(revision)
    db.execute('INSERT INTO resource_revisions (' + ','.join(columns) + ') VALUES (' +
               ','.join('?' for _ in columns) + ')', tuple(revision[key] for key in columns))
    metadata = {key: value for key, value in info.items() if key != 'instructions'}
    payload = json.dumps(dict(filename=filename, data=base64.b64encode(raw).decode('ascii')))
    db.execute("UPDATE ai_resources SET metadata_json=?,payload_enc=?,sha256=?,origin=?,"
               "byte_size=?,state='inactive' WHERE id=? AND owner_id=?",
               (security.encrypt(json.dumps(metadata)), security.encrypt(payload), _digest(raw),
                origin, len(raw), row['id'], user))
    db.execute('DELETE FROM skill_bindings WHERE resource_id=?', (row['id'],))
    audit(db, user, 'resource_version_' + operation, 'ai_resource', row['id'])
    result = _review(dict(row, sha256=_digest(raw), byte_size=len(raw), state='inactive'), info)
    return dict(resource_id=row['id'], archived_revision_id=revision['id'], current=result,
                bindings_removed=True, activation_required=True)


def apply_update(db, security, user, rid, filename, raw,
                 expected_current_sha256, confirmed_new_sha256):
    """CAS replacement under BEGIN IMMEDIATE; never installs or activates."""
    with transaction(db):
        row = _owner(db, user, rid)
        _confirm(row['sha256'], expected_current_sha256)
        _, _, old_info = _decode(db, security, row)
        info = _inspect(row['kind'], filename, raw)
        _confirm(_digest(raw), confirmed_new_sha256)
        if _identity(old_info) != _identity(info):
            _error(422)
        if row['sha256'] == confirmed_new_sha256:
            _error()
        return _replace(db, security, user, row, filename, raw, info, 'local_upload_update', 'update')


def _revision(db, security, user, rid, revision_id):
    revision = db.one('SELECT * FROM resource_revisions WHERE id=? AND resource_id=? AND owner_id=?',
                      (revision_id, rid, user))
    if not revision:
        _error(404)
    try:
        if not hmac.compare_digest(security.decrypt(revision['integrity_enc']).encode(), _seal(revision).encode()):
            _error()
    except HTTPException:
        raise
    except Exception:
        _error()
    return revision


def list_versions(db, security, user, resource_id):
    """List archived static reviews only, never encrypted or decrypted package data."""
    with db.lock:
        _owner(db, user, resource_id)
        result = []
        for item in db.all('SELECT id FROM resource_revisions WHERE resource_id=? ORDER BY created_at,id', (resource_id,)):
            revision = _revision(db, security, user, resource_id, item['id'])
            _, _, info = _decode(db, security, revision)
            result.append(dict(_review(revision, info), revision_id=revision['id'],
                               created_at=revision['created_at'], operation=revision['operation']))
        return result


def rollback(db, security, user, rid, revision_id, expected_current_sha256, confirmed_target_sha256):
    """Restore an authenticated archive as inactive; archive current as compensation."""
    with transaction(db):
        row = _owner(db, user, rid)
        _confirm(row['sha256'], expected_current_sha256)
        _, _, current_info = _decode(db, security, row)
        target = _revision(db, security, user, rid, revision_id)
        _confirm(target['sha256'], confirmed_target_sha256)
        filename, raw, info = _decode(db, security, target)
        if target['kind'] != row['kind'] or _identity(info) != _identity(current_info):
            _error()
        if target['sha256'] == row['sha256']:
            _error()
        return _replace(db, security, user, row, filename, raw, info, target['origin'], 'rollback')
