"""Project document RAG with explicit visibility, source IDs and expiry.

Text-only ingestion: no crawlers, file paths, remote fetches or document code
execution. Chat history remains private even when documents are shared.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException
from .database import uid, utcnow
from .organizations import require_project, require_org, project_org
from .memory import terms
from . import semantic_memory as semantic

SCHEMA = '''
CREATE TABLE IF NOT EXISTS knowledge_documents (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, content TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('private','project')),
 fingerprint TEXT NOT NULL, expires_at TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge_documents(project_id,user_id,expires_at);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, content TEXT NOT NULL, UNIQUE(document_id,position)
);
CREATE TABLE IF NOT EXISTS knowledge_embeddings (
 chunk_id TEXT NOT NULL REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
 model TEXT NOT NULL, vector_json TEXT NOT NULL, PRIMARY KEY(chunk_id,model)
);
'''


def purge_expired(db):
    return db.execute('DELETE FROM knowledge_documents WHERE id IN '
                      '(SELECT id FROM knowledge_documents WHERE expires_at IS NOT NULL '
                      'AND expires_at<=? LIMIT 500)', (utcnow(),))


def create(db, user_id, project_id, title, content, visibility='private', retention_days=90):
    if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 140
            or not isinstance(content, str) or not content.strip()
            or len(content.encode('utf-8')) > 128000 or '\x00' in content):
        raise HTTPException(422, 'Informe título e texto UTF-8 com até 128 KB.')
    if visibility not in ('private', 'project'):
        raise HTTPException(422, 'Visibilidade deve ser private ou project.')
    if retention_days is not None and (type(retention_days) is not int or not 1 <= retention_days <= 3650):
        raise HTTPException(422, 'Retenção deve ser 1..3650 dias ou permanente.')
    require_project(db, project_id, user_id, write=True)
    purge_expired(db)
    expires = ((datetime.now(timezone.utc) + timedelta(days=retention_days)).isoformat()
               if retention_days is not None else None)
    document_id = uid()
    with db.lock:
        db.conn.execute('BEGIN IMMEDIATE')
        try:
            require_project(db, project_id, user_id, write=True)
            count = db.one('SELECT COUNT(*) AS total,SUM(CASE WHEN user_id=? THEN 1 ELSE 0 END) AS personal '
                           'FROM knowledge_documents WHERE project_id=?', (user_id, project_id))
            if count['total'] >= 100 or (count['personal'] or 0) >= 25:
                raise HTTPException(429, 'Limite de documentos atingido neste projeto.')
            db.conn.execute('INSERT INTO knowledge_documents VALUES(?,?,?,?,?,?,?,?,?)',
                            (document_id, project_id, user_id, title.strip(), content, visibility,
                             hashlib.sha256(content.encode()).hexdigest(), expires, utcnow()))
            for position, offset in enumerate(range(0, len(content), 850)):
                db.conn.execute('INSERT INTO knowledge_chunks VALUES(?,?,?,?)',
                                (uid(), document_id, position, content[offset:offset + 1000]))
            db.conn.execute('COMMIT')
        except BaseException:
            db.conn.execute('ROLLBACK')
            raise
    return {'id': document_id, 'title': title.strip(), 'visibility': visibility, 'expires_at': expires}


def documents(db, user_id, project_id):
    require_project(db, project_id, user_id)
    purge_expired(db)
    return db.all('SELECT id,title,visibility,expires_at,created_at,user_id=? AS owned '
                   'FROM knowledge_documents WHERE project_id=? AND (user_id=? OR visibility=?) '
                   'AND (expires_at IS NULL OR expires_at>?) ORDER BY created_at DESC LIMIT 100',
                   (user_id, project_id, user_id, 'project', utcnow()))


def delete(db, user_id, project_id, document_id):
    require_project(db, project_id, user_id, write=True)
    row = db.one('SELECT user_id,visibility FROM knowledge_documents WHERE id=? AND project_id=?',
                 (document_id, project_id))
    if not row or (row['visibility'] == 'private' and row['user_id'] != user_id):
        raise HTTPException(404, 'Documento não encontrado.')
    if row['user_id'] != user_id:
        org = project_org(db, project_id)
        if not org:
            raise HTTPException(403, 'Somente o autor pode excluir este documento.')
        require_org(db, org['organization_id'], user_id, admin=True)
    db.execute('DELETE FROM knowledge_documents WHERE id=? AND project_id=?', (document_id, project_id))
    return {'deleted': True}


def retrieve(db, user_id, project_id, query):
    require_project(db, project_id, user_id)
    purge_expired(db)
    rows = db.all('''SELECT k.id,k.content,k.position,d.id AS document_id,d.title,d.created_at
        FROM knowledge_chunks k JOIN knowledge_documents d ON d.id=k.document_id
        WHERE d.project_id=? AND (d.user_id=? OR d.visibility='project')
        AND (d.expires_at IS NULL OR d.expires_at>?)
        ORDER BY d.created_at DESC,k.position LIMIT 1200''', (project_id, user_id, utcnow()))
    tokens = terms(query)
    ranked = [(len(tokens & terms(row['content'])), row) for row in rows]
    ranked.sort(key=lambda item: -item[0])
    if rows and semantic.preference(db, user_id, project_id)['enabled']:
        model = semantic.preference(db, user_id, project_id)['model']
        candidates = [row for _, row in ranked[:120]]
        missing, vectors = [], {}
        for row in candidates:
            cached = db.one('SELECT vector_json FROM knowledge_embeddings WHERE chunk_id=? AND model=?',
                             (row['id'], model))
            if cached:
                vectors[row['id']] = json.loads(cached['vector_json'])
            elif len(missing) < 16:
                missing.append(row)
        try:
            batch = semantic.embed([query[:1800]] + [row['content'] for row in missing])
            for row, vector in zip(missing, batch[1:]):
                db.execute('INSERT INTO knowledge_embeddings SELECT ?,?,? '
                           'WHERE EXISTS(SELECT 1 FROM knowledge_chunks WHERE id=?) '
                           'ON CONFLICT(chunk_id,model) DO UPDATE SET vector_json=excluded.vector_json',
                           (row['id'], model, json.dumps(vector), row['id']))
                vectors[row['id']] = vector
            semantic_ranked = [(semantic.cosine(batch[0], vectors[row['id']]), row)
                               for row in candidates if row['id'] in vectors]
            semantic_ranked.sort(key=lambda item: -item[0])
            chosen = [(score, row) for score, row in semantic_ranked if score >= .35]
            chosen_ids = {row['id'] for _, row in chosen}
            ranked = chosen + [(score, row) for score, row in ranked if row['id'] not in chosen_ids]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass
    # Membership and expiry can change during a slow embedding request.
    require_project(db, project_id, user_id)
    visible = {row['id'] for row in db.all('SELECT id FROM knowledge_documents '
               'WHERE project_id=? AND (user_id=? OR visibility=?) '
               'AND (expires_at IS NULL OR expires_at>?)', (project_id, user_id, 'project', utcnow()))}
    result, per_document = [], set()
    for score, row in ranked:
        if score <= 0 or row['document_id'] not in visible or row['document_id'] in per_document:
            continue
        result.append({'document_id': row['document_id'], 'conversation_id': None,
                       'chunk_id': row['id'], 'title': row['title'], 'role': 'document',
                       'content': row['content'][:800], 'retrieval': 'project_document'})
        per_document.add(row['document_id'])
        if len(result) == 2:
            break
    return result
