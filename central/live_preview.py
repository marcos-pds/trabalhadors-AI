"""Explicit, local-only live browser previews for authorized Vite-like projects.

Preview is an opt-in long-running npm dev command and is not an isolation boundary.
Never bind a remote interface or accept arbitrary shell arguments from a model.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from fastapi import HTTPException

from .computer_access import allowed_folder, policy
from .workspace_tools import target, _kill_tree

_LOCK = threading.RLock()
_SESSIONS = {}
_SKIP = {'.git', '.venv', 'node_modules', '.next', '.turbo', 'dist', 'build', 'coverage'}


def candidates(folder):
    root = Path(allowed_folder(folder))
    found = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        path = Path(directory)
        depth = len(path.relative_to(root).parts)
        dirs[:] = [d for d in dirs if d not in _SKIP
                   and not (path / d).is_symlink()
                   and not (hasattr(path / d, 'is_junction') and (path / d).is_junction())]
        if depth >= 4:
            dirs.clear()
        if 'package.json' not in files:
            continue
        try:
            info = json.loads((path / 'package.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(info.get('scripts'), dict) and isinstance(info['scripts'].get('dev'), str):
            found.append({'cwd': path.relative_to(root).as_posix() if path != root else '',
                          'name': str(info.get('name') or path.name)[:70]})
        if len(found) == 20:
            break
    return found


def _port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _alive(entry):
    return entry is not None and entry['process'].poll() is None


def info(user_id):
    with _LOCK:
        entry = _SESSIONS.get(user_id)
        if not _alive(entry):
            _SESSIONS.pop(user_id, None)
            return {'status': 'stopped'}
        return {'status': 'running', 'cwd': entry['cwd'],
                'url': 'http://127.0.0.1:' + str(entry['port']) + '/',
                'port': entry['port']}


def stop(user_id):
    with _LOCK:
        entry = _SESSIONS.pop(user_id, None)
    if entry:
        _kill_tree(entry['process'])
    return {'status': 'stopped'}


def stop_all():
    with _LOCK:
        users = list(_SESSIONS)
    for user in users:
        stop(user)


def start(db, user_id, relative):
    permission = policy(db, user_id)
    if permission['mode'] not in ('full', 'ask'):
        raise HTTPException(403, 'Escolha uma pasta autorizada no botão Computador.')
    folder = allowed_folder(permission['folder'])
    available = candidates(folder)
    if relative not in [item['cwd'] for item in available]:
        raise HTTPException(422, 'Escolha um projeto com script npm dev listado dentro da pasta autorizada.')
    directory = target(folder, relative, directory=True)
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise HTTPException(422, 'npm não encontrado. Instale Node.js neste computador.')
    with _LOCK:
        previous = _SESSIONS.get(user_id)
        if _alive(previous):
            if previous['cwd'] == relative and previous['folder'] == folder:
                return info(user_id)
            raise HTTPException(409, 'Pare a prévia atual antes de iniciar outra.')
    port = _port()
    # npm scripts execute third-party code with the local Windows user's privileges.
    # The UI asks for explicit preview startup confirmation.
    args = [npm, 'run', 'dev', '--', '--host', '127.0.0.1',
            '--port', str(port), '--strictPort']
    try:
        log = subprocess.DEVNULL
        process = subprocess.Popen(
            args, cwd=directory, stdout=log, stderr=log, shell=False,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0),
            start_new_session=(os.name != 'nt'),
            env=dict(os.environ, BROWSER='none', HOST='127.0.0.1'))
    except OSError as exc:
        raise HTTPException(422, 'Falha ao iniciar a prévia: ' + str(exc)[:200]) from exc
    with _LOCK:
        _SESSIONS[user_id] = {'process': process, 'port': port,
                              'folder': folder, 'cwd': relative}
    # The server might compile on first request; don't claim it is ready yet.
    for _ in range(24):
        if process.poll() is not None:
            stop(user_id)
            raise HTTPException(422, 'O servidor de prévia encerrou. Verifique o script npm dev e as dependências.')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return info(user_id)
        except OSError:
            time.sleep(0.25)
    stop(user_id)
    raise HTTPException(504, 'A prévia não iniciou na porta local em 6 segundos. Verifique as dependências.')
