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
    def __init__(self, row, security, transport=None, repository=None):
        stored_repository = row['repository']
        self.github = row['service'] == 'github'
        self.account_scope = self.github and stored_repository == '*'
        if row['service'] not in ('github', 'gitlab') or (stored_repository == '*' and not self.github):
            raise HTTPException(422, 'Conexão Git inválida.')
        if repository is not None:
            if (not REPOSITORY.fullmatch(repository)
                    or any(part in ('.', '..') for part in repository.split('/'))
                    or (self.github and repository.count('/') != 1)):
                raise HTTPException(422, 'Repositório Git inválido.')
            if not self.account_scope and repository.casefold() != stored_repository.casefold():
                raise HTTPException(422, 'O repositório não corresponde à conexão salva.')
        target_repository = repository or (None if self.account_scope else stored_repository)
        if not self.account_scope and (not REPOSITORY.fullmatch(stored_repository)
                or any(part in ('.', '..') for part in stored_repository.split('/'))
                or (self.github and stored_repository.count('/') != 1)):
            raise HTTPException(422, 'Conexão Git inválida.')
        self.repository = target_repository or stored_repository
        token = security.decrypt(row['token_enc'])
        self.base = ('https://api.github.com' if self.github and target_repository is None else
                     'https://api.github.com/repos/' + target_repository if self.github else
                     'https://gitlab.com/api/v4/projects/' + quote(target_repository, safe=''))
        self.headers = ({'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
                        if self.github else {'PRIVATE-TOKEN': token})
        self.transport = transport

    def request(self, method, suffix, payload=None):
        if (method not in ('GET', 'POST') or (suffix and not suffix.startswith('/'))
                or suffix.startswith('//') or (not suffix and method != 'GET')):
            raise ValueError('Invalid internal Git operation')
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False,
                          transport=self.transport) as client:
            with client.stream(method, self.base + suffix, headers=self.headers, json=payload) as response:
                if not 200 <= response.status_code < 300:
                    raise RemoteRejected(response.status_code)
                raw = bytearray()
                limit = 8 * 1024 * 1024 if '/git/trees/' in suffix and 'recursive=1' in suffix else 2 * 1024 * 1024
                for chunk in response.iter_bytes(65536):
                    raw.extend(chunk)
                    if len(raw) > limit:
                        raise ValueError('Git response exceeds limit')
                return json.loads(raw), dict(response.headers)

    def branch_sha(self, branch):
        if self.account_scope and self.repository == '*':
            raise HTTPException(422, 'Selecione um repositório antes de consultar branches.')
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
