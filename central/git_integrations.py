"""Paginated GitHub/GitLab review reads with per-user encrypted credentials.

Draft writes are separate, immutable single-use plans in git_change_plans.
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


def reviews(db, security, user_id, connection_id, number=None, transport=None, page=1):
    from .git_gateway import Gateway, RemoteRejected, connection
    row = connection(db, user_id, connection_id)
    if number is not None and (type(number) is not int or not 1 <= number <= 2147483647):
        raise HTTPException(422, 'Número de revisão inválido.')
    if type(page) is not int or not 1 <= page <= 100:
        raise HTTPException(422, 'Página deve estar entre 1 e 100.')
    gateway = Gateway(row, security, transport)
    suffix = '/pulls' if gateway.github else '/merge_requests'
    if number:
        suffix += '/' + str(number) + ('/files' if gateway.github else '/diffs') + '?per_page=100'
    else:
        suffix += '?state=' + ('open' if gateway.github else 'opened') + '&per_page=20'
    suffix += '&page=' + str(page)
    try:
        data, headers = gateway.request('GET', suffix)
        if not isinstance(data, list):
            raise ValueError('Expected list')
        if number:
            items = [{'path': str(item.get('filename' if gateway.github else 'new_path', ''))[:500],
                      'status': str(item.get('status', 'modified'))[:30],
                      'patch': str(item.get('patch' if gateway.github else 'diff') or '')[:12000],
                      'truncated': (len(str(item.get('patch' if gateway.github else 'diff') or '')) > 12000
                                    or bool(item.get('too_large') or item.get('collapsed')))}
                     for item in data[:100]]
        else:
            items = [{'number': item.get('number' if gateway.github else 'iid'),
                      'title': str(item.get('title', ''))[:300],
                      'state': str(item.get('state', ''))[:30]}
                     for item in data[:20]]
        has_next = ('rel="next"' in headers.get('link', '') if gateway.github else
                    headers.get('x-next-page') == str(page + 1))
        return {'service': row['service'], 'repository': row['repository'], 'items': items,
                'page': page, 'previous_page': page - 1 if page > 1 else None,
                'next_page': page + 1 if has_next and page < 100 else None,
                'pagination_notice': 'Página ' + str(page) + '; diffs podem estar truncados pelo serviço.',
                'read_only': True}
    except (httpx.HTTPError, RemoteRejected, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(502, 'Não foi possível consultar o serviço Git.') from exc
