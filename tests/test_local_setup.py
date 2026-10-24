from central.database import Database
from configurar_local import configure


def test_local_setup_preserves_accounts_and_is_idempotent(tmp_path):
    db = Database(tmp_path / 'test.sqlite3')
    try:
        for user in ('u1', 'u2'):
            db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, user+'@test.local', 'hash', 'now'))
            db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,api_key_enc,created_at) '
                       'VALUES(?,?,?,?,?,?,?,?)',
                       (user, user, 'Cloud', 'groq', 'https://example.com', 'cloud-model', 'secret', 'now'))
            db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,provider_id,model,created_at) '
                       'VALUES(?,?,?,?,?,?,?,?)',
                       (user, user, 'Agent', 'code', 'Help', user, 'cloud-model', 'now'))
        configure(db, 'local-model')
        configure(db, 'local-model')
        assert len(db.all('SELECT * FROM providers')) == 4
        for user in ('u1', 'u2'):
            active = db.all('SELECT * FROM providers WHERE user_id=? AND enabled=1', (user,))
            assert len(active) == 1
            assert active[0]['kind'] == 'ollama'
            assert active[0]['model'] == 'local-model'
            assert active[0]['api_key_enc'] is None
            assert db.one('SELECT api_key_enc FROM providers WHERE id=?', (user,))['api_key_enc'] == 'secret'
            agent = db.one('SELECT * FROM agents WHERE id=?', (user,))
            assert agent['provider_id'] == active[0]['id']
            assert agent['model'] is None
    finally:
        db.close()
