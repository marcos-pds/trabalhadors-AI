import pytest
from fastapi import HTTPException
from central import knowledge, semantic_memory
from central.database import Database
from central.memory import build_memory
from central.organizations import create_organization, set_member, remove_member
from test_memory import user, project, convo, message


@pytest.fixture
def workspace():
    db = Database(':memory:')
    for name in ('alice', 'bob', 'outsider'):
        user(db, name)
    org = create_organization(db, 'alice', 'Equipe')
    set_member(db, org, 'alice', 'bob', 'operator')
    project(db, 'alice', 'p'); project(db, 'alice', 'other')
    db.execute('INSERT INTO organization_projects VALUES(?,?)', ('p', org))
    convo(db, 'alice', 'chat', 'p'); convo(db, 'bob', 'bob-chat', 'p')
    yield db, org
    db.close()


def test_document_visibility_does_not_share_private_chat_or_other_projects(workspace):
    db, org = workspace
    private = knowledge.create(db, 'alice', 'p', 'Privado', 'login SEGREDO-PESSOAL')
    shared = knowledge.create(db, 'alice', 'p', 'Requisitos', 'login usa sessão segura', 'project')
    knowledge.create(db, 'alice', 'other', 'Outro projeto', 'login OUTRO-PROJETO')
    message(db, 'alice', 'chat', 'login CHAT-PRIVADO-DA-ALICE')
    assert len(knowledge.documents(db, 'bob', 'p')) == 1
    memory = build_memory(db, 'bob', 'bob-chat', 'login')
    assert 'sessão segura' in memory['text'] and 'Documento: Requisitos' in memory['text']
    for secret in ('SEGREDO-PESSOAL', 'OUTRO-PROJETO', 'CHAT-PRIVADO-DA-ALICE'):
        assert secret not in memory['text']
    assert memory['sources'][0]['document_id'] == shared['id']
    with pytest.raises(HTTPException):
        knowledge.documents(db, 'outsider', 'p')
    with pytest.raises(HTTPException):
        knowledge.delete(db, 'bob', 'p', private['id'])
    remove_member(db, org, 'alice', 'bob')
    with pytest.raises(HTTPException):
        knowledge.retrieve(db, 'bob', 'p', 'login')


def test_retention_excludes_source_and_cascades_chunks_and_embeddings(workspace):
    db, _ = workspace
    doc = knowledge.create(db, 'alice', 'p', 'Temporário', 'login e autenticação')
    chunk = db.one('SELECT id FROM knowledge_chunks WHERE document_id=?', (doc['id'],))
    db.execute('INSERT INTO knowledge_embeddings VALUES(?,?,?)', (chunk['id'], 'model', '[1,0]'))
    db.execute("UPDATE knowledge_documents SET expires_at='2000-01-01' WHERE id=?", (doc['id'],))
    assert knowledge.retrieve(db, 'alice', 'p', 'login') == []
    assert db.all('SELECT * FROM knowledge_chunks') == []
    assert db.all('SELECT * FROM knowledge_embeddings') == []
    permanent = knowledge.create(db, 'alice', 'p', 'Permanente', 'manual', retention_days=None)
    assert permanent['expires_at'] is None


def test_semantic_documents_are_opt_in_and_cached_without_embedding_private_sources(workspace, monkeypatch):
    db, _ = workspace
    knowledge.create(db, 'alice', 'p', 'Privado', 'NUNCA-ENVIAR-PARA-BOB')
    doc = knowledge.create(db, 'alice', 'p', 'Manual', 'Autenticação com refresh tokens', 'project')
    sent = []
    def embed(texts):
        sent.extend(texts)
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(semantic_memory, 'embed', embed)
    assert knowledge.retrieve(db, 'bob', 'p', 'credenciais') == []
    assert not sent
    semantic_memory.preference(db, 'bob', 'p', True)
    result = knowledge.retrieve(db, 'bob', 'p', 'credenciais')
    assert result[0]['document_id'] == doc['id']
    assert not any('NUNCA-ENVIAR-PARA-BOB' in text for text in sent)
    sent.clear()
    knowledge.retrieve(db, 'bob', 'p', 'credenciais')
    assert sent == ['credenciais']


def test_document_deletion_during_embedding_never_leaks_stale_source(workspace, monkeypatch):
    db, _ = workspace
    doc = knowledge.create(db, 'alice', 'p', 'Manual', 'login credenciais')
    semantic_memory.preference(db, 'alice', 'p', True)
    def embed(texts):
        knowledge.delete(db, 'alice', 'p', doc['id'])
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(semantic_memory, 'embed', embed)
    assert knowledge.retrieve(db, 'alice', 'p', 'credenciais') == []
    assert not db.all('SELECT * FROM knowledge_embeddings')


def test_document_ingestion_limits_and_analyst_permissions(workspace):
    db, org = workspace
    set_member(db, org, 'alice', 'bob', 'analyst')
    with pytest.raises(HTTPException):
        knowledge.create(db, 'bob', 'p', 'Negado', 'documento')
    for content, visibility, days in [('x' * 128001, 'private', 90),
                                      ('texto', 'public', 90), ('texto', 'private', 0)]:
        with pytest.raises(HTTPException):
            knowledge.create(db, 'alice', 'p', 'Inválido', content, visibility, days)


def test_document_quota_is_enforced_atomically(workspace):
    db, _ = workspace
    for number in range(25):
        knowledge.create(db, 'alice', 'p', 'Reference ' + str(number), 'bounded text')
    with pytest.raises(HTTPException) as error:
        knowledge.create(db, 'alice', 'p', 'Above limit', 'bounded text')
    assert error.value.status_code == 429
    assert db.one('SELECT COUNT(*) AS n FROM knowledge_documents')['n'] == 25


def test_revoked_member_cannot_receive_document_after_embedding_request(workspace, monkeypatch):
    db, org = workspace
    knowledge.create(db, 'alice', 'p', 'Manual', 'login credenciais', 'project')
    semantic_memory.preference(db, 'bob', 'p', True)
    def embed(texts):
        remove_member(db, org, 'alice', 'bob')
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(semantic_memory, 'embed', embed)
    with pytest.raises(HTTPException):
        knowledge.retrieve(db, 'bob', 'p', 'credenciais')
