"""Unit checks for the account-scoped ChatGPT plan provider contract."""
from urllib.parse import parse_qs, urlparse

from central import chatgpt_plan


def test_authorization_url_uses_pkce_local_client_and_plan_consent():
    verifier, challenge = chatgpt_plan.pkce_pair()
    url = chatgpt_plan.authorization_url(
        client_id='dynamic_agent_client', host_id='urn:uuid:install-id',
        app_name='Central de Trabalhadores IA', redirect_uri='http://127.0.0.1:8765/api/chatgpt-plan/callback',
        state='random-state', nonce='random-nonce', challenge=challenge,
    )
    params = parse_qs(urlparse(url).query)
    assert len(verifier) >= 43
    assert params['client_id'] == ['dynamic_agent_client']
    assert params['code_challenge_method'] == ['S256']
    assert params['code_challenge'] == [challenge]
    assert params['ext_agent_host_id'] == ['urn:uuid:install-id']
    assert 'chatgpt.tokens.use.direct' in params['scope'][0].split()
    assert params['redirect_uri'] == ['http://127.0.0.1:8765/api/chatgpt-plan/callback']


def test_model_selector_excludes_models_not_visible_to_account():
    models = chatgpt_plan.visible_models([
        {'slug': 'gpt-visible', 'display_name': 'GPT visible', 'visibility': 'list'},
        {'slug': 'internal-model', 'display_name': 'Internal', 'visibility': 'hidden'},
        {'display_name': 'No slug', 'visibility': 'list'},
    ])
    assert models == [{'id': 'gpt-visible', 'name': 'GPT visible'}]


def test_response_payload_uses_non_stored_stream_and_supported_context_fields():
    payload = chatgpt_plan.response_payload('gpt-visible', 'Be concise', [
        {'role': 'user', 'content': 'Hello'},
        {'role': 'assistant', 'content': 'Hi'},
    ])
    assert payload == {
        'model': 'gpt-visible', 'instructions': 'Be concise',
        'input': [{'role': 'user', 'content': 'Hello'}, {'role': 'assistant', 'content': 'Hi'}],
        'store': False, 'stream': True,
    }
    assert 'max_output_tokens' not in payload
    assert 'previous_response_id' not in payload

