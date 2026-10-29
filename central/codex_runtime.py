"""Read-only local Codex discovery. No generation, login, or token refresh.

probe(timeout=10, cancel_event=None) is synchronous and safe in sync routes.
Timeout covers the whole protocol; cleanup uses bounded waits.
"""
from collections import deque
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time

_MAX_LINE = 256 * 1024
_MAX_OUTPUT = 2 * 1024 * 1024
_MAX_MESSAGES = 256


class _Failure(Exception):
    pass


def _executable():
    override = os.environ.get('CENTRAL_CODEX_EXECUTABLE')
    value = override if override is not None else shutil.which('codex')
    if not value:
        raise _Failure('not_found')
    path = Path(value)
    if (not path.is_absolute() or not path.is_file()
            or (os.name == 'nt' and path.suffix.lower() != '.exe')
            or (os.name != 'nt' and not os.access(path, os.X_OK))):
        raise _Failure('invalid_executable')
    return str(path)


def inventory():
    """Presence only; never starts or installs a runtime, never returns paths."""
    result = {name: {'present': bool(shutil.which(name))}
              for name in ('claude', 'gemini', 'opencode', 'codex')}
    try:
        _executable()
        result['codex']['present'] = True
    except _Failure:
        result['codex']['present'] = False
    return result


class _Client:
    def __init__(self, command, deadline, cancel_event, *,
                 max_messages=256, max_output=2 * 1024 * 1024, env=None, cwd=None):
        if (type(max_messages) is not int or not 1 <= max_messages <= 20000
                or type(max_output) is not int or not 1 <= max_output <= 32 * 1024 * 1024):
            raise ValueError('invalid client limits')
        self.max_messages = max_messages
        self.max_output = max_output
        self.notifications = deque()
        self.deadline = deadline
        self.cancel_event = cancel_event
        self.events = queue.Queue(maxsize=32)
        self.stop = threading.Event()
        self.failure = None
        self.serial = 0
        options = {}
        if env is not None:
            options['env'] = env
        if cwd is not None:
            options['cwd'] = cwd
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, shell=False, bufsize=0,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            **options)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.outgoing = queue.Queue(maxsize=16)
        self.reader.start()
        self.writer.start()

    def _put(self, value):
        while not self.stop.is_set():
            try:
                self.events.put(value, timeout=.05)
                return
            except queue.Full:
                pass

    def _read(self):
        total = 0
        try:
            for _ in range(self.max_messages):
                line = self.process.stdout.readline(_MAX_LINE + 1)
                total += len(line)
                if len(line) > _MAX_LINE or total > self.max_output:
                    self.failure = 'output_limit'
                    return
                if not line:
                    self.failure = 'disconnected'
                    return
                if not line.endswith(b'\n'):
                    self.failure = 'protocol_error'
                    return
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError()
                self._put(value)
            self.failure = 'output_limit'
        except (ValueError, UnicodeError, OSError):
            self.failure = 'protocol_error'

    def _write(self):
        try:
            while not self.stop.is_set():
                try:
                    value = self.outgoing.get(timeout=.05)
                except queue.Empty:
                    continue
                pending = memoryview(value)
                while pending and not self.stop.is_set():
                    written = self.process.stdin.write(pending)
                    if not written:
                        raise OSError()
                    pending = pending[written:]
                self.process.stdin.flush()
        except (OSError, ValueError):
            self.failure = 'disconnected'

    def check(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise _Failure('cancelled')
        if time.monotonic() >= self.deadline:
            raise _Failure('timeout')

    def send(self, value):
        self.check()
        try:
            self.outgoing.put_nowait((json.dumps(value) + '\n').encode())
        except queue.Full:
            raise _Failure('output_limit') from None

    def _poll_event(self):
        # Read only raw events here: request must never replay its saved notices.
        while True:
            self.check()
            try:
                value = self.events.get(timeout=.025)
            except queue.Empty:
                if self.failure:
                    raise _Failure(self.failure)
                continue
            if 'method' in value and 'id' in value:
                identifier = value['id']
                if type(identifier) not in (str, int) or len(str(identifier)) > 128:
                    raise _Failure('protocol_error')
                self.send({'id': identifier, 'error': {
                    'code': -32601, 'message': 'Client requests are not supported'}})
                continue
            return value

    def next_event(self):
        """Return the next notification, refusing all server requests."""
        self.check()
        if self.notifications:
            return self.notifications.popleft()
        value = self._poll_event()
        if 'id' in value or 'method' not in value:
            raise _Failure('protocol_error')
        return value

    def request(self, method, params):
        self.serial += 1
        request_id = self.serial
        self.send({'id': request_id, 'method': method, 'params': params})
        while True:
            value = self._poll_event()
            if 'method' in value:
                if len(self.notifications) >= self.max_messages:
                    raise _Failure('output_limit')
                self.notifications.append(value)
                continue
            if type(value.get('id')) is not int or value['id'] != request_id:
                raise _Failure('protocol_error')
            if 'error' in value:
                raise _Failure('rpc_error')
            result = value.get('result')
            if not isinstance(result, dict):
                raise _Failure('protocol_error')
            return result

    def close(self):
        self.stop.set()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=1)
        self.reader.join(timeout=.25)
        self.writer.join(timeout=.25)
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()


