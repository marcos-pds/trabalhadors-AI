"""Bounded Git REST transport with fixed origins and no redirect/retry writes."""
import json
import re
from urllib.parse import quote
import httpx
from fastapi import HTTPException
from .git_integrations import REPOSITORY


class RemoteRejected(Exception):
    def __init__(self, status):
        self.status = status


class Gateway:
    def __init__(self, row, security, transport=None):
        repository = row['repository']
        self.github = row['service'] == 'github'
        if (row['service'] not in ('github', 'gitlab') or not REPOSITORY.fullmatch(repository)
                or any(part in ('.', '..') for part in repository.split('/'))
                or (self.github and repository.count('/') != 1)):
            raise HTTPException(422, 'Conexão Git inválida.')
        token = security.decrypt(row['token_enc'])
        self.base = ('https://api.github.com/repos/' + repository if self.github else
                     'https://gitlab.com/api/v4/projects/' + quote(repository, safe=''))
        self.headers = ({'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
                        if self.github else {'PRIVATE-TOKEN': token})
        self.transport = transport

    def request(self, method, suffix, payload=None):
        if method not in ('GET', 'POST') or not suffix.startswith('/') or suffix.startswith('//'):
            raise ValueError('Invalid internal Git operation')
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False,
                          transport=self.transport) as client:
            with client.stream(method, self.base + suffix, headers=self.headers, json=payload) as response:
                if not 200 <= response.status_code < 300:
                    raise RemoteRejected(response.status_code)
                raw = bytearray()
                for chunk in response.iter_bytes(65536):
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError('Git response exceeds 2 MB')
                return json.loads(raw), dict(response.headers)

    def branch_sha(self, branch):
        suffix = ('/branches/' if self.github else '/repository/branches/') + quote(branch, safe='')
        data, _ = self.request('GET', suffix)
        sha = data['commit']['sha' if self.github else 'id']
        if not isinstance(sha, str) or not re.fullmatch(r'[a-fA-F0-9]{40,64}', sha):
            raise ValueError('Invalid branch SHA')
        return sha.lower()


def connection(db, user_id, connection_id):
    row = db.one('SELECT * FROM git_connections WHERE id=? AND user_id=?', (connection_id, user_id))
    if not row:
        raise HTTPException(404, 'Conexão não encontrada.')
    return row
