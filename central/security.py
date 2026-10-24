import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, status
from .database import uid, utcnow


def password_hash(password: str):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f'{salt.hex()}:{digest.hex()}'


def verify_password(password: str, stored: str):
    try:
        salt, correct = stored.split(':')
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest, bytes.fromhex(correct))
    except (ValueError, TypeError):
        return False


class Security:
    def __init__(self, db, data_dir):
        self.db = db
        keyfile = Path(data_dir) / 'secret.key'
        if not keyfile.exists():
            try:
                with keyfile.open('xb') as f:
                    f.write(Fernet.generate_key())
                os.chmod(keyfile, 0o600)
            except FileExistsError:
                pass
        self.fernet = Fernet(keyfile.read_bytes())

    def encrypt(self, value):
        return self.fernet.encrypt(value.encode()).decode() if value else None

    def decrypt(self, value):
        return self.fernet.decrypt(value.encode()).decode() if value else ''

    def create_session(self, user_id):
        token = secrets.token_urlsafe(48)
        h = hashlib.sha256(token.encode()).hexdigest()
        expiry = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        self.db.execute('INSERT INTO sessions VALUES(?,?,?)', (h, user_id, expiry))
        return token

    def user(self, request: Request):
        token = request.cookies.get('central_session')
        if not token:
            raise HTTPException(status_code=401, detail='Faça login para continuar.')
        h = hashlib.sha256(token.encode()).hexdigest()
        row = self.db.one('''SELECT u.id,u.email FROM sessions s JOIN users u ON u.id=s.user_id
          WHERE s.token_hash=? AND s.expires_at>?''', (h, utcnow()))
        if not row:
            raise HTTPException(status_code=401, detail='Sessão expirada. Faça login novamente.')
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            if request.headers.get('x-central-request') != '1':
                raise HTTPException(status_code=403, detail='Cabeçalho de proteção obrigatório.')
            # A browser cannot set this custom header cross-origin without successful CORS preflight.
            origin = request.headers.get('origin')
            if origin:
                from urllib.parse import urlsplit
                o = urlsplit(origin)
                origin_host = (o.hostname or '').lower()
                request_host = (request.url.hostname or '').lower()
                if origin_host != request_host or o.scheme != request.url.scheme:
                    raise HTTPException(status_code=403, detail='Origem não autorizada.')
        return row


def require_owned(db, table, obj_id, user_id):
    if table not in {'providers', 'agents', 'conversations', 'runs', 'workflows', 'projects'}:
        raise ValueError('Invalid table')
    obj = db.one(f'SELECT * FROM {table} WHERE id=? AND user_id=?', (obj_id, user_id))
    if not obj:
        raise HTTPException(404, 'Registro não encontrado.')
    if table == 'projects':
        from .organizations import require_project
        return require_project(db,obj_id,user_id)
    if table == 'conversations':
        from .organizations import require_conversation_scope
        return require_conversation_scope(db,obj,user_id)
    if table == 'runs':
        from .organizations import require_run_scope
        return require_run_scope(db,obj,user_id)
    return obj
