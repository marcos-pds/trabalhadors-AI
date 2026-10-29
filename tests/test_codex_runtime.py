"""Protocol tests use real Python subprocesses, not live model calls."""
import json
import subprocess
import sys
import threading
import time

import pytest

from central import codex_runtime as runtime


FIXTURE = r'''
import json, sys, time
mode = sys.argv[1]
def send(value):
    print(json.dumps(value), flush=True)
if mode == 'hang':
    time.sleep(30)
if mode == 'flood':
    print('x' * 300000, flush=True)
    time.sleep(30)
if mode == 'notifications':
    for _ in range(300):
        send({'method': 'notice'})
    time.sleep(30)
if mode == 'malformed':
    print('{invalid', flush=True)
    time.sleep(30)
if mode == 'exit':
    sys.exit(0)
if mode == 'stderr':
    sys.stderr.write('private-token@email.example' * 100000)
    sys.stderr.flush()
request = json.loads(input())
assert request['method'] == 'initialize'
send({'id': request['id'], 'result': {'userAgent': 'codex/0.164.0-alpha.11.1 (private/path)'}})
assert json.loads(input())['method'] == 'initialized'
request = json.loads(input())
assert request['method'] == 'account/read'
assert request['params'] == {'refreshToken': False}
send({'id': 'server1', 'method': 'account/chatgptAuthTokens/refresh', 'params': {'secret': 'private'}})
refusal = json.loads(input())
assert refusal['id'] == 'server1' and refusal['error']['code'] == -32601
if mode == 'error':
    send({'id': request['id'], 'error': {'message': 'private-token@email.example'}})
    time.sleep(30)
if mode == 'wrong_id':
    send({'id': 999, 'result': {}})
    time.sleep(30)
send({'id': request['id'], 'result': {'account': {'type': 'chatgpt', 'email': 'private@email.example', 'token': 'private'}}})
request = json.loads(input())
assert request['method'] == 'model/list'
send({'id': request['id'], 'result': {'data': [
    {'id': 'model-1', 'displayName': 'Model One', 'secret': 'private'},
    {'id': '/private/path', 'displayName': 'private@email.example'}]}})
time.sleep(30)
'''


@pytest.fixture
def launch(monkeypatch, tmp_path):
    fixture = tmp_path / 'server.py'
    fixture.write_text(FIXTURE, encoding='utf-8')
    original = subprocess.Popen
    processes = []
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    monkeypatch.setattr(runtime, '_executable', lambda: sys.executable)

    def configure(mode):
        def popen(command, **kwargs):
            assert command == [sys.executable, 'app-server']
            assert kwargs['shell'] is False
            assert kwargs['stderr'] == subprocess.DEVNULL
            process = original([sys.executable, '-u', str(fixture), mode], **kwargs)
            processes.append(process)
            return process
        monkeypatch.setattr(runtime.subprocess, 'Popen', popen)
        return processes
    yield configure
    assert all(process.poll() is not None for process in processes)


def test_protocol_and_safe_output(launch):
    launch('normal')
    result = runtime.probe(3)
    assert result == {'status': 'ok', 'authenticated': True, 'auth_type': 'chatgpt',
                      'version': '0.164.0-alpha.11.1',
                      'models': [{'id': 'model-1', 'name': 'Model One'}]}
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('mode,status', [
    ('hang', 'timeout'), ('flood', 'output_limit'),
    ('notifications', 'output_limit'),
    ('malformed', 'protocol_error'), ('exit', 'disconnected'),
    ('error', 'rpc_error'), ('wrong_id', 'protocol_error'), ('stderr', 'ok')])
def test_failures_and_cleanup(launch, mode, status):
    launch(mode)
    started = time.monotonic()
    result = runtime.probe(.7 if mode == 'hang' else 3)
    assert result['status'] == status
    assert time.monotonic() - started < 5
    assert 'private' not in json.dumps(result)


def test_cancellation(launch):
    launch('hang')
    cancelled = threading.Event()
    timer = threading.Timer(.15, cancelled.set)
    timer.start()
    try:
        assert runtime.probe(3, cancelled)['status'] == 'cancelled'
    finally:
        timer.join()


def test_server_mode_never_launches(monkeypatch):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'server')
    monkeypatch.setattr(runtime.subprocess, 'Popen', lambda *a, **k: pytest.fail('launched'))
    assert runtime.probe()['status'] == 'server_mode_refused'


@pytest.mark.parametrize('value', [0, -1, 61, float('nan'), float('inf'), '3', True])
def test_invalid_timeout(value):
    assert runtime.probe(value)['status'] == 'invalid_timeout'


def test_override_validation(monkeypatch, tmp_path):
    monkeypatch.setenv('CENTRAL_CODEX_EXECUTABLE', 'relative.exe')
    assert runtime.probe()['status'] == 'invalid_executable'
    monkeypatch.setenv('CENTRAL_CODEX_EXECUTABLE', str(tmp_path / 'missing.exe'))
    assert runtime.probe()['status'] == 'invalid_executable'


