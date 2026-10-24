"""Local folder access policy and narrowly scoped, user-approved file previews.

This is NOT remote desktop control and does not equip an LLM with filesystem tools.
Future tools must call request_action before accessing the folder.  Default: blocked.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import HTTPException

ALLOWED_MODES = {'blocked', 'ask', 'full'}
ALLOWED_ACTIONS = {'list', 'read'}
MAX_READ_BYTES = 65536
MAX_LIST_ITEMS = 150
RESTRICTED_NAMES = {
    '.git', '.ssh', '.aws', '.azure', '.gnupg', '.env', '.venv', 'node_modules',
    'secret.key', 'id_rsa', 'id_ed25519', 'credentials', 'credentials.json',
    'central.sqlite3', 'central.sqlite3-wal', 'central.sqlite3-shm'
}
TEXT_EXTENSIONS = {
    '.txt', '.md', '.py', '.js', '.jsx', '.ts', '.tsx', '.json', '.yaml',
    '.yml', '.toml', '.ini', '.cfg', '.css', '.html', '.xml', '.sql', '.csv',
    '.bat', '.ps1', '.sh', '.go', '.rs', '.java', '.c', '.h', '.cpp'
}


def local_only(request):
    """Never offer host filesystem endpoints to remotely connected browsers."""
    host = (request.client.host if request.client else '') or ''
    if host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, 'Acesso à pasta disponível apenas no computador local.')


def policy(db, user_id):
    row = db.one('SELECT mode,folder FROM computer_access_settings WHERE user_id=?',
                 (user_id,))
    return row or {'mode': 'blocked', 'folder': ''}


def allowed_folder(folder):
    if not isinstance(folder, str) or not folder.strip() or len(folder) > 1024:
        raise HTTPException(422, 'Informe o caminho completo de uma pasta.')
    path = Path(folder.strip()).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise HTTPException(422, 'A pasta precisa existir neste computador e ter um caminho absoluto.')
    try:
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise HTTPException(422, 'Não use atalhos, links ou junções como pasta autorizada.')
        real = path.resolve(strict=True)
        home = Path.home().resolve()
        if real == Path(real.anchor) or real == home:
            raise HTTPException(422, 'Escolha uma pasta específica, não a unidade inteira ou sua pasta de usuário.')
        if not os.access(real, os.R_OK):
            raise HTTPException(422, 'A pasta não está acessível para leitura.')
        return str(real)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(422, 'Não foi possível validar essa pasta.') from exc


def set_policy(db, user_id, mode, folder):
    if mode not in ALLOWED_MODES:
        raise HTTPException(422, 'Modo de acesso inválido.')
    validated = allowed_folder(folder) if mode != 'blocked' else ''
    from .database import utcnow
    db.execute('''INSERT INTO computer_access_settings(user_id,mode,folder,updated_at)
                  VALUES(?,?,?,?)
                  ON CONFLICT(user_id) DO UPDATE SET
                  mode=excluded.mode,folder=excluded.folder,updated_at=excluded.updated_at''',
               (user_id, mode, validated, utcnow()))
    # Cancel old approvals whenever the mode, path or permissions change.
    db.execute("DELETE FROM computer_access_approvals WHERE user_id=?", (user_id,))
    return policy(db, user_id)


def scoped_path(folder, relative, allow_root=False):
    if not folder:
        raise HTTPException(403, 'Nenhuma pasta autorizada.')
    if not isinstance(relative, str) or len(relative) > 300 or '\\' in relative or '\x00' in relative:
        raise HTTPException(422, 'Caminho relativo inválido.')
    # Relative paths use / separators on every platform.
    parts = relative.split('/')
    if relative in ('', '.'):
        parts = []
    elif any(x in ('', '.', '..') for x in parts) or ':' in relative or relative.startswith('/'):
        raise HTTPException(422, 'Use apenas um caminho relativo dentro da pasta autorizada.')
    if not parts and not allow_root:
        raise HTTPException(422, 'Selecione um arquivo para leitura.')
    if any(p.lower() in RESTRICTED_NAMES or p.lower().startswith('.env') for p in parts):
        raise HTTPException(403, 'Arquivos de credenciais e dependências internas não podem ser acessados.')
    root = Path(folder).resolve(strict=True)
    current = root
    try:
        for part in parts:
            current = current / part
            if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
                raise HTTPException(403, 'Links simbólicos e junções não são permitidos.')
        resolved = current.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise HTTPException(403, 'O arquivo está fora da pasta autorizada.')
        return resolved
    except (OSError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(404, 'Arquivo ou pasta não encontrado.') from exc


def inspect(folder, action, relative):
    path = scoped_path(folder, relative, allow_root=action == 'list')
    if action == 'list':
        if not path.is_dir():
            raise HTTPException(422, 'Selecione uma pasta para listar.')
        items = []
        try:
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if len(items) >= MAX_LIST_ITEMS:
                    break
                if child.name.lower() in RESTRICTED_NAMES or child.name.lower().startswith('.env'):
                    continue
                if child.is_symlink() or (hasattr(child, 'is_junction') and child.is_junction()):
                    continue
                items.append({'name': child.name, 'type': 'folder' if child.is_dir() else 'file'})
        except OSError as exc:
            raise HTTPException(403, 'Sem permissão do Windows para listar esta pasta.') from exc
        return {'action': 'list', 'path': relative, 'items': items}
    if action != 'read':
        raise HTTPException(422, 'Ação não suportada.')
    if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
        raise HTTPException(422, 'A visualização suporta somente arquivos de texto/código.')
    try:
        with path.open('rb') as file:
            raw = file.read(MAX_READ_BYTES + 1)
        if len(raw) > MAX_READ_BYTES or b'\x00' in raw:
            raise HTTPException(413, 'Arquivo grande demais ou não textual para visualização.')
        text = raw.decode('utf-8')
    except UnicodeError as exc:
        raise HTTPException(422, 'O arquivo não está codificado em UTF-8.') from exc
    except OSError as exc:
        raise HTTPException(403, 'Sem permissão do Windows para ler este arquivo.') from exc
    return {'action': 'read', 'path': relative, 'content': text}


def request_action(db, user_id, action, relative):
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(422, 'Somente visualização de pastas e arquivos está disponível nesta versão.')
    config = policy(db, user_id)
    if config['mode'] == 'blocked':
        raise HTTPException(403, 'Acesso ao computador bloqueado. Altere as permissões primeiro.')
    if not config['folder'] or not Path(config['folder']).is_dir():
        raise HTTPException(409, 'A pasta autorizada não está mais disponível.')
    # Check the path before issuing approval, and check it again upon approval.
    scoped_path(config['folder'], relative, allow_root=action == 'list')
    if config['mode'] == 'full':
        return {'status': 'completed', 'result': inspect(config['folder'], action, relative)}
    from .database import utcnow
    req_id = secrets.token_urlsafe(24)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db.execute('''INSERT INTO computer_access_approvals
                  (id,user_id,action,relative_path,folder,expires_at,created_at)
                  VALUES(?,?,?,?,?,?,?)''',
               (req_id, user_id, action, relative, config['folder'], expires_at, utcnow()))
    return {'status': 'approval_required', 'request_id': req_id,
            'action': action, 'path': relative}


def decide_action(db, user_id, request_id, approve):
    entry = db.one(
        'SELECT * FROM computer_access_approvals WHERE id=? AND user_id=?',
        (request_id, user_id))
    if not entry or entry['status'] != 'pending':
        raise HTTPException(404, 'Solicitação inexistente ou já processada.')
    current = policy(db, user_id)
    # A permission change or expiry automatically invalidates earlier requests.
    if (current['mode'] != 'ask' or current['folder'] != entry['folder'] or
            datetime.fromisoformat(entry['expires_at']) <= datetime.now(timezone.utc)):
        db.execute("UPDATE computer_access_approvals SET status='expired' WHERE id=?", (request_id,))
        raise HTTPException(409, 'Solicitação expirada ou permissões alteradas.')
    db.execute('UPDATE computer_access_approvals SET status=? WHERE id=? AND status=?',
               ('approved' if approve else 'denied', request_id, 'pending'))
    if not approve:
        return {'status': 'denied'}
    return {'status': 'completed', 'result': inspect(entry['folder'], entry['action'],
                                                     entry['relative_path'])}
