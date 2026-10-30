"""Explicit, local-only live browser previews for authorized Vite-like projects.

Preview is an opt-in long-running npm dev command and is not an isolation boundary.
Never bind a remote interface or accept arbitrary shell arguments from a model.
"""
import json
import os
import re
import select
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from fastapi import HTTPException

from .computer_access import allowed_folder, policy
from .workspace_tools import target, _kill_tree
from .sandbox_executor import backend
from . import docker_preview

_LOCK = threading.RLock()
_SESSIONS = {}
_SKIP = {'.git', '.venv', 'node_modules', '.next', '.turbo', 'dist', 'build', 'coverage'}


_LOG_BYTES = 8192
_LOG_PREVIEW = 4000
_ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))')


class _PreviewLogs:
    """One draining reader, bounded byte tail, and interruptible pipe polling."""

    def __init__(self, process):
        self.process = process
        self.pipe = process.stdout
        self.tail = bytearray()
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True,
                                       name='central-preview-logs')
        self.thread.start()

    def _available(self, fd):
        if os.name == 'nt':
            # select() only supports sockets on Windows. PeekNamedPipe never
            # blocks, even when a descendant keeps stdout open after npm exits.
            import ctypes
            from ctypes import wintypes
            import msvcrt
            available = wintypes.DWORD()
            peek = ctypes.windll.kernel32.PeekNamedPipe
            peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                             wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
            peek.restype = wintypes.BOOL
            if not peek(msvcrt.get_osfhandle(fd), None, 0, None,
                        ctypes.byref(available), None):
                return -1
            return min(available.value, 4096)
        return 4096 if select.select([fd], [], [], 0)[0] else 0

    def _read(self):
        try:
            fd = self.pipe.fileno()
            while True:
                size = self._available(fd)
                if size < 0:
                    break
                if size:
                    chunk = os.read(fd, size)
                    if not chunk:
                        break
                    with self.lock:
                        self.tail.extend(chunk)
                        del self.tail[:-_LOG_BYTES]
                    if self.stopping.is_set():
                        break
                elif self.stopping.is_set() or self.process.poll() is not None:
                    break
                else:
                    self.stopping.wait(.025)
        except (OSError, ValueError):
            pass  # closed/broken pipe during concurrent shutdown
        finally:
            self.pipe.close()

    def recent(self):
        with self.lock:
            text = bytes(self.tail).decode('utf-8', errors='replace')
        text = _ANSI.sub('', text)
        text = ''.join(c for c in text if c in '\n\t' or (c.isprintable() and c != '\x7f'))
        return text[-_LOG_PREVIEW:]

    def close(self):
        self.stopping.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=1)


def _recent_logs(entry):
    logs = entry.get('logs')
    return logs.recent() if logs else ''


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


def info(user_id, expected=None, *, include_logs=False):
    with _LOCK:
        entry = _SESSIONS.get(user_id)
        if expected is not None and entry is not expected:
            return {'status': 'stopped'}
        if entry and entry.get('authorized') and not entry['authorized']():
            stop(user_id, expected=entry)
            return {'status': 'stopped'}
        if not _alive(entry):
            if entry and entry.get('logs'):
                entry['logs'].thread.join(timeout=.5)
            result = {'status': 'stopped'}
            if entry and include_logs is True:
                result['recent_logs'] = _recent_logs(entry)
            stop(user_id, expected=entry)
            return result
        result = {'status': 'running', 'cwd': entry['cwd'], 'folder': entry['folder'],
                  'backend': entry.get('backend', 'host'),
                  'url': 'http://127.0.0.1:' + str(entry['port']) + entry.get('prefix', '/'),
                  'port': entry['port']}
        if include_logs is True:
            result['recent_logs'] = _recent_logs(entry)
        return result


def stop(user_id, expected=None):
    with _LOCK:
        if expected is not None and _SESSIONS.get(user_id) is not expected:
            return {'status': 'stopped'}
        entry = _SESSIONS.pop(user_id, None)
    if entry:
        if entry.get('timer'):
            entry['timer'].cancel()
        if entry.get('container'):
            docker_preview.cleanup(entry)
        try:
            _kill_tree(entry['process'])
        finally:
            if entry.get('logs'):
                entry['logs'].close()
    return {'status': 'stopped'}


def stop_all():
    with _LOCK:
        users = list(_SESSIONS)
    for user in users:
        stop(user)


def _environment():
    # npm scripts must not inherit API keys, DB settings, NODE_OPTIONS or tokens.
    names = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
             'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'LANG', 'LC_ALL'}
    env = {key: value for key, value in os.environ.items() if key.upper() in names}
    env.update(BROWSER='none', HOST='127.0.0.1')
    return env


