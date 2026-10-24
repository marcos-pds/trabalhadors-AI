"""Regression for default workers accidentally stored as architecture."""
import asyncio

from fastapi.testclient import TestClient

from central.database import Database, uid, utcnow
from central.engine import (
    Engine, TEMPLATES, discover_agents, effective_specialty,
    recoverable_default_agents, team_for_task,
)


def fake_workers(specialty='architecture'):
    return [dict(id=str(n), name=name, specialty=specialty, instructions=instructions,
                 enabled=1, avatar=avatar)
            for n, (name, intended, instructions, avatar) in enumerate(TEMPLATES)]


def test_corrupted_standard_workers_still_route_to_frontend_and_reviewer():
    agents = fake_workers()
    assert len(recoverable_default_agents(agents)) == len(TEMPLATES) - 1
    selected = team_for_task(agents, 'Desenvolva a landing page NOVA STUDIO com React, testes e correções.')
    assert [effective_specialty(a) for a in selected] == ['architecture', 'frontend', 'review']
    assert [a['name'] for a in selected] == ['Arquiteto IA', 'Frontend IA', 'Revisor IA']


def test_team_mode_no_longer_collapses_to_single_architect_when_keywords_match():
    selected = discover_agents(fake_workers(), 'Desenvolva um projeto e arquitetura', mode='team')
    assert len(selected) == 3
    assert len({a['id'] for a in selected}) == 3


def test_custom_worker_specialties_are_not_guessed_from_names():
    agents = fake_workers()
    changed = next(a for a in agents if a['name'] == 'Programador IA')
    changed['instructions'] = 'Especialista personalizado em arquitetura.'
    assert effective_specialty(changed) == 'architecture'
    assert changed not in recoverable_default_agents(agents)
    renamed = next(a for a in agents if a['name'] == 'Backend IA')
    renamed['name'] = 'Meu Backend IA personalizado'
    assert effective_specialty(renamed) == 'architecture'


def test_engine_builds_real_team_even_when_stored_specialties_are_all_wrong():
    db = Database(':memory:')
    try:
        db.execute('INSERT INTO users VALUES(?,?,?,?)',
                   ('user', 'test@example.com', 'hash', utcnow()))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                   ('chat', 'user', 'Nova conversa', None, utcnow(), utcnow()))
        for agent in fake_workers():
            db.execute(
                'INSERT INTO agents(id,user_id,name,specialty,instructions,avatar,created_at) '
                'VALUES(?,?,?,?,?,?,?)',
                (agent['id'], 'user', agent['name'], agent['specialty'],
                 agent['instructions'], agent['avatar'], utcnow()))
        engine = Engine(db, None)
        engine.schedule = lambda rid: None
        async def go():
            return engine.create_run(
                'user', 'chat', 'Desenvolva uma landing page premium React',
                'team', autonomous=True)
        rid = asyncio.run(go())
        run = db.one('SELECT * FROM runs WHERE id=?', (rid,))
        steps = db.all('SELECT * FROM steps WHERE run_id=? ORDER BY rowid', (rid,))
        assert run['status'] == 'queued'
        assert [step['name'] for step in steps] == [
            'Arquiteto IA', 'Frontend IA', 'Revisor IA']
        assert steps[1]['deps'] == '["' + steps[0]['id'] + '"]'
        assert steps[2]['deps'] == '["' + steps[1]['id'] + '"]'
    finally:
        db.close()


def test_explicit_repair_preserves_custom_settings_and_requires_authorized_user():
    # Use the app's test database; each account is generated independently.
    import uuid
    from central.main import app, DB
    headers = {'X-Central-Request': '1'}
    def create_user(client):
        response = client.post('/api/register', headers=headers,
            json={'email': uuid.uuid4().hex + '@example.com',
                  'password': 'strongpasswordxyz'})
        assert response.status_code == 200, response.text
        return response.json()
    with TestClient(app) as client, TestClient(app) as outsider:
        first_user = create_user(client)
        create_user(outsider)
        rows = client.get('/api/agents').json()
        assert len(rows) == len(TEMPLATES)
        coder = next(a for a in rows if a['name'] == 'Programador IA')
        frontend = next(a for a in rows if a['name'] == 'Frontend IA')
        DB.execute("UPDATE agents SET specialty='architecture' WHERE user_id=?",
                   (first_user['id'],))
        DB.execute("UPDATE agents SET instructions=? WHERE id=?",
                   ('Instruções personalizadas mantidas', coder['id']))
        before = client.get('/api/agents').json()
        detected = {a['name'] for a in before if a.get('suggested_specialty') != a['specialty']}
        assert 'Frontend IA' in detected
        assert 'Programador IA' not in detected
        assert next(a for a in before if a['id'] == frontend['id'])['suggested_specialty'] == 'frontend'
        assert outsider.post('/api/agents/restore-default-specialties', headers=headers).json()['repaired_count'] == 0
        assert client.post('/api/agents/restore-default-specialties').status_code == 403
        repair = client.post('/api/agents/restore-default-specialties', headers=headers)
        assert repair.status_code == 200, repair.text
        assert repair.json()['repaired_count'] == len(TEMPLATES) - 2
        restored = client.get('/api/agents').json()
        assert next(a for a in restored if a['name']=='Frontend IA')['specialty'] == 'frontend'
        assert next(a for a in restored if a['name']=='Revisor IA')['specialty'] == 'review'
        assert next(a for a in restored if a['name']=='Programador IA')['specialty'] == 'architecture'
        assert next(a for a in restored if a['name']=='Programador IA')['instructions'] == 'Instruções personalizadas mantidas'
        assert client.post('/api/agents/restore-default-specialties', headers=headers).json()['repaired_count'] == 0
