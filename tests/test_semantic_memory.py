import pytest
from fastapi import HTTPException
from central.database import Database
from central import semantic_memory as semantic
from test_memory import user, project, convo, message


def test_opt_in_semantic_recall_never_embeds_other_users_or_projects(monkeypatch):
    db = Database(':memory:')
    for name in ('alice', 'bob'):
        user(db, name)
        project(db, name, name)
        convo(db, name, name + '-old', name)
        convo(db, name, name + '-new', name)
    message(db, 'alice', 'alice-old', 'Authentication uses refresh tokens')
    message(db, 'bob', 'bob-old', 'BOB SECRET')
    calls = []
    def embed(texts):
        calls.extend(texts)
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(semantic, 'embed', embed)
    assert semantic.retrieve(db, 'alice', 'alice', 'alice-new', 'login') == []
    assert not calls
    semantic.preference(db, 'alice', 'alice', True)
    result = semantic.retrieve(db, 'alice', 'alice', 'alice-new', 'login')
    assert len(result) == 1 and result[0]['retrieval'] == 'semantic'
    assert not any('BOB SECRET' in text for text in calls)
    calls.clear()
    semantic.retrieve(db, 'alice', 'alice', 'alice-new', 'login')
    assert calls == ['login']  # immutable source fingerprint cache
    with pytest.raises(HTTPException):
        semantic.preference(db, 'bob', 'alice', True)
    db.close()


def test_local_embedding_endpoint_rejects_remote_origin(monkeypatch):
    monkeypatch.setenv('CENTRAL_EMBEDDING_URL', 'https://example.com')
    with pytest.raises(ValueError, match='local Ollama'):
        semantic.embed(['private'])


def test_optional_semantic_service_failure_retains_lexical_fallback(monkeypatch):
    db = Database(':memory:')
    user(db, 'one'); project(db, 'one', 'p')
    convo(db, 'one', 'old', 'p'); convo(db, 'one', 'new', 'p')
    message(db, 'one', 'old', 'Detalhes do login e autenticação')
    semantic.preference(db, 'one', 'p', True)
    def fail(_texts):
        raise ValueError('invalid embedding')
    monkeypatch.setattr(semantic, 'embed', fail)
    from central.memory import build_memory
    assert build_memory(db, 'one', 'new', 'login autenticação')['sources']
    db.close()