def start(db, user_id, relative, *, owner=None, authorize=None, expected_folder=None):
    permission = policy(db, user_id)
    if permission['mode'] not in ('full', 'ask'):
        raise HTTPException(403, 'Autorize uma pasta no Computador.')
    folder = allowed_folder(permission['folder'])
    if expected_folder is not None and folder != expected_folder:
        # A server-resolved isolated step may run below the original grant.
        # UI callers cannot select this root or supply their own authorizer.
        if owner is None or authorize is None or not authorize():
            raise HTTPException(409, 'O workspace autorizado mudou.')
        candidate = allowed_folder(expected_folder)
        if not Path(candidate).is_relative_to(Path(folder)):
            raise HTTPException(403, 'A prévia isolada está fora da pasta original.')
        folder = candidate
    if relative not in [item['cwd'] for item in candidates(folder)]:
        raise HTTPException(422, 'Escolha um projeto com script npm dev na pasta autorizada.')
    directory = target(folder, relative, directory=True)
    runner = backend()
    npm = 'npm' if runner == 'docker' else shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise HTTPException(422, 'npm nao encontrado. Instale Node.js.')

    def authorized():
        try:
            return policy(db, user_id) == permission and (authorize is None or bool(authorize()))
        except Exception:
            return False

    with _LOCK:
        if not authorized():
            raise HTTPException(403, 'Autorizacao da previa revogada.')
        previous = _SESSIONS.get(user_id)
        if _alive(previous):
            if (previous.get('owner') == owner and previous['cwd'] == relative
                    and previous['folder'] == folder
                    and previous.get('backend', 'host') == runner):
                return info(user_id, expected=previous)
            raise HTTPException(409, 'Pare a previa atual antes de iniciar outra.')
        if previous:
            stop(user_id, expected=previous)
        if len(_SESSIONS) >= 4:
            raise HTTPException(429, 'Limite de quatro previas simultaneas atingido.')
        if runner == 'docker':
            entry = docker_preview.start(directory, authorized)
        else:
            port = _port()
            args = [npm, 'run', 'dev', '--', '--host', '127.0.0.1',
                    '--port', str(port), '--strictPort']
            try:
                process = subprocess.Popen(
                    args, cwd=directory, stdout=subprocess.PIPE, bufsize=0,
                    stderr=subprocess.STDOUT, shell=False,
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0),
                    start_new_session=(os.name != 'nt'), env=_environment())
            except OSError as exc:
                raise HTTPException(422, 'Falha ao iniciar a previa: ' + str(exc)[:200]) from exc
            entry = {'process': process, 'port': port}
            if getattr(process, 'stdout', None) is not None:
                entry['logs'] = _PreviewLogs(process)
        entry.update(folder=folder, cwd=relative, backend=runner,
                     authorized=authorized, owner=owner)
        _SESSIONS[user_id] = entry
        timer = threading.Timer(1800, stop, args=(user_id, entry))
        timer.daemon = True
        entry['timer'] = timer
        timer.start()

    # Creation is serialized for both backends; readiness never holds the lock.
    try:
        for _ in range(24):
            with _LOCK:
                if _SESSIONS.get(user_id) is not entry:
                    raise HTTPException(409, 'Previa substituida ou encerrada.')
            if not authorized():
                raise HTTPException(403, 'Autorizacao da previa revogada.')
            if entry['process'].poll() is not None:
                raise HTTPException(422, 'O servidor de previa encerrou. Verifique npm dev e dependencias.')
            try:
                if runner == 'docker':
                    check = subprocess.run(
                        [shutil.which('docker.exe' if os.name == 'nt' else 'docker'),
                         'exec', entry['container'], 'python3', '-c',
                         'import socket;s=socket.create_connection(("127.0.0.1",4173),1);s.close()'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    ready = check.returncode == 0
                else:
                    with socket.create_connection(('127.0.0.1', entry['port']), timeout=.2):
                        ready = True
                if ready:
                    result = info(user_id, expected=entry)
                    if result['status'] != 'running':
                        raise HTTPException(409, 'Previa encerrada durante inicializacao.')
                    return result
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(.25)
        raise HTTPException(504, 'A previa nao iniciou; verifique as dependencias.')
    except BaseException as exc:
        # Only startup diagnostics, never output on a denied/revoked request.
        if isinstance(exc, HTTPException) and exc.status_code in (422, 504):
            logs = entry.get('logs')
            if logs and entry['process'].poll() is not None:
                logs.thread.join(timeout=.5)
            tail = _recent_logs(entry)
            if tail and authorized():
                exc.detail = str(exc.detail) + '\nSaida recente de npm dev:\n' + tail
        stop(user_id, expected=entry)
        raise