def test_inventory_does_not_launch(monkeypatch):
    monkeypatch.delenv('CENTRAL_CODEX_EXECUTABLE', raising=False)
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: sys.executable if name == 'codex' else None)
    monkeypatch.setattr(runtime.subprocess, 'Popen', lambda *a, **k: pytest.fail('launched'))
    result = runtime.inventory()
    assert result == {name: {'present': name == 'codex'}
                      for name in ('claude', 'gemini', 'opencode', 'codex')}

@pytest.fixture
def native_client(tmp_path):
    clients = []

    def launch_script(script, **options):
        fixture = tmp_path / 'native_server.py'
        fixture.write_text('import json, os, sys, time\n'
                           'def send(v): print(json.dumps(v), flush=True)\n' + script,
                           encoding='utf-8')
        client = runtime._Client([sys.executable, '-u', str(fixture)],
                                 time.monotonic() + 5, None, **options)
        clients.append(client)
        return client

    yield launch_script
    for client in clients:
        client.close()
        assert client.process.poll() is not None
        assert not client.reader.is_alive()
        assert not client.writer.is_alive()
        assert client.process.stdin.closed and client.process.stdout.closed


def test_native_preserves_notifications_across_requests(native_client):
    client = native_client("""
for n in range(2):
    request = json.loads(input())
    for i in range(2):
        send({'method': 'notice', 'params': {'n': n * 2 + i}})
    send({'id': request['id'], 'result': {'n': n}})
send({'method': 'live'})
time.sleep(30)
""")
    assert client.request('first', {}) == {'n': 0}
    assert client.request('second', {}) == {'n': 1}
    assert [client.next_event()['params']['n'] for _ in range(4)] == list(range(4))
    assert client.next_event() == {'method': 'live'}


@pytest.mark.parametrize('method', [
    'account/chatgptAuthTokens/refresh', 'item/tool/call', 'item/commandExecution/requestApproval'])
def test_native_event_refuses_server_requests(native_client, method):
    client = native_client(f"""
send({{'id': 'server', 'method': {method!r}, 'params': {{}}}})
refusal = json.loads(input())
assert refusal == {{'id': 'server', 'error': {{'code': -32601, 'message': 'Client requests are not supported'}}}}
send({{'method': 'refused'}})
time.sleep(30)
""")
    assert client.next_event() == {'method': 'refused'}


@pytest.mark.parametrize('value', [
    {'id': 1, 'result': {}}, {'id': 1, 'error': {}}, {},
    {'id': True, 'method': 'approval'}, {'id': [], 'method': 'approval'}])
def test_native_event_protocol_errors(native_client, value):
    client = native_client(f"send({value!r})\ntime.sleep(30)\n")
    with pytest.raises(runtime._Failure, match='^protocol_error$'):
        client.next_event()


@pytest.mark.parametrize('options', [
    {'max_messages': 0}, {'max_messages': 20001}, {'max_messages': True},
    {'max_messages': 1.5}, {'max_output': 0}, {'max_output': 32 * 1024 * 1024 + 1},
    {'max_output': True}, {'max_output': '100'}])
def test_native_invalid_limits_never_launch(monkeypatch, options):
    monkeypatch.setattr(runtime.subprocess, 'Popen', lambda *a, **k: pytest.fail('launched'))
    with pytest.raises(ValueError, match='invalid client limits'):
        runtime._Client([], time.monotonic() + 1, None, **options)


@pytest.mark.parametrize('options', [{'max_messages': 2}, {'max_output': 20}])
def test_native_custom_limits_cleanup(native_client, options):
    client = native_client("for _ in range(4): send({'method': 'notice'})\ntime.sleep(30)\n",
                           **options)
    with pytest.raises(runtime._Failure, match='^output_limit$'):
        for _ in range(5):
            client.next_event()


def test_native_longer_turn(native_client):
    client = native_client("""
request = json.loads(input())
for n in range(300): send({'method': 'notice', 'params': n})
send({'id': request['id'], 'result': {}})
time.sleep(30)
""", max_messages=400, max_output=3 * 1024 * 1024)
    assert client.request('turn', {}) == {}
    assert [client.next_event()['params'] for _ in range(300)] == list(range(300))


def test_native_env_cwd_and_cancellation(native_client, tmp_path):
    import os
    client = native_client("send({'method': 'context', 'params': [os.environ['BRIDGE_TEST'], os.getcwd()]})\ntime.sleep(30)\n",
                           env=dict(os.environ, BRIDGE_TEST='isolated'), cwd=str(tmp_path))
    assert client.next_event()['params'] == ['isolated', str(tmp_path)]
    client.cancel_event = threading.Event()
    client.cancel_event.set()
    with pytest.raises(runtime._Failure, match='^cancelled$'):
        client.next_event()


def test_native_saved_notifications_obey_deadline(native_client):
    client = native_client("""
request = json.loads(input())
send({'method': 'notice'})
send({'id': request['id'], 'result': {}})
time.sleep(30)
""")
    assert client.request('turn', {}) == {}
    client.deadline = time.monotonic() - 1
    with pytest.raises(runtime._Failure, match='^timeout$'):
        client.next_event()
