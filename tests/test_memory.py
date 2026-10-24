"""Project memories: bounded, scoped, inspectable and user-controlled."""
import sqlite3

from central.database import Database, utcnow
from central.memory import build_memory, search_history, terms


def user(db, uid):
    db.execute('INSERT INTO users VALUES(?,?,?,?)',
               (uid, uid + '@example.com', 'hash', utcnow()))


def project(db, uid, pid, name='Projeto'):
    db.execute('INSERT INTO projects(id,user_id,name,description,created_at) VALUES(?,?,?,?,?)',
               (pid, uid, name, 'Descrição do projeto ' + name, utcnow()))


def convo(db, uid, cid, project_id=None):
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
               (cid, uid, 'Conversa ' + cid, project_id, utcnow(), utcnow()))


def message(db, uid, cid, content, role='user'):
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
               (cid + ':' + str(len(db.all('SELECT id FROM messages'))), cid, uid, role,
                'Central IA' if role == 'assistant' else None, content, utcnow()))


def test_standalone_remembers_only_few_recent_messages_and_never_other_chats():
    db = Database(':memory:')
    user(db, 'one')
    convo(db, 'one', 'free')
    convo(db, 'one', 'other-free')
    for i in range(15):
        message(db, 'one', 'free', f'Detalhe avulso {i} sobre login e cadastro')
    message(db, 'one', 'other-free', 'O sistema usa um segredo entre conversas avulsas')
    memory = build_memory(db, 'one', 'free', 'relembre login')
    assert memory['scope'] == 'avulsa'
    assert 'Detalhe avulso 14' in memory['text']
    assert 'Detalhe avulso 0' not in memory['text']
    assert memory['text'].count('Usuário:') <= 6
    assert 'segredo entre conversas' not in memory['text']
    assert memory['sources'] == []
    db.close()


def test_project_remembers_more_and_recalls_relevant_same_project_messages():
    db = Database(':memory:')
    user(db, 'one')
    user(db, 'two')
    project(db, 'one', 'site', 'Site')
    project(db, 'one', 'finance', 'Finanças')
    project(db, 'two', 'someone-else', 'Privado')
    convo(db, 'one', 'work', 'site')
    convo(db, 'one', 'earlier', 'site')
    convo(db, 'one', 'unrelated', 'finance')
    convo(db, 'two', 'outsider', 'someone-else')
    db.execute("UPDATE projects SET memory_notes=? WHERE id=?", (
        'Decisão confirmada: autenticação via JWT; problema pendente: tokens expiram.', 'site'))
    for i in range(12):
        message(db, 'one', 'work', f'Detalhe do projeto numero {i}')
    message(db, 'one', 'earlier', 'No fluxo de autenticação de login, decidimos usar refresh tokens.')
    message(db, 'one', 'unrelated', 'No login, a senha mestra é INFORMAÇÃO-DE-OUTRO-PROJETO.')
    message(db, 'two', 'outsider', 'Autenticação de login: INFORMAÇÃO-DE-OUTRO-USUARIO.')
    memory = build_memory(db, 'one', 'work', 'Precisamos rever autenticação login.')
    assert memory['scope'] == 'projeto'
    assert 'Detalhe do projeto numero 0' in memory['text']
    assert 'JWT' in memory['text']
    assert 'refresh tokens' in memory['text']
    assert 'INFORMAÇÃO-DE-OUTRO-PROJETO' not in memory['text']
    assert 'INFORMAÇÃO-DE-OUTRO-USUARIO' not in memory['text']
    assert [r['conversation_id'] for r in memory['sources']] == ['earlier']
    assert len(memory['text']) < 31000
    db.close()


def test_recall_avoids_irrelevant_messages_and_respects_same_project_only():
    db = Database(':memory:')
    user(db, 'one')
    project(db, 'one', 'site')
    convo(db, 'one', 'work', 'site')
    convo(db, 'one', 'earlier', 'site')
    message(db, 'one', 'earlier', 'Falamos sobre roteamento HTTP do backend.')
    memory = build_memory(db, 'one', 'work', 'Como desenhar o logotipo vetorial?')
    assert memory['sources'] == []
    db.close()


def test_search_is_explicit_and_scoped_without_cross_project_recall():
    db = Database(':memory:')
    user(db, 'one')
    user(db, 'two')
    project(db, 'one', 'a')
    project(db, 'one', 'b')
    convo(db, 'one', 'a-chat', 'a')
    convo(db, 'one', 'b-chat', 'b')
    convo(db, 'one', 'free')
    convo(db, 'two', 'hidden')
    for cid, uid in [('a-chat', 'one'), ('b-chat', 'one'), ('free', 'one'),
                     ('hidden', 'two')]:
        message(db, uid, cid, 'Decisão sobre endpoints da API REST em produção.')
    assert [r['conversation_id'] for r in search_history(db, 'one', 'API', 'a')] == ['a-chat']
    assert [r['conversation_id'] for r in search_history(db, 'one', 'API')] == ['free']
    ids = {r['conversation_id'] for r in search_history(db, 'one', 'API', 'a', all_projects=True)}
    assert ids == {'a-chat', 'b-chat', 'free'}
    assert 'hidden' not in ids
    assert terms('API SQL autenticação')
    db.close()


def test_legacy_sqlite_is_migrated_without_losing_notes_or_projects(tmp_path):
    path = tmp_path / 'legacy.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE projects(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,description TEXT,created_at TEXT)')
    conn.execute('INSERT INTO projects VALUES(?,?,?,?,?)', ('old', 'one', 'Antigo', 'Histórico intacto', 'now'))
    conn.commit()
    conn.close()

    db = Database(path)
    row = db.one('SELECT * FROM projects WHERE id=?', ('old',))
    assert row['name'] == 'Antigo'
    assert row['description'] == 'Histórico intacto'
    assert row['memory_notes'] == ''
    db.execute('UPDATE projects SET memory_notes=? WHERE id=?', ('Continuar com FastAPI', 'old'))
    db.close()

    again = Database(path)
    assert again.one('SELECT memory_notes FROM projects WHERE id=?', ('old',))['memory_notes'] == 'Continuar com FastAPI'
    again.close()
