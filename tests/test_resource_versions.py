"""Static lifecycle checks with real SQLite and authenticated Catalog encryption."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import sqlite3
import zipfile

import pytest
from fastapi import HTTPException

from central import resource_versions as versions
from central.addon_catalog import Catalog
from central.database import Database, utcnow
from central.organizations import ensure_personal
from central.security import Security


def skill(version='1.0.0', name='review-code'):
    return f'---\nname: {name}\ndescription: Private description\nversion: {version}\n---\nPRIVATE_BODY_{version}'.encode()


def manifest(version='1.0.0', name='example'):
    return json.dumps(dict(name=name, version=version, transport='stdio',
                           tools=[], permissions=['workspace.read'])).encode()


def vsix(version='1.0.0'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('extension/package.json', json.dumps(dict(
            name='example', publisher='pub', version=version, engines={'vscode': '^1.80.0'},
            scripts={'postinstall': 'DO_NOT_EXECUTE'})))
        archive.writestr('extension/main.js', 'throw new Error("DO_NOT_EXECUTE")')
    return stream.getvalue()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / 'versions.sqlite')
    if not db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='resource_revisions'"):
        for sql in versions.SCHEMA:
            db.execute(sql)
    for user in ('alice', 'bob'):
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, user + '@example.test', 'unused', utcnow()))
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) VALUES(?,?,?,?,?,?)',
                   (user, user, 'worker', 'code', 'test', utcnow()))
    security = Security(db, tmp_path)
    catalog = Catalog(db, security)
    yield db, security, catalog
    db.close()


def imported(env, kind='skill', raw=None):
    db, security, catalog = env
    filename = {'skill': 'SKILL.md', 'vsix': 'example.vsix', 'mcp': 'server.json'}[kind]
    raw = raw if raw is not None else {'skill': skill, 'vsix': vsix, 'mcp': manifest}[kind]()
    preview = catalog.preview('alice', kind, filename, raw)
    return catalog.confirm('alice', preview['preview_id'], preview['confirmation']), filename, raw


def update(env, row, filename, raw):
    return versions.apply_update(env[0], env[1], 'alice', row['id'], filename, raw, row['sha256'], sha(raw))


@pytest.mark.parametrize('kind,factory', [('skill', skill), ('vsix', vsix), ('mcp', manifest)])
def test_roundtrip_preview_update_rollback_inactive(env, kind, factory):
    db, security, catalog = env
    row, filename, original = imported(env, kind)
    db.execute("UPDATE ai_resources SET state='active' WHERE id=?", (row['id'],))
    db.execute('INSERT INTO skill_bindings VALUES(?,?,?,?)', (row['id'], 'alice', 'agent', 'alice'))
    old = db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],))
    raw = factory('2.0.0')
    before = db.conn.total_changes
    preview = versions.preview_update(db, security, 'alice', row['id'], filename, raw)
    assert db.conn.total_changes == before
    assert preview['current']['sha256'] == sha(original)
    assert preview['new']['sha256'] == sha(raw)
    assert preview['new']['state'] == 'inactive'
    assert 'PRIVATE_BODY' not in json.dumps(preview)
    changed = update(env, row, filename, raw)
    assert changed['current']['state'] == 'inactive'
    assert db.all('SELECT * FROM skill_bindings') == []
    archive = db.one('SELECT * FROM resource_revisions WHERE id=?', (changed['archived_revision_id'],))
    for field in ('payload_enc', 'metadata_json', 'sha256', 'origin', 'byte_size', 'state'):
        assert archive[field] == old[field]
    assert 'PRIVATE_BODY' not in archive['payload_enc'] + archive['metadata_json']
    # Simulate separate explicit reactivation/binding before rollback.
    db.execute("UPDATE ai_resources SET state='active' WHERE id=?", (row['id'],))
    db.execute('INSERT INTO skill_bindings VALUES(?,?,?,?)', (row['id'], 'alice', 'agent', 'alice'))
    restored = versions.rollback(db, security, 'alice', row['id'], archive['id'], sha(raw), sha(original))
    current = db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],))
    assert catalog.payload(current) == (filename, original)
    assert current['state'] == 'inactive' and restored['activation_required']
    assert current['origin'] == old['origin']
    assert db.all('SELECT * FROM skill_bindings') == []
    history = versions.list_versions(db, security, 'alice', row['id'])
    assert len(history) == 2
    assert {r['sha256'] for r in history} == {sha(original), sha(raw)}
    assert {r['operation'] for r in history} == {'update', 'rollback'}
    for public in [preview, changed, restored, history]:
        serialized = json.dumps(public)
        assert all(field not in serialized for field in ('payload_enc', 'metadata_json', 'integrity_enc', 'PRIVATE_BODY'))
    actions = db.all("SELECT action FROM ops_audit WHERE action LIKE 'resource_version_%'")
    assert [r['action'] for r in actions] == ['resource_version_update', 'resource_version_rollback']


@pytest.mark.parametrize('method', ['preview', 'apply', 'list', 'rollback'])
def test_foreign_identity_denied(env, method):
    db, security, _ = env
    row, filename, _ = imported(env)
    changed = update(env, row, filename, skill('2.0.0'))
    before = db.conn.total_changes
    with pytest.raises(HTTPException) as error:
        if method == 'preview':
            versions.preview_update(db, security, 'bob', row['id'], filename, skill('3.0.0'))
        elif method == 'apply':
            versions.apply_update(db, security, 'bob', row['id'], filename, skill('3.0.0'), sha(skill('2.0.0')), sha(skill('3.0.0')))
        elif method == 'list':
            versions.list_versions(db, security, 'bob', row['id'])
        else:
            versions.rollback(db, security, 'bob', row['id'], changed['archived_revision_id'], sha(skill('2.0.0')), row['sha256'])
    assert error.value.status_code == 404
    assert db.conn.total_changes == before


def test_local_personal_org_allowed_shared_scope_denied(env):
    db, security, catalog = env
    row, filename, _ = imported(env)
    org = ensure_personal(db, 'alice')
    catalog.share('alice', row['id'], org, row['sha256'])
    update(env, row, filename, skill('2.0.0'))
    db.execute('UPDATE organizations SET is_personal=0 WHERE id=?', (org,))
    with pytest.raises(HTTPException) as error:
        versions.preview_update(db, security, 'alice', row['id'], filename, skill('3.0.0'))
    assert error.value.status_code == 403
    db.execute('INSERT INTO organization_members VALUES(?,?,?,?)', (org, 'bob', 'admin', utcnow()))
    with pytest.raises(HTTPException) as error:
        versions.apply_update(db, security, 'bob', row['id'], filename, skill('3.0.0'), sha(skill('2.0.0')), sha(skill('3.0.0')))
    assert error.value.status_code == 404


@pytest.mark.parametrize('failure', ['stale', 'confirmation', 'identity', 'invalid', 'tampered_payload', 'tampered_metadata'])
def test_rejected_update_leaves_package_bindings_history_unchanged(env, failure):
    db, security, _ = env
    row, filename, _ = imported(env)
    raw = skill('2.0.0')
    expected, confirmed = row['sha256'], sha(raw)
    if failure == 'stale':
        expected = '0' * 64
    elif failure == 'confirmation':
        confirmed = '0' * 64
    elif failure == 'identity':
        raw = skill('2.0.0', 'different-identity')
        confirmed = sha(raw)
    elif failure == 'invalid':
        raw = b'invalid'
        confirmed = sha(raw)
    elif failure == 'tampered_payload':
        db.execute("UPDATE ai_resources SET payload_enc='invalid' WHERE id=?", (row['id'],))
    else:
        db.execute('UPDATE ai_resources SET metadata_json=? WHERE id=?', (security.encrypt('{}'), row['id']))
    db.execute('INSERT INTO skill_bindings VALUES(?,?,?,?)', (row['id'], 'alice', 'agent', 'alice'))
    before = db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],))
    with pytest.raises(HTTPException):
        versions.apply_update(db, security, 'alice', row['id'], filename, raw, expected, confirmed)
    assert db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],)) == before
    assert db.one('SELECT COUNT(*) n FROM skill_bindings')['n'] == 1
    assert versions.list_versions(db, security, 'alice', row['id']) == []
    assert not db.conn.in_transaction


def test_cas_serializes_independent_connections(env):
    db, security, _ = env
    row, filename, _ = imported(env)
    other = Database(db.one('PRAGMA database_list')['file'])

    def change(connection, version):
        raw = skill(version)
        try:
            return versions.apply_update(connection, security, 'alice', row['id'], filename, raw, row['sha256'], sha(raw))
        except HTTPException as error:
            return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(change, connection, version) for connection, version in
                       ((db, '2.0.0'), (other, '3.0.0'))]
            results = [future.result(timeout=10) for future in futures]
        assert sum(isinstance(result, dict) for result in results) == 1
        assert 409 in results
        assert len(versions.list_versions(db, security, 'alice', row['id'])) == 1
    finally:
        other.close()


def test_history_immutable_foreign_revision_and_confirmations(env):
    db, security, _ = env
    row, filename, raw = imported(env)
    changed = update(env, row, filename, skill('2.0.0'))
    revision = changed['archived_revision_id']
    for sql in ('UPDATE resource_revisions SET origin=origin WHERE id=?', 'DELETE FROM resource_revisions WHERE id=?'):
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            db.execute(sql, (revision,))
    other, _, _ = imported(env)
    for rid, expected, target in ((other['id'], other['sha256'], sha(raw)),
                                  (row['id'], '0' * 64, sha(raw)),
                                  (row['id'], sha(skill('2.0.0')), '0' * 64)):
        with pytest.raises(HTTPException):
            versions.rollback(db, security, 'alice', rid, revision, expected, target)
    assert len(versions.list_versions(db, security, 'alice', row['id'])) == 1


def test_quota_counts_archives_and_never_prunes(env, monkeypatch):
    db, security, _ = env
    row, filename, raw = imported(env)
    new = skill('2.0.0')
    changed = update(env, row, filename, new)
    current = db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],))
    # Exactly current + archive fits, but the next package would exceed quota.
    monkeypatch.setattr(versions, 'MAX_ACCOUNT_BYTES', len(raw) + len(new))
    with pytest.raises(HTTPException, match='64 MiB'):
        update(env, current, filename, skill('3.0.0'))
    with pytest.raises(HTTPException):
        versions.rollback(db, security, 'alice', row['id'], changed['archived_revision_id'], sha(new), sha(raw))
    assert len(versions.list_versions(db, security, 'alice', row['id'])) == 1
    monkeypatch.setattr(versions, 'MAX_ACCOUNT_BYTES', 64 * 1024 * 1024)
    monkeypatch.setattr(versions, 'MAX_VERSIONS', 2)
    with pytest.raises(HTTPException, match='20 versões'):
        update(env, current, filename, skill('3.0.0'))
    assert len(versions.list_versions(db, security, 'alice', row['id'])) == 1


def test_audit_failure_rolls_back_whole_change(env, monkeypatch):
    db, _, _ = env
    row, filename, _ = imported(env)
    before = db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],))

    def fail(*args):
        raise RuntimeError('injected audit failure')

    monkeypatch.setattr(versions, 'audit', fail)
    with pytest.raises(RuntimeError, match='injected'):
        update(env, row, filename, skill('2.0.0'))
    assert db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],)) == before
    assert db.all('SELECT * FROM resource_revisions') == []


def test_revision_integrity_binds_identity_digest_and_metadata(env):
    db, security, _ = env
    row, filename, _ = imported(env)
    changed = update(env, row, filename, skill('2.0.0'))
    archived = db.one('SELECT * FROM resource_revisions WHERE id=?', (changed['archived_revision_id'],))
    # SQL cannot edit an archive. A copied/injected archive must also fail its
    # authenticated binding, even when its ciphertext is itself valid Fernet.
    forged = dict(archived, id='forged', sha256='0' * 64, metadata_json=security.encrypt('{}'))
    columns = tuple(forged)
    db.execute('INSERT INTO resource_revisions (' + ','.join(columns) + ') VALUES (' +
               ','.join('?' for _ in columns) + ')', tuple(forged[k] for k in columns))
    before = db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],))
    with pytest.raises(HTTPException) as error:
        versions.rollback(db, security, 'alice', row['id'], 'forged', before['sha256'], '0' * 64)
    assert error.value.status_code == 409
    assert db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],)) == before
    with pytest.raises(HTTPException):
        versions.list_versions(db, security, 'alice', row['id'])


def test_twenty_versions_are_retained_without_pruning(env):
    db, security, _ = env
    row, filename, _ = imported(env)
    for version in range(2, 21):
        update(env, row, filename, skill(f'{version}.0.0'))
        row = db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],))
    history = versions.list_versions(db, security, 'alice', row['id'])
    assert len(history) == 19
    with pytest.raises(HTTPException):
        update(env, row, filename, skill('21.0.0'))
    assert versions.list_versions(db, security, 'alice', row['id']) == history


def test_personal_org_with_other_members_is_shared_and_denied(env):
    db, security, catalog = env
    row, filename, _ = imported(env)
    org = ensure_personal(db, 'alice')
    catalog.share('alice', row['id'], org, row['sha256'])
    db.execute('INSERT INTO organization_members VALUES(?,?,?,?)', (org, 'bob', 'admin', utcnow()))
    with pytest.raises(HTTPException) as error:
        update(env, row, filename, skill('2.0.0'))
    assert error.value.status_code == 403
    assert db.all('SELECT * FROM resource_revisions') == []


def test_mcp_permissions_do_not_activate_unsupported_runtime(env):
    db, security, catalog = env
    row, filename, _ = imported(env, 'mcp')
    replacement = json.loads(manifest('2.0.0'))
    replacement['permissions'] = ['workspace.read', 'workspace.write', 'network', 'external.write']
    raw = json.dumps(replacement).encode()
    changed = update(env, row, filename, raw)
    assert changed['current']['state'] == 'inactive'
    assert changed['current']['execution_enabled'] is False
    with pytest.raises(HTTPException) as error:
        catalog.state('alice', row['id'], 'active', sha(raw))
    assert error.value.status_code == 409
    assert db.one('SELECT state FROM ai_resources WHERE id=?', (row['id'],))['state'] == 'inactive'


def test_official_mcp_update_stays_inactive_and_requires_separate_activation(env):
    db, security, catalog = env
    official = {
        '$schema': 'https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json',
        'name': 'io.github.ChromeDevTools/chrome-devtools-mcp', 'title': 'Chrome DevTools MCP',
        'description': 'Official static fixture',
        'repository': {'url': 'https://github.com/ChromeDevTools/chrome-devtools-mcp', 'source': 'github'},
        'version': '1.0.1', 'packages': [{'registryType': 'npm',
            'registryBaseUrl': 'https://registry.npmjs.org', 'identifier': 'chrome-devtools-mcp',
            'version': '1.0.1', 'transport': {'type': 'stdio'}}],
    }
    row, filename, _ = imported(env, 'mcp', json.dumps(official).encode())
    catalog.state('alice', row['id'], 'active', row['sha256'])
    official['description'] = 'Changed documentation only'
    raw = json.dumps(official).encode()
    update(env, row, filename, raw)
    current = catalog.get('alice', row['id'])
    assert current['metadata']['server_id'] == 'chrome-devtools'
    assert current['state'] == 'inactive' and current['runtime_enabled'] is False
    # This Catalog operation only changes data; no native runtime is invoked.
    assert catalog.state('alice', row['id'], 'active', sha(raw))['state'] == 'active'


def test_explicit_owner_delete_cascades_history_and_bindings(env):
    db, security, catalog = env
    row, filename, original = imported(env)
    changed = update(env, row, filename, skill('2.0.0'))
    versions.rollback(db, security, 'alice', row['id'], changed['archived_revision_id'],
                      sha(skill('2.0.0')), sha(original))
    assert len(versions.list_versions(db, security, 'alice', row['id'])) == 2
    db.execute('INSERT INTO skill_bindings VALUES(?,?,?,?)', (row['id'], 'alice', 'agent', 'alice'))
    # Guard direct history deletion while its owning resource exists.
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        db.execute('DELETE FROM resource_revisions WHERE resource_id=?', (row['id'],))
    assert catalog.delete('alice', row['id']) == {
        'deleted_from_central': True, 'external_uninstall_performed': False}
    # SQLite removes the parent before firing FK delete actions, allowing the
    # guarded trigger to distinguish a cascade from direct history deletion.
    assert db.one('SELECT id FROM ai_resources WHERE id=?', (row['id'],)) is None
    assert db.all('SELECT * FROM resource_revisions WHERE resource_id=?', (row['id'],)) == []
    assert db.all('SELECT * FROM skill_bindings WHERE resource_id=?', (row['id'],)) == []
    assert db.one("SELECT action FROM ops_audit WHERE target_id=? ORDER BY id DESC", (row['id'],))['action'] == 'resource_deleted'


def test_foreign_owner_cannot_delete_private_resource_or_history(env):
    db, security, catalog = env
    row, filename, _ = imported(env)
    update(env, row, filename, skill('2.0.0'))
    before = db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],))
    history = versions.list_versions(db, security, 'alice', row['id'])
    with pytest.raises(HTTPException) as error:
        catalog.delete('bob', row['id'])
    assert error.value.status_code == 404
    assert db.one('SELECT * FROM ai_resources WHERE id=?', (row['id'],)) == before
    assert versions.list_versions(db, security, 'alice', row['id']) == history
