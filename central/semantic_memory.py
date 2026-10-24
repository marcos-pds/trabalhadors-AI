"""Opt-in local embeddings with source fingerprints and project/user scoping."""
import hashlib
import json
import math
import os
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from .database import utcnow
from .organizations import require_project

SCHEMA = '''
CREATE TABLE IF NOT EXISTS memory_preferences (
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 PRIMARY KEY(user_id,project_id)
);
CREATE TABLE IF NOT EXISTS memory_embeddings (
 message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
 model TEXT NOT NULL, fingerprint TEXT NOT NULL, vector_json TEXT NOT NULL,
 updated_at TEXT NOT NULL, PRIMARY KEY(message_id,model)
);
'''


def initialize(db):
    with db.lock:
        db.conn.executescript(SCHEMA)


def preference(db, user_id, project_id, enabled=None):
    require_project(db, project_id, user_id)
    if enabled is not None:
        db.execute('INSERT INTO memory_preferences VALUES(?,?,?) '
                   'ON CONFLICT(user_id,project_id) DO UPDATE SET enabled=excluded.enabled',
                   (user_id, project_id, int(enabled)))
    row = db.one('SELECT enabled FROM memory_preferences WHERE user_id=? AND project_id=?',
                 (user_id, project_id))
    return {'enabled': bool(row and row['enabled']), 'backend': 'ollama_local',
            'model': os.environ.get('CENTRAL_EMBEDDING_MODEL', 'nomic-embed-text')}


def embed(texts):
    endpoint = os.environ.get('CENTRAL_EMBEDDING_URL', 'http://127.0.0.1:11434')
    parsed = urlsplit(endpoint)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise ValueError('Embedding endpoint must be a local Ollama origin')
    model = os.environ.get('CENTRAL_EMBEDDING_MODEL', 'nomic-embed-text')
    with httpx.Client(timeout=8, trust_env=False, follow_redirects=False) as client:
        response = client.post(endpoint.rstrip('/') + '/api/embed',
                               json={'model': model, 'input': texts, 'truncate': True})
        response.raise_for_status()
    vectors = response.json()['embeddings']
    if len(vectors) != len(texts):
        raise ValueError('Embedding batch size mismatch')
    for vector in vectors:
        if (not isinstance(vector, list) or not 1 <= len(vector) <= 8192
                or any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in vector)):
            raise ValueError('Invalid embedding')
    return vectors


def cosine(a, b):
    if len(a) != len(b):
        return 0.0
    denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0.0


def retrieve(db, user_id, project_id, conversation_id, query):
    if not preference(db, user_id, project_id)['enabled']:
        return []
    model = os.environ.get('CENTRAL_EMBEDDING_MODEL', 'nomic-embed-text')
    rows = db.all('''SELECT m.id,m.content,m.role,m.conversation_id,c.title
        FROM messages m JOIN conversations c ON c.id=m.conversation_id
        WHERE m.user_id=? AND c.user_id=? AND c.project_id=? AND c.id<>?
          AND m.role IN ('user','assistant') ORDER BY m.rowid DESC LIMIT 120''',
                  (user_id, user_id, project_id, conversation_id))
    if not rows:
        return []
    # At most one small batch per recall; cached content is invalidated by hash.
    missing, vectors = [], {}
    for row in rows:
        content = row['content'][:1800]
        digest = hashlib.sha256(content.encode()).hexdigest()
        row['fingerprint'] = digest
        cached = db.one('SELECT vector_json FROM memory_embeddings '
                        'WHERE message_id=? AND model=? AND fingerprint=?',
                        (row['id'], model, digest))
        if cached:
            vectors[row['id']] = json.loads(cached['vector_json'])
        elif len(missing) < 16:
            missing.append(row)
    try:
        batch = embed([query[:1800]] + [r['content'][:1800] for r in missing])
        for row, vector in zip(missing, batch[1:]):
            db.execute('INSERT INTO memory_embeddings VALUES(?,?,?,?,?) '
                       'ON CONFLICT(message_id,model) DO UPDATE SET '
                       'fingerprint=excluded.fingerprint,vector_json=excluded.vector_json,'
                       'updated_at=excluded.updated_at',
                       (row['id'], model, row['fingerprint'], json.dumps(vector), utcnow()))
            vectors[row['id']] = vector
        ranked = [(cosine(batch[0], vectors[r['id']]), r) for r in rows if r['id'] in vectors]
        ranked.sort(key=lambda x: -x[0])
        # Recheck authorization after a potentially slow provider request.
        require_project(db, project_id, user_id)
        return [dict(conversation_id=r['conversation_id'], title=r['title'][:140],
                     role=r['role'], content=r['content'][:800], retrieval='semantic',
                     score=round(score, 4)) for score, r in ranked[:4] if score >= .35]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # Optional local service unavailable: the caller retains lexical recall.
        return []