def _label(value):
    # Do not accept paths, email addresses, tokens, or arbitrary diagnostic text.
    if (isinstance(value, str) and 0 < len(value) <= 128
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._()+:-]*', value)
            and not re.search(r'(?:sk-|token|secret|bearer)', value, re.I)):
        return value
    return None


def probe(timeout=10.0, cancel_event=None):
    """Return safe discovery fields plus status; never expose raw server data.

    Status is ok, server_mode_refused, invalid_timeout, not_found,
    invalid_executable, cancelled, timeout, output_limit, disconnected,
    protocol_error, rpc_error, or unavailable. Models are discovery only.
    """
    safe = {'authenticated': False, 'auth_type': None, 'version': None, 'models': []}
    if os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local') != 'local':
        return dict(safe, status='server_mode_refused')
    if (isinstance(timeout, bool) or not isinstance(timeout, (float, int))
            or not math.isfinite(timeout) or not 0 < timeout <= 60):
        return dict(safe, status='invalid_timeout')
    client = None
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise _Failure('cancelled')
        executable = _executable()
        client = _Client([executable, 'app-server'], time.monotonic() + timeout, cancel_event)
        initialized = client.request('initialize', {
            'clientInfo': {'name': 'central_discovery', 'version': '1.0.0'}})
        client.send({'method': 'initialized', 'params': {}})
        account = client.request('account/read', {'refreshToken': False}).get('account')
        models = client.request('model/list', {'limit': 100})
        auth_type = account.get('type') if isinstance(account, dict) else None
        safe['authenticated'] = auth_type in ('apiKey', 'chatgpt', 'chatgptAuthTokens')
        safe['auth_type'] = auth_type if safe['authenticated'] else None
        # initialize userAgent contains the server version, but also host details.
        agent = initialized.get('userAgent', '')
        match = re.match(r'codex[^/ ]*/([0-9][A-Za-z0-9.+-]{0,63})(?:\s|$)', agent) if isinstance(agent, str) else None
        safe['version'] = match.group(1) if match else None
        data = models.get('data')
        if not isinstance(data, list) or len(data) > 100:
            raise _Failure('protocol_error')
        for model in data:
            if not isinstance(model, dict):
                raise _Failure('protocol_error')
            identifier = _label(model.get('id'))
            name = _label(model.get('displayName'))
            if identifier and name:
                safe['models'].append({'id': identifier, 'name': name})
        client.check()
        return dict(safe, status='ok')
    except _Failure as exc:
        return dict(authenticated=False, auth_type=None, version=None, models=[], status=str(exc))
    except (OSError, ValueError, TypeError):
        return dict(authenticated=False, auth_type=None, version=None, models=[], status='unavailable')
    finally:
        if client is not None:
            client.close()
