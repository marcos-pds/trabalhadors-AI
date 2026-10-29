"""Real SQLite verification of the opt-in specialist pack."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from uuid import UUID

import pytest

from central.database import Database, utcnow
from central.specialist_profiles import (
    SPECIALIST_PROFILES, install_missing_profiles, list_missing_profiles,
)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / 'profiles.sqlite')
    for owner in ('alice', 'bob'):
        database.execute('INSERT INTO users VALUES(?,?,?,?)',
                         (owner, owner + '@example.test', 'hash', utcnow()))
    yield database
    database.close()


def test_preview_install_defaults_and_idempotency(db):
    preview = list_missing_profiles(db, 'alice')
    assert len(preview) == 5
    assert db.all('SELECT * FROM agents') == []
    assert {p['specialty'] for p in preview} == {'review', 'backend', 'code'}
    result = install_missing_profiles(db, 'alice')
    assert len(result['created_ids']) == 5
    assert result['existing_ids'] == []
    rows = db.all('SELECT * FROM agents WHERE user_id=?', ('alice',))
    assert {r['name'] for r in rows} == {p[0] for p in SPECIALIST_PROFILES}
    for row in rows:
        assert str(UUID(row['id'])) == row['id']
        assert row['provider_id'] is None and row['model'] is None
        assert row['enabled'] == row['max_concurrency'] == 1
        assert row['created_at'] and row['avatar'] and row['instructions']
    assert list_missing_profiles(db, 'alice') == []
    again = install_missing_profiles(db, 'alice')
    assert again['created_ids'] == []
    assert set(again['existing_ids']) == set(result['created_ids'])
    assert db.all('SELECT * FROM agents WHERE user_id=?', ('alice',)) == rows


def test_owner_isolation_and_customized_exact_name(db):
    db.execute('INSERT INTO agents '
               '(id,user_id,name,specialty,instructions,provider_id,model,enabled,max_concurrency,created_at) '
               'VALUES(?,?,?,?,?,?,?,?,?,?)',
               ('custom', 'alice', 'Testador QA', 'custom', 'Keep me', 'p', 'm', 0, 7, utcnow()))
    before = db.one('SELECT * FROM agents WHERE id=?', ('custom',))
    bob = install_missing_profiles(db, 'bob')
    assert len(bob['created_ids']) == 5
    assert len(list_missing_profiles(db, 'alice')) == 4
    alice = install_missing_profiles(db, 'alice')
    assert alice['existing_ids'] == ['custom']
    assert len(alice['created_ids']) == 4
    assert not set(alice['created_ids']) & set(bob['created_ids'])
    assert db.one('SELECT * FROM agents WHERE id=?', ('custom',)) == before


@pytest.mark.parametrize('helper', [list_missing_profiles, install_missing_profiles])
def test_unknown_user_rejected(db, helper):
    with pytest.raises(ValueError, match='User not found'):
        helper(db, 'missing')
    assert db.all('SELECT * FROM agents') == []
    assert not db.conn.in_transaction


def test_failure_rolls_back_entire_pack(db):
    db.execute("CREATE TRIGGER fail_pack BEFORE INSERT ON agents "
               "WHEN NEW.name='Especialista em Banco de Dados' "
               "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(Exception, match='injected failure'):
        install_missing_profiles(db, 'alice')
    assert db.all('SELECT * FROM agents') == []
    assert not db.conn.in_transaction


def test_names_are_exact_and_outer_transaction_is_not_committed(db):
    db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,created_at) '
               'VALUES(?,?,?,?,?,?)',
               ('lower', 'alice', 'testador qa', 'custom', 'untouched', utcnow()))
    assert len(list_missing_profiles(db, 'alice')) == 5
    db.conn.execute('BEGIN')
    db.execute("UPDATE agents SET instructions='pending' WHERE id='lower'")
    with pytest.raises(Exception, match='within a transaction'):
        install_missing_profiles(db, 'alice')
    assert db.conn.in_transaction
    db.conn.execute('ROLLBACK')
    assert db.one("SELECT instructions FROM agents WHERE id='lower'")['instructions'] == 'untouched'
    assert len(install_missing_profiles(db, 'alice')['created_ids']) == 5


def _install_in_process(path):
    database = Database(path)
    try:
        return install_missing_profiles(database, 'alice')
    finally:
        database.close()


def test_concurrent_processes_create_one_pack(db):
    path = db.one('PRAGMA database_list')['file']
    with ProcessPoolExecutor(max_workers=4, mp_context=get_context('spawn')) as pool:
        results = list(pool.map(_install_in_process, [path] * 8))
    assert sum(len(r['created_ids']) for r in results) == 5
    rows = db.all('SELECT name,COUNT(*) AS n FROM agents GROUP BY name')
    assert len(rows) == 5 and all(row['n'] == 1 for row in rows)
    ids = {r['id'] for r in db.all('SELECT id FROM agents')}
    assert all(set(r['created_ids'] + r['existing_ids']) == ids for r in results)
