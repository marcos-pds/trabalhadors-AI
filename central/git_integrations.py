"""Read-only GitHub/GitLab reviews with per-user encrypted credentials.

No arbitrary URLs, redirects, remote writes, push, merge or deployment actions.
"""
import re
from urllib.parse import quote
import httpx
from fastapi import HTTPException
from .database import uid, utcnow

SCHEMA = '''CREATE TABLE IF NOT EXISTS git_connections (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 service TEXT NOT NULL CHECK(service IN ('github','gitlab')),
 repository TEXT NOT NULL, token_enc TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(user_id,service,repository)
)'''
REPOSITORY = re.compile(r'^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){1,5}$')


def connect(db, security, user_id, service, repository, token):
    if (service not in ('github', 'gitlab') or not REPOSITORY.fullmatch(repository)
            or any(segment in ('.', '..') for segment in repository.split('/'))
            or (service == 'github' and repository.count('/') != 1)):
        raise HTTPException(422, 'Serviço ou caminho do repositório inválido.')
    if not token or len(token) > 4096 or any(c.isspace() for c in token):
        raise HTTPException(422, 'Token inválido.')
    identifier = uid()
    db.execute('INSERT INTO git_connections VALUES(?,?,?,?,?,?) '
               'ON CONFLICT(user_id,service,repository) DO UPDATE SET token_enc=excluded.token_enc',
               (identifier, user_id, service, repository, security.encrypt(token), utcnow()))
    return db.one('SELECT id,service,repository,created_at FROM git_connections '
                   'WHERE user_id=? AND service=? AND repository=?', (user_id, service, repository))


def connections(db, user_id):
    return db.all('SELECT id,service,repository,created_at FROM git_connections WHERE user_id=?', (user_id,))


def reviews(db, security, user_id, connection_id, number=None, transport=None):
    row = db.one('SELECT * FROM git_connections WHERE id=? AND user_id=?', (connection_id, user_id))
    if not row:
        raise HTTPException(404, 'Conexão não encontrada.')
    if number is not None and (not isinstance(number, int) or not 1 <= number <= 2147483647):
        raise HTTPException(422, 'Número de revisão inválido.')
    token = security.decrypt(row['token_enc'])
    github = row['service'] == 'github'
    if github:
        url = 'https://api.github.com/repos/' + row['repository'] + '/pulls'
        url += '/' + str(number) + '/files?per_page=100' if number else '?state=open&per_page=20'
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
    else:
        url = 'https://gitlab.com/api/v4/projects/' + quote(row['repository'], safe='') + '/merge_requests'
        url += '/' + str(number) + '/diffs?per_page=100' if number else '?state=opened&per_page=20'
        headers = {'PRIVATE-TOKEN': token}
    try:
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False, transport=transport) as client:
            # Bounded streaming: don't hold arbitrarily large remote responses.
            with client.stream('GET', url, headers=headers) as response:
                if response.status_code != 200:
                    raise HTTPException(502, 'Serviço Git recusou a consulta; verifique token e permissões.')
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise HTTPException(413, 'Resposta Git excedeu o limite de 2 MB.')
                import json
                data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError('Expected list')
        if number:
            items = [{'path': str(item.get('filename' if github else 'new_path', ''))[:500],
                      'status': str(item.get('status', 'modified'))[:30],
                      'patch': str(item.get('patch' if github else 'diff', ''))[:12000]}
                     for item in data[:100]]
        else:
            items = [{'number': item.get('number' if github else 'iid'),
                      'title': str(item.get('title', ''))[:300],
                      'state': str(item.get('state', ''))[:30]}
                     for item in data[:20]]
        return {'service': row['service'], 'repository': row['repository'],
                'items': items, 'pagination_notice': 'Primeira página; diffs podem estar truncados.',
                'read_only': True}
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(502, 'Não foi possível consultar o serviço Git.') from exc
