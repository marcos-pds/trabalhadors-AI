"""Real local Python subprocess fixtures. NOT live runtime/model evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from central import external_runtimes as runtimes


FIXTURE = r'''
import json, os, subprocess, sys, time
mode = sys.argv[1]
def emit(value):
    print(json.dumps(value), flush=True)
if mode == 'hang':
    time.sleep(30)
if mode == 'stderr':
    sys.stderr.write('SECRET@example.invalid /private/path sk-private' * 100000)
    sys.stderr.flush()
if mode == 'oversize':
    sys.stdout.write('x' * 70000)
    sys.stdout.flush()
    time.sleep(30)
if mode == 'total':
    for _ in range(100):
        emit({'jsonrpc': '2.0', 'method': 'notice', 'params': {'x': 'a' * 6000}})
    time.sleep(30)
if mode == 'messages':
    for _ in range(200):
        emit({'jsonrpc': '2.0', 'method': 'notice'})
    time.sleep(30)
if mode.startswith('version_'):
    text = {'version_claude': '2.1.300 (Claude Code)', 'version_gemini': '0.40.0',
            'version_opencode': '1.2.3', 'version_bad': 'SECRET@example.invalid /private/path',
            'version_exit': '1.2.3', 'version_nonewline': '1.2.3',
            'version_huge': 'x' * 2000}[mode]
    print(text, end='' if mode == 'version_nonewline' else '\n', flush=True)
    sys.exit(7 if mode == 'version_exit' else 0)
if mode == 'exit':
    sys.exit(0)
if mode == 'malformed':
    print('{invalid', flush=True)
    time.sleep(30)
if mode == 'utf8':
    sys.stdout.buffer.write(b'\xff\n')
    sys.stdout.buffer.flush()
    time.sleep(30)
request = json.loads(input())
assert request == {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': 1,
    'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False},
    'clientInfo': {'name': 'central-discovery', 'version': '1.0.0'}}}
if mode == 'duplicate':
    print('{"jsonrpc":"2.0","id":1,"id":1,"result":{}}', flush=True)
    time.sleep(30)
if mode == 'nan':
    print('{"jsonrpc":"2.0","id":1,"result":{"bad":NaN}}', flush=True)
    time.sleep(30)
if mode == 'deep':
    print('[' * 2000 + '0' + ']' * 2000, flush=True)
    time.sleep(30)
if mode == 'no_newline':
    sys.stdout.write('{"jsonrpc":"2.0","id":1,"result":{}}')
    sys.stdout.flush()
    sys.exit(0)
if mode == 'blocked_write':
    for _ in range(200):
        emit({'jsonrpc': '2.0', 'id': 'a' * 128, 'method': 'terminal/create'})
    time.sleep(30)  # Deliberately never read the refusals.
if mode in ('normal', 'stderr', 'unsafe_info', 'child'):
    for i, method in enumerate(('fs/read_text_file', 'fs/write_text_file',
                               'terminal/create', 'session/request_permission', 'authenticate', 'unknown')):
        emit({'jsonrpc': '2.0', 'id': 'server-' + str(i), 'method': method,
              'params': {'path': '/private/path', 'secret': 'SECRET'}})
        denial = json.loads(input())
        assert denial == {'jsonrpc': '2.0', 'id': 'server-' + str(i), 'error': {
            'code': -32601, 'message': 'Client method not supported'}}
    emit({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'secret': 'SECRET'}})
if mode == 'child':
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    open(sys.argv[2], 'w').write(str(child.pid))
result = {'protocolVersion': 1, 'agentCapabilities': {},
          'agentInfo': {'version': '1.2.3', 'name': 'SECRET@example.invalid'},
          'authMethods': [{'id': 'private-token', 'name': 'SECRET'}],
          'unexpected': 'SECRET /private/path'}
response = {'jsonrpc': '2.0', 'id': 1, 'result': result}
if mode == 'unsafe_info':
    result['agentInfo']['version'] = 'SECRET@example.invalid /private/path'
if mode == 'unsupported':
    result['protocolVersion'] = 2
if mode == 'bool_protocol':
    result['protocolVersion'] = True
if mode == 'bad_caps':
    result['agentCapabilities'] = []
if mode == 'wrong_id':
    response['id'] = 2
if mode == 'bool_id':
    response['id'] = True
if mode == 'missing_jsonrpc':
    del response['jsonrpc']
if mode == 'error':
    response = {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'SECRET@example.invalid'}}
if mode == 'both':
    response['error'] = {'code': -32000, 'message': 'SECRET'}
if mode == 'bad_request':
    response = {'jsonrpc': '2.0', 'id': [], 'method': 'fs/read_text_file'}
emit(response)
time.sleep(30)  # Client must close, never send session/new, authenticate or prompts.
'''


@pytest.fixture(autouse=True)
def local_environment(monkeypatch):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    for key in ('CENTRAL_CLAUDE_EXECUTABLE', 'CENTRAL_GEMINI_EXECUTABLE',
                'CENTRAL_OPENCODE_EXECUTABLE', 'CENTRAL_ACP_EXECUTABLE', 'CENTRAL_ACP_ARGS'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(runtimes.shutil, 'which', lambda name: None)


@pytest.fixture
def launch(monkeypatch, tmp_path):
    script = tmp_path / 'fixture.py'
    script.write_text(FIXTURE, encoding='utf-8')
    original = subprocess.Popen
    processes, options = [], []
    monkeypatch.setattr(runtimes, '_resolve', lambda name: str(Path(sys.executable).resolve()))

    def configure(mode, extra=()):
        def popen(command, **kwargs):
            options.append((command, kwargs))
            child = original([sys.executable, '-u', str(script), mode, *extra], **kwargs)
            processes.append(child)
            return child
        monkeypatch.setattr(runtimes.subprocess, 'Popen', popen)
        return processes, options

    yield configure
    assert all(child.poll() is not None for child in processes), 'leaked fixture process'
    assert all(child.stdin.closed and child.stdout.closed for child in processes)
    assert not [thread for thread in threading.enumerate()
                if thread.name == 'central-runtime-discovery'], 'leaked pipe worker'


def test_registry_is_detached_and_never_promises_execution():
    result = runtimes.registry()
    assert set(result) == {'claude', 'gemini', 'opencode', 'acp'}
    for capabilities in result.values():
        assert capabilities['certified_versions'] == []
        assert not any(capabilities[key] for key in (
            'text_stream', 'action_planner', 'tools_disable_certified', 'gateway_binding'))
    result['claude']['certified_versions'].append('unsafe')
    assert runtimes.registry()['claude']['certified_versions'] == []


def test_inventory_presence_only(monkeypatch):
    monkeypatch.setattr(runtimes.subprocess, 'Popen', lambda *a, **kw: pytest.fail('launched'))
    monkeypatch.setattr(runtimes.shutil, 'which', lambda name: sys.executable if name == 'claude' else None)
    result = runtimes.inventory()
    assert result['claude']['present']
    assert result['gemini']['status'] == 'not_found'
    assert result['opencode']['status'] == 'not_found'
    assert result['acp']['status'] == 'not_configured'
    assert sys.executable not in json.dumps(result)


@pytest.mark.parametrize('runtime', ['claude', 'gemini', 'opencode', 'acp'])
def test_missing_runtime_never_launches(monkeypatch, runtime):
    monkeypatch.setattr(runtimes.subprocess, 'Popen', lambda *a, **kw: pytest.fail('launched'))
    status = 'not_configured' if runtime == 'acp' else 'not_found'
    assert runtimes.probe(runtime)['status'] == status
    with pytest.raises(runtimes.RuntimeBlocked, match='^' + status + '$'):
        list(runtimes.stream(runtime, 'model', 'system', []))


@pytest.mark.parametrize('runtime,mode,version', [
    ('claude', 'version_claude', '2.1.300'), ('gemini', 'version_gemini', '0.40.0'),
    ('opencode', 'version_opencode', '1.2.3'), ('gemini', 'version_nonewline', '1.2.3')])
def test_real_subprocess_version_probe(launch, runtime, mode, version):
    _, options = launch(mode)
    result = runtimes.probe(runtime, timeout=3)
    assert result['status'] == 'unsupported_version'
    assert result['version'] == version
    assert result['authenticated'] is None
    assert not result['capabilities']['text_stream']
    assert options[0][0] == [str(Path(sys.executable).resolve()), '--version']


def test_acp_initialization_and_refusal(launch):
    launch('normal')
    result = runtimes.probe('acp', timeout=3)
    assert result['status'] == 'transport_ready'
    assert result['protocol_version'] == 1
    assert result['version'] == '1.2.3'
    assert result['authenticated'] is None and result['auth_type'] is None
    assert result['execution_blocker'] == 'native_tools_uncertified'
    assert 'SECRET' not in json.dumps(result)
    assert '/private/path' not in json.dumps(result)


def test_isolated_environment_and_no_stderr(launch, monkeypatch, capfd):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'SECRET')
    monkeypatch.setenv('NODE_OPTIONS', '--require secret-plugin')
    monkeypatch.setenv('GEMINI_API_KEY', 'SECRET')
    monkeypatch.setenv('PYTHONPATH', '/private/path')
    monkeypatch.setenv('HTTPS_PROXY', 'SECRET')
    _, options = launch('stderr')
    assert runtimes.probe('acp', timeout=3)['status'] == 'transport_ready'
    _, kwargs = options[0]
    assert kwargs['shell'] is False and kwargs['stderr'] == subprocess.DEVNULL
    assert not set(kwargs['env']) & {'ANTHROPIC_API_KEY', 'NODE_OPTIONS', 'GEMINI_API_KEY',
                                     'PYTHONPATH', 'HTTPS_PROXY'}
    assert kwargs['env']['HOME'] == kwargs['cwd']
    assert kwargs['env']['USERPROFILE'] == kwargs['cwd']
    assert not Path(kwargs['cwd']).exists(), 'temporary home leaked'
    assert capfd.readouterr() == ('', '')


@pytest.mark.parametrize('mode,status', [
    ('hang', 'timeout'), ('oversize', 'output_limit'), ('total', 'output_limit'),
    ('messages', 'output_limit'), ('blocked_write', 'output_limit'),
    ('exit', 'disconnected'), ('malformed', 'protocol_error'), ('utf8', 'protocol_error'),
    ('duplicate', 'protocol_error'), ('nan', 'protocol_error'), ('deep', 'protocol_error'),
    ('no_newline', 'protocol_error'), ('unsupported', 'unsupported_protocol'),
    ('bool_protocol', 'unsupported_protocol'), ('bad_caps', 'protocol_error'),
    ('wrong_id', 'protocol_error'), ('bool_id', 'protocol_error'),
    ('missing_jsonrpc', 'protocol_error'), ('error', 'rpc_error'),
    ('both', 'protocol_error'), ('bad_request', 'protocol_error')])
def test_bounded_acp_failures_and_cleanup(launch, mode, status):
    launch(mode)
    started = time.monotonic()
    result = runtimes.probe('acp', timeout=.3 if mode == 'hang' else 3)
    assert result['status'] == status
    assert time.monotonic() - started < 5
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('mode,status', [
    ('version_bad', 'invalid_version'), ('version_huge', 'invalid_version'),
    ('version_exit', 'version_failed')])
def test_invalid_version_is_not_echoed(launch, mode, status):
    launch(mode)
    result = runtimes.probe('gemini', timeout=3)
    assert result['status'] == status
    assert result['version'] is None
    assert 'SECRET' not in json.dumps(result)


def test_unsafe_agent_metadata_is_dropped(launch):
    launch('unsafe_info')
    result = runtimes.probe('acp', timeout=3)
    assert result['status'] == 'transport_ready'
    assert result['version'] is None


def test_running_probe_cancellation(launch):
    launch('hang')
    cancelled = threading.Event()
    timer = threading.Timer(.15, cancelled.set)
    timer.start()
    try:
        assert runtimes.probe('acp', timeout=3, cancel_event=cancelled)['status'] == 'cancelled'
    finally:
        timer.join()


def test_precancelled_never_launches(monkeypatch):
    monkeypatch.setattr(runtimes.subprocess, 'Popen', lambda *a, **kw: pytest.fail('launched'))
    cancel = threading.Event()
    cancel.set()
    assert runtimes.probe('claude', cancel_event=cancel)['status'] == 'cancelled'


@pytest.mark.parametrize('mode', ['server', 'unknown', ''])
def test_server_mode_never_launches(monkeypatch, mode):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', mode)
    monkeypatch.setattr(runtimes.subprocess, 'Popen', lambda *a, **kw: pytest.fail('launched'))
    assert runtimes.probe('claude')['status'] == 'server_mode_refused'
    with pytest.raises(runtimes.RuntimeBlocked, match='^server_mode_refused$'):
        list(runtimes.stream('acp', '', '', []))


@pytest.mark.parametrize('value', [0, -1, 61, float('nan'), float('inf'), True, '3', None])
def test_timeout_validation(value):
    assert runtimes.probe('claude', timeout=value)['status'] == 'invalid_timeout'


@pytest.mark.parametrize('value', ['relative.exe', '', 'C:/definitely-missing/runtime.exe'])
def test_override_is_not_a_shell_command(monkeypatch, value):
    monkeypatch.setenv('CENTRAL_CLAUDE_EXECUTABLE', value)
    monkeypatch.setattr(runtimes.subprocess, 'Popen', lambda *a, **kw: pytest.fail('launched'))
    assert runtimes.probe('claude')['status'] == 'invalid_executable'


def test_override_does_not_fallback_to_path(monkeypatch):
    monkeypatch.setenv('CENTRAL_GEMINI_EXECUTABLE', 'relative.exe')
    monkeypatch.setattr(runtimes.shutil, 'which', lambda name: pytest.fail('fallback'))
    assert runtimes.probe('gemini')['status'] == 'invalid_executable'


@pytest.mark.skipif(os.name != 'nt', reason='Windows must not execute shell wrappers')
def test_windows_cmd_wrapper_is_refused(monkeypatch, tmp_path):
    wrapper = tmp_path / 'gemini.cmd'
    wrapper.write_text('@echo unsafe')
    monkeypatch.setenv('CENTRAL_GEMINI_EXECUTABLE', str(wrapper))
    assert runtimes.probe('gemini')['status'] == 'invalid_executable'


@pytest.mark.parametrize('arguments', ['not json', '{}', '[1]', '[""]', '["a\\u0000b"]',
                                      json.dumps(['a'] * 17), json.dumps(['a' * 257])])
def test_invalid_acp_arguments_no_launch(monkeypatch, arguments):
    monkeypatch.setenv('CENTRAL_ACP_EXECUTABLE', sys.executable)
    monkeypatch.setenv('CENTRAL_ACP_ARGS', arguments)
    monkeypatch.setattr(runtimes.subprocess, 'Popen', lambda *a, **kw: pytest.fail('launched'))
    assert runtimes.probe('acp')['status'] == 'invalid_arguments'


def test_admin_acp_arguments_are_argv_not_shell(launch, monkeypatch):
    monkeypatch.setenv('CENTRAL_ACP_ARGS', '["acp", "a;echo SECRET"]')
    _, options = launch('normal')
    assert runtimes.probe('acp', timeout=3)['status'] == 'transport_ready'
    assert options[0][0][1:] == ['acp', 'a;echo SECRET']
    assert options[0][1]['shell'] is False


@pytest.mark.parametrize('value', ['SECRET/path', [], None])
def test_unknown_runtime_is_not_echoed(value):
    result = runtimes.probe(value)
    assert result['status'] == 'unknown_runtime'
    assert result['runtime'] == 'unknown'


@pytest.mark.parametrize('runtime', ['claude', 'gemini', 'opencode', 'acp'])
def test_stream_refuses_before_sending_prompt(monkeypatch, runtime):
    monkeypatch.setattr(runtimes, '_resolve', lambda name: sys.executable)
    monkeypatch.setattr(runtimes.subprocess, 'Popen', lambda *a, **kw: pytest.fail('launched'))
    class PrivatePrompt:
        def __str__(self):
            pytest.fail('prompt inspected')
        def __iter__(self):
            pytest.fail('prompt inspected')
    with pytest.raises(runtimes.RuntimeBlocked, match='^native_tools_uncertified$'):
        list(runtimes.stream(runtime, PrivatePrompt(), PrivatePrompt(), PrivatePrompt()))


def test_popen_errors_are_sanitized(monkeypatch):
    monkeypatch.setattr(runtimes, '_resolve', lambda name: sys.executable)
    def fail(*args, **kwargs):
        raise OSError('SECRET@example.invalid /private/path')
    monkeypatch.setattr(runtimes.subprocess, 'Popen', fail)
    result = runtimes.probe('acp')
    assert result['status'] == 'unavailable'
    assert 'SECRET' not in json.dumps(result)


def test_process_tree_cleanup(launch, tmp_path):
    pid_file = tmp_path / 'child.pid'
    launch('child', [str(pid_file)])
    assert runtimes.probe('acp', timeout=3)['status'] == 'transport_ready'
    pid = int(pid_file.read_text())
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 1000) == 0, 'descendant survived'
            finally:
                kernel.CloseHandle(handle)
    else:
        # A killed adopted child can briefly remain as a zombie until reaped.
        status_file = Path('/proc') / str(pid) / 'stat'
        if status_file.exists():
            assert status_file.read_text().split()[2] == 'Z'
