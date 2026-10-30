"""Local, discovery-only adapters; no certified external execution versions yet.

inventory() never starts a process. probe() runs only --version or ACP v1
initialize in a disposable home/cwd. stream() fails closed before transmitting
any prompt. No credentials are read, sessions created, or tools granted.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from types import MappingProxyType


MAX_LINE = 64 * 1024
MAX_OUTPUT = 512 * 1024
MAX_MESSAGES = 128
_VERSION = r'(\d{1,4}\.\d{1,4}\.\d{1,4}(?:-[A-Za-z0-9.-]{1,40})?(?:\+[A-Za-z0-9.-]{1,20})?)'


class RuntimeBlocked(Exception):
    """Fixed diagnostic code only; never wrap raw subprocess/RPC errors."""


@dataclass(frozen=True)
class _Spec:
    executable: str
    environment: str
    version_pattern: str = ''


_REGISTRY = MappingProxyType({
    'claude': _Spec('claude', 'CENTRAL_CLAUDE_EXECUTABLE', _VERSION + r' \(Claude Code\)'),
    'gemini': _Spec('gemini', 'CENTRAL_GEMINI_EXECUTABLE', _VERSION),
    'opencode': _Spec('opencode', 'CENTRAL_OPENCODE_EXECUTABLE', _VERSION),
    # ACP is a protocol, not a standard executable named "acp".
    'acp': _Spec('', 'CENTRAL_ACP_EXECUTABLE'),
})


def registry():
    """Capabilities describe implemented discovery, never promised execution."""
    return {name: {
        'version_probe': name != 'acp', 'acp_initialize': name == 'acp',
        'text_stream': False, 'action_planner': False,
        'tools_disable_certified': False, 'gateway_binding': False,
        'certified_versions': [],
    } for name in _REGISTRY}


def _resolve(name):
    spec = _REGISTRY.get(name)
    if spec is None:
        raise RuntimeBlocked('unknown_runtime')
    value = os.environ.get(spec.environment)
    if value is None:
        value = shutil.which(spec.executable) if spec.executable else None
    if value is None:
        raise RuntimeBlocked('not_configured' if name == 'acp' else 'not_found')
    path = Path(value)
    if (not path.is_absolute() or not path.is_file()
            or (os.name == 'nt' and path.suffix.lower() != '.exe')
            or (os.name != 'nt' and not os.access(path, os.X_OK))):
        raise RuntimeBlocked('invalid_executable')
    return str(path.resolve())


def inventory():
    """Read-only PATH/admin override presence; no paths or environment values."""
    result = {}
    for name, spec in _REGISTRY.items():
        present, status = False, 'available'
        try:
            _resolve(name)
            present = True
        except (OSError, ValueError):
            status = 'invalid_executable'
        except RuntimeBlocked as exc:
            status = str(exc)
        result[name] = {
            'present': present, 'configured': spec.environment in os.environ,
            'status': status, 'capabilities': registry()[name],
        }
    return result


def _timeout(value):
    if (type(value) not in (float, int) or not 0 < value <= 60
            or not math.isfinite(value)):
        raise RuntimeBlocked('invalid_timeout')


def _check(deadline, cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeBlocked('cancelled')
    if time.monotonic() >= deadline:
        raise RuntimeBlocked('timeout')


def _acp_arguments():
    try:
        value = json.loads(os.environ.get('CENTRAL_ACP_ARGS', '[]'))
    except (ValueError, RecursionError):
        raise RuntimeBlocked('invalid_arguments') from None
    if (not isinstance(value, list) or len(value) > 16
            or any(not isinstance(arg, str) or not arg or len(arg) > 256
                   or any(ord(char) < 32 for char in arg) for arg in value)):
        raise RuntimeBlocked('invalid_arguments')
    return value


def _isolated_environment(home):
    # Deliberate allowlist: no provider keys, login helpers, Node preload,
    # Python startup injection, proxy credentials, or CLI config overrides.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'PATHEXT',
                              'SYSTEMDRIVE', 'LANG', 'LC_ALL'}}
    env.update({key: home for key in (
        'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME',
        'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'TEMP', 'TMP', 'TMPDIR')})
    env.update({'CI': '1', 'NO_COLOR': '1'})
    return env


class _WindowsJob:
    """Kill the discovery process and its descendants on close (Windows)."""
    def __init__(self, process):
        import ctypes
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong),
                        ('job_time', ctypes.c_longlong), ('flags', w.DWORD),
                        ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                        ('active', w.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(field, ctypes.c_ulonglong) for field in (
                'read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', Counters),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int,
                                                       ctypes.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise RuntimeBlocked('containment_failed')
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not self.kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle))):
            self.close()
            raise RuntimeBlocked('containment_failed')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class _Process:
    """Bounded byte framing and independent pipe workers for Windows sync routes.

    The child must be trusted admin/PATH software: this is lifecycle containment,
    not a sandbox for arbitrary binaries. No public API accepts a command array.
    """
    def __init__(self, command, deadline, cancel_event, home):
        self.deadline, self.cancel_event = deadline, cancel_event
        self.stop = threading.Event()
        self.events = queue.Queue(maxsize=16)
        self.outgoing = queue.Queue(maxsize=16)
        self.failure = None
        self.job = None
        self.threads = []
        _check(deadline, cancel_event)
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, shell=False, bufsize=0,
            cwd=home, env=_isolated_environment(home), **options)
        try:
            if os.name == 'nt':
                self.job = _WindowsJob(self.process)
            for target in (self._read, self._write):
                thread = threading.Thread(target=target, name='central-runtime-discovery', daemon=True)
                thread.start()
                self.threads.append(thread)
        except BaseException:
            self.close()
            raise

    def _put(self, value):
        while not self.stop.is_set():
            try:
                self.events.put(value, timeout=.025)
                return
            except queue.Full:
                pass

    def _read(self):
        pending = b''
        total = messages = 0
        try:
            while not self.stop.is_set():
                chunk = os.read(self.process.stdout.fileno(), 4096)
                if not chunk:
                    if pending:
                        self._put(pending)  # Version output can omit its final newline.
                    self._put(None)
                    return
                total += len(chunk)
                if total > MAX_OUTPUT:
                    raise RuntimeBlocked('output_limit')
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    messages += 1
                    if len(line) + 1 > MAX_LINE or messages > MAX_MESSAGES:
                        raise RuntimeBlocked('output_limit')
                    self._put(line + b'\n')
                if len(pending) >= MAX_LINE:
                    raise RuntimeBlocked('output_limit')
        except RuntimeBlocked as exc:
            self.failure = str(exc)
        except (OSError, ValueError):
            self.failure = 'disconnected'

    def _write(self):
        try:
            while not self.stop.is_set():
                try:
                    value = self.outgoing.get(timeout=.025)
                except queue.Empty:
                    continue
                pending = memoryview(value)
                while pending and not self.stop.is_set():
                    count = os.write(self.process.stdin.fileno(), pending)
                    if not count:
                        raise OSError()
                    pending = pending[count:]
        except (OSError, ValueError):
            self.failure = 'disconnected'

    def check(self):
        _check(self.deadline, self.cancel_event)
        if self.failure:
            raise RuntimeBlocked(self.failure)

    def receive(self):
        while True:
            self.check()
            try:
                return self.events.get(timeout=.025)
            except queue.Empty:
                pass

    def send(self, value):
        self.check()
        data = (json.dumps(value, allow_nan=False) + '\n').encode('utf-8')
        if len(data) > MAX_LINE:
            raise RuntimeBlocked('input_limit')
        try:
            self.outgoing.put_nowait(data)
        except queue.Full:
            raise RuntimeBlocked('output_limit') from None

    def close(self):
        self.stop.set()
        if self.job is not None:
            self.job.close()
        elif os.name != 'nt':
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.process.poll() is None:
            self.process.kill()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise RuntimeBlocked('cleanup_failed') from None
        finally:
            for thread in self.threads:
                thread.join(timeout=.5)
            for pipe in (self.process.stdin, self.process.stdout):
                pipe.close()
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeBlocked('cleanup_failed')


@contextmanager
def _connection(command, deadline, cancel_event):
    with tempfile.TemporaryDirectory(prefix='central-runtime-') as home:
        process = _Process(command, deadline, cancel_event, home)
        try:
            yield process
        finally:
            process.close()


def _read_version(process, pattern):
    output = bytearray()
    while True:
        value = process.receive()
        if value is None:
            break
        output.extend(value)
        if len(output) > 1024:
            raise RuntimeBlocked('invalid_version')
    while process.process.poll() is None:
        process.check()
        process.stop.wait(.01)
    if process.process.returncode != 0:
        raise RuntimeBlocked('version_failed')
    match = re.fullmatch(pattern, output.decode('utf-8').strip(), flags=re.ASCII)
    if not match:
        raise RuntimeBlocked('invalid_version')
    return match.group(1)


def _object_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate')
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError('constant')


def _acp_initialize(process):
    process.send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': 1,
        'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False},
                               'terminal': False},
        'clientInfo': {'name': 'central-discovery', 'version': '1.0.0'},
    }})
    for _ in range(MAX_MESSAGES):
        line = process.receive()
        if line is None:
            raise RuntimeBlocked('disconnected')
        if not line.endswith(b'\n'):
            raise RuntimeBlocked('protocol_error')
        try:
            value = json.loads(line.decode('utf-8'), object_pairs_hook=_object_pairs,
                               parse_constant=_invalid_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise RuntimeBlocked('protocol_error') from None
        if not isinstance(value, dict) or value.get('jsonrpc') != '2.0':
            raise RuntimeBlocked('protocol_error')
        if 'method' in value:
            if not isinstance(value['method'], str) or not value['method']:
                raise RuntimeBlocked('protocol_error')
            if 'result' in value or 'error' in value:
                raise RuntimeBlocked('protocol_error')
            if 'id' in value:
                identifier = value['id']
                if (type(identifier) not in (str, int)
                        or len(str(identifier)) > 128):
                    raise RuntimeBlocked('protocol_error')
                # No gateway binding exists in this sidecar. All inbound calls,
                # including permissions, file/terminal and login, are refused.
                process.send({'jsonrpc': '2.0', 'id': identifier, 'error': {
                    'code': -32601, 'message': 'Client method not supported'}})
            continue
        if type(value.get('id')) is not int or value['id'] != 1:
            raise RuntimeBlocked('protocol_error')
        if 'error' in value:
            if 'result' in value or not isinstance(value['error'], dict):
                raise RuntimeBlocked('protocol_error')
            raise RuntimeBlocked('rpc_error')
        result = value.get('result')
        if not isinstance(result, dict):
            raise RuntimeBlocked('protocol_error')
        if type(result.get('protocolVersion')) is not int or result['protocolVersion'] != 1:
            raise RuntimeBlocked('unsupported_protocol')
        if not isinstance(result.get('agentCapabilities'), dict):
            raise RuntimeBlocked('protocol_error')
        info = result.get('agentInfo', {})
        version = info.get('version') if isinstance(info, dict) else None
        return version if isinstance(version, str) and re.fullmatch(_VERSION, version, re.ASCII) else None
    raise RuntimeBlocked('output_limit')


def probe(runtime, timeout=5.0, cancel_event=None):
    """Sync discovery, fixed statuses, unknown authentication (None).

    ACP transport_ready proves only initialize, never auth, tool safety or model
    access. CLI unsupported_version reports parsed version but no certification.
    Timeout <=60s covers all IO; cleanup adds up to two bounded worker waits.
    """
    name = runtime if isinstance(runtime, str) and runtime in _REGISTRY else 'unknown'
    result = {'runtime': name, 'present': False, 'version': None,
              'authenticated': None, 'auth_type': None, 'protocol_version': None,
              'capabilities': registry().get(name, {}),
              'execution_blocker': 'native_tools_uncertified'}
    try:
        if os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local') != 'local':
            raise RuntimeBlocked('server_mode_refused')
        _timeout(timeout)
        deadline = time.monotonic() + timeout
        _check(deadline, cancel_event)
        executable = _resolve(name)
        result['present'] = True
        command = [executable] + (_acp_arguments() if name == 'acp' else ['--version'])
        with _connection(command, deadline, cancel_event) as process:
            if name == 'acp':
                result['version'] = _acp_initialize(process)
                result['protocol_version'] = 1
                status = 'transport_ready'
            else:
                result['version'] = _read_version(process, _REGISTRY[name].version_pattern)
                status = 'unsupported_version'
            process.check()
        return dict(result, status=status)
    except RuntimeBlocked as exc:
        return dict(result, status=str(exc))
    except (OSError, ValueError, TypeError, OverflowError):
        return dict(result, status='unavailable')


def stream(runtime, model, system, messages, *, timeout=60.0, cancel_event=None):
    """Synchronous iterator interface reserved for certified text planners.

    Always raises RuntimeBlocked today, before executing any CLI or serializing
    model/system/messages. Caller must route validated action JSON through the
    Central gateway when an actual certified planner is added. No fallback to
    native tools, generic ACP prompting, API billing, login, or auto-install.
    """
    if os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local') != 'local':
        raise RuntimeBlocked('server_mode_refused')
    _timeout(timeout)
    _check(time.monotonic() + timeout, cancel_event)
    if not isinstance(runtime, str) or runtime not in _REGISTRY:
        raise RuntimeBlocked('unknown_runtime')
    try:
        _resolve(runtime)
    except (OSError, ValueError):
        raise RuntimeBlocked('invalid_executable') from None
    raise RuntimeBlocked('native_tools_uncertified')
    yield  # Iterator contract; no fake text or success events.
