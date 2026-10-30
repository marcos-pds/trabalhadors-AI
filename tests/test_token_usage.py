import uuid

from fastapi.testclient import TestClient

from central.database import uid, utcnow
from central.main import DB, app


HEADERS = {'x-central-request': '1'}


def register(client):
    email = f'{uuid.uuid4().hex}@example.com'
    response = client.post('/api/register', json={
        'email': email, 'password': 'strongpasswordxyz',
    }, headers=HEADERS)
    assert response.status_code == 200
    return response.json()


def test_token_usage_is_aggregated_and_scoped_to_owner():
    with TestClient(app) as owner_client, TestClient(app) as other_client:
        owner = register(owner_client)
        register(other_client)
        conversation = owner_client.post(
            '/api/conversations', json={'title': 'Uso de tokens'}, headers=HEADERS,
        ).json()
        run_id = uid()
        now = utcnow()
        DB.execute(
            '''INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,
                                agent_ids,plan,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (run_id, owner['id'], conversation['id'], 'Pergunta de teste',
             'completed', 'auto', '[]', '[]', now, now),
        )
        DB.execute(
            '''INSERT INTO token_usage
               (id,user_id,run_id,agent_name,provider_name,model,input_tokens,
                output_tokens,source,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (uid(), owner['id'], run_id, 'Agente teste', 'Provedor teste',
             'modelo-teste', 17, 8, 'actual', now),
        )
        DB.execute(
            '''INSERT INTO token_usage
               (id,user_id,run_id,agent_name,provider_name,model,input_tokens,
                output_tokens,source,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (uid(), owner['id'], run_id, 'Agente teste', 'Provedor teste',
             'modelo-teste', 4, 3, 'estimated', now),
        )

        usage_response = owner_client.get(f'/api/runs/{run_id}/token-usage')
        assert usage_response.status_code == 200
        usage = usage_response.json()
        assert usage['input_tokens'] == 21
        assert usage['output_tokens'] == 11
        assert usage['total_tokens'] == 32
        assert usage['actual_tokens'] == 25
        assert usage['estimated_tokens'] == 7
        assert usage['generation_count'] == 2
        assert usage['balance_available'] is False

        overview_response = owner_client.get('/api/token-usage?days=30')
        assert overview_response.status_code == 200
        overview = overview_response.json()
        assert overview['totals']['total_tokens'] == 32
        assert overview['recent_runs'][0]['run_id'] == run_id
        assert overview['providers'][0]['provider_name'] == 'Provedor teste'
        assert other_client.get(f'/api/runs/{run_id}/token-usage').status_code == 404
        assert other_client.get('/api/token-usage?days=1').status_code == 422
