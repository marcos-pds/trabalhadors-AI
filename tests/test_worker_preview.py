"""Owned preview lifecycle and real authorization, without launching processes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import subprocess
from pathlib import Path
import threading

import pytest
from fastapi import HTTPException

from central import live_preview as live, worker_preview as worker
from central.computer_access import set_policy
from central.workspace_guard import bind_run
from test_workspace_isolation import db, add_run


_REAL_POPEN = subprocess.Popen
_NODE = shutil.which('node')


class Process:
    def __init__(self):
        self.code = None
    def poll(self):
        return self.code


class Timer:
    def __init__(self, seconds, fn, args):
        self.seconds, self.fn, self.args = seconds, fn, args
        self.cancelled = False
    def start(self):
        pass
    def cancel(self):
        self.cancelled = True


class Connection:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


@pytest.fixture
def preview(db, tmp_path, monkeypatch):
    folder = tmp_path / 'workspace'
    folder.mkdir()
    (folder / 'package.json').write_text(json.dumps({'scripts': {'dev': 'node server.js'}}))
    nested = folder / 'client'
    nested.mkdir()
    (nested / 'package.json').write_text(json.dumps({'scripts': {'dev': 'node server.js'}}))
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'host')
    set_policy(db, 'a', 'full', str(folder))
    for rid in ('r1', 'r2'):
        add_run(db, 'a', rid)
        bind_run(db, 'a', rid)
    monkeypatch.setattr(worker, '_OWNED', {})
    monkeypatch.setattr(live, '_SESSIONS', {})
    monkeypatch.setattr(live.shutil, 'which', lambda _: 'npm')
    monkeypatch.setattr(live.threading, 'Timer', Timer)
    monkeypatch.setattr(live.socket, 'create_connection', lambda *a, **k: Connection())
    spawned, killed = [], []

    def spawn(args, **kwargs):
        process = Process()
        spawned.append((args, kwargs, process))
        return process

    def kill(process):
        process.code = -9
        killed.append(process)

    monkeypatch.setattr(live.subprocess, 'Popen', spawn)
    monkeypatch.setattr(live, '_kill_tree', kill)
    yield db, folder, spawned, killed
    live.stop_all()


def call(db, operation, run='r1', **kwargs):
    return asyncio.run(worker.execute(db, 'a', run, dict(action='preview', operation=operation, **kwargs)))


@pytest.mark.parametrize('payload', [
    None, [], {}, {'action': 'preview', 'operation': []},
    {'action': 'command', 'operation': 'start'},
    {'action': 'preview', 'operation': 'start', 'shell': 'whoami'},
    *[dict(action='preview', operation='start', cwd=cwd) for cwd in
      (None, False, 4, [], '/tmp', 'C:/tmp', '../src', 'a/../b', 'a//b',
       'a\\b', '.', '.git', '.git./x', 'NUL', 'x/' , 'x' * 241, 'a/' * 13 + 'b')],
])
def test_strict_request_validation(payload):
    with pytest.raises(ValueError):
        worker.validate_request(payload)


def test_valid_request_is_copied_and_start_defaults_to_root():
    request = {'action': 'preview', 'operation': 'start'}
    assert worker.validate_request(request) == dict(request, cwd='')
    assert 'cwd' not in request
    assert worker.validate_request(dict(request, cwd='my app/client'))['cwd'] == 'my app/client'
    assert 'cwd' not in worker.validate_request({'action': 'preview', 'operation': 'status'})


def test_owned_lifecycle_and_audit_output(preview):
    db, folder, spawned, killed = preview
    first = call(db, 'start', cwd='client')
    assert first['success'] is True and first['status'] == 'running'
    assert first['url'].startswith('http://127.0.0.1:')
    assert first['cwd'] == 'client'
    assert json.loads(first['output']) == {k: first[k] for k in ('status', 'url', 'cwd')}
    assert 'folder' not in json.loads(first['output'])
    assert call(db, 'start', cwd='client')['url'] == first['url']
    assert call(db, 'status')['url'] == first['url']
    assert len(spawned) == 1
    args, kwargs, process = spawned[0]
    assert args[1:6] == ['run', 'dev', '--', '--host', '127.0.0.1']
    assert args[-1] == '--strictPort' and kwargs['shell'] is False
    assert Path(kwargs['cwd']) == folder / 'client'
    stopped = call(db, 'stop')
    assert stopped['success'] and json.loads(stopped['output']) == {'status': 'stopped'}
    assert killed == [process]
    assert call(db, 'status')['status'] == 'stopped'


def test_ui_preview_cannot_be_adopted_or_stopped(preview):
    db, folder, spawned, killed = preview
    ui = live.start(db, 'a', '')
    assert call(db, 'status')['status'] == 'stopped'
    assert call(db, 'stop')['status'] == 'stopped'
    with pytest.raises(HTTPException) as error:
        call(db, 'start')
    assert error.value.status_code == 409
    asyncio.run(worker.close_run('r1'))
    assert live.info('a')['url'] == ui['url'] and not killed


def test_runs_and_databases_cannot_share_ownership(preview):
    db, folder, spawned, killed = preview
    first = call(db, 'start')
    assert call(db, 'status', run='r2')['status'] == 'stopped'
    assert call(db, 'stop', run='r2')['status'] == 'stopped'
    with pytest.raises(HTTPException):
        call(db, 'start', run='r2')

    class OtherDatabase:
        def one(self, *args):
            return db.one(*args)
    other = OtherDatabase()
    assert call(other, 'status')['status'] == 'stopped'
    assert call(other, 'stop')['status'] == 'stopped'
    with pytest.raises(HTTPException):
        call(other, 'start')
    asyncio.run(worker.close_run('r2'))
    assert call(db, 'status')['url'] == first['url']
    asyncio.run(worker.close_run('r1'))
    assert len(killed) == 1


@pytest.mark.parametrize('operation', ['start', 'status', 'stop'])
def test_all_operations_reauthorize_and_internal_cleanup_works(preview, operation):
    db, folder, spawned, killed = preview
    call(db, 'start')
    set_policy(db, 'a', 'blocked', '')
    with pytest.raises(HTTPException):
        call(db, operation)
    assert not killed  # denied tool call cannot bypass authorization to stop
    asyncio.run(worker.close_run('r1'))
    assert len(killed) == 1


@pytest.mark.parametrize('operation', ['start', 'status', 'stop'])
def test_inactive_run_is_rejected(preview, operation):
    db, *_ = preview
    db.execute("UPDATE runs SET status='completed' WHERE id='r1'")
    with pytest.raises(HTTPException):
        call(db, operation)


def test_bound_workspace_is_required_even_for_non_autonomous_run(preview):
    db, *_ = preview
    add_run(db, 'a', 'legacy', autonomous=0)
    with pytest.raises(HTTPException, match='vinculado'):
        call(db, 'start', run='legacy')


def test_wrong_user_is_rejected(preview):
    db, *_ = preview
    with pytest.raises(HTTPException) as error:
        asyncio.run(worker.execute(db, 'b', 'r1', {'action': 'preview', 'operation': 'status'}))
    assert error.value.status_code == 404


def test_host_organization_policy_is_enforced(preview):
    from central.organizations import create_organization
    db, folder, spawned, killed = preview
    org = create_organization(db, 'a', 'Team')
    team_folder = folder.parent / 'team-workspace'
    team_folder.mkdir()
    (team_folder / 'package.json').write_text((folder / 'package.json').read_text())
    set_policy(db, 'a', 'full', str(team_folder))
    add_run(db, 'a', 'team', org)
    bind_run(db, 'a', 'team', org)
    with pytest.raises(HTTPException, match='administrador'):
        call(db, 'start', run='team')
    assert not spawned
    db.execute('UPDATE organizations SET host_commands_enabled=1 WHERE id=?', (org,))
    assert call(db, 'start', run='team')['status'] == 'running'


def test_cwd_and_actual_session_folder_must_match(preview):
    db, folder, *_ = preview
    call(db, 'start', cwd='client')
    for operation in ('start', 'status', 'stop'):
        with pytest.raises(HTTPException, match='cwd'):
            call(db, operation, cwd='')
    live._SESSIONS['a']['folder'] = str(folder / 'client')
    with pytest.raises(HTTPException, match='workspace'):
        call(db, 'status')


def test_cleanup_never_stops_replacement_ui_session(preview):
    db, folder, spawned, killed = preview
    call(db, 'start')
    live.stop('a')
    ui = live.start(db, 'a', 'client')
    asyncio.run(worker.close_run('r1'))
    assert live.info('a')['url'] == ui['url']
    assert len(killed) == 1


def test_host_environment_and_ttl(preview, monkeypatch):
    db, folder, spawned, killed = preview
    monkeypatch.setenv('OPENAI_API_KEY', 'secret')
    monkeypatch.setenv('DATABASE_URL', 'secret')
    monkeypatch.setenv('NODE_OPTIONS', '--require evil.js')
    monkeypatch.setenv('NPM_CONFIG_USERCONFIG', 'evil.npmrc')
    call(db, 'start')
    env = spawned[0][1]['env']
    assert not {'OPENAI_API_KEY', 'DATABASE_URL', 'NODE_OPTIONS', 'NPM_CONFIG_USERCONFIG'} & env.keys()
    assert env['HOST'] == '127.0.0.1' and env['BROWSER'] == 'none'
    old = live._SESSIONS['a']
    timer = old['timer']
    assert timer.seconds == 1800
    timer.fn(*timer.args)
    assert len(killed) == 1
    call(db, 'start')
    timer.fn(*timer.args)
    assert len(killed) == 1 and live.info('a')['status'] == 'running'


def test_concurrent_host_starts_spawn_only_once(preview):
    db, folder, spawned, killed = preview
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(live.start, db, 'a', '') for _ in range(2)]
        assert all(f.result()['status'] == 'running' for f in futures)
    assert len(spawned) == 1


def test_status_info_revokes_host_session_after_run_ends(preview):
    db, folder, spawned, killed = preview
    call(db, 'start')
    db.execute("UPDATE runs SET status='cancelled' WHERE id='r1'")
    assert live.info('a')['status'] == 'stopped'
    assert len(killed) == 1


def test_cancellation_during_start_cleans_up(preview, monkeypatch):
    db, folder, spawned, killed = preview
    entered, release = threading.Event(), threading.Event()
    original = live.start

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(live, 'start', delayed)

    async def scenario():
        task = asyncio.create_task(worker.execute(db, 'a', 'r1', {'action': 'preview', 'operation': 'start'}))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert len(killed) == 1 and not live._SESSIONS and not worker._OWNED


def test_instructions_document_the_gateway_contract():
    instruction = worker.worker_instruction()
    assert all(word in instruction for word in ('start', 'status', 'stop', 'URL', 'cwd', 'gateway'))



@pytest.mark.parametrize('status', ['completed', 'cancelled', 'failed', 'paused_limit'])
def test_terminal_run_cannot_keep_preview_alive(preview, status):
    db, folder, spawned, killed = preview
    call(db, 'start')
    db.execute('UPDATE runs SET status=? WHERE id=?', (status, 'r1'))
    assert live.info('a')['status'] == 'stopped' and len(killed) == 1
    for operation in ('start', 'status', 'stop'):
        with pytest.raises(HTTPException):
            call(db, operation)
    asyncio.run(worker.close_run('r1'))
    assert len(killed) == 1


@pytest.mark.skipif(_NODE is None, reason='Node.js not installed')
@pytest.mark.parametrize('script, expected', [
    ('const broken = ;', 'SyntaxError'),
    ("throw new Error('server startup failed: EADDRINUSE')", 'EADDRINUSE'),
])
def test_real_node_startup_failure_reports_bounded_diagnostics(preview, monkeypatch, script, expected):
    db, folder, spawned, killed = preview
    captured = {}
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-reach-node')

    def spawn(args, **kwargs):
        captured.update(kwargs)
        process = _REAL_POPEN([_NODE, '-e', script], **kwargs)
        # Small, failing programs cannot fill the pipe; ensure a real Node exit
        # before readiness can mistake another listener for this server.
        process.wait(timeout=5)
        captured['process'] = process
        return process

    monkeypatch.setattr(live.subprocess, 'Popen', spawn)
    with pytest.raises(HTTPException) as error:
        call(db, 'start')
    assert error.value.status_code == 422
    assert expected in error.value.detail
    assert 'Saida recente de npm dev:' in error.value.detail
    assert len(error.value.detail) <= live._LOG_PREVIEW + 200
    assert captured['stdout'] == subprocess.PIPE and captured['stderr'] == subprocess.STDOUT
    assert 'OPENAI_API_KEY' not in captured['env']
    assert captured['process'].stdout.closed and not live._SESSIONS


def _pipe_capture():
    read_fd, write_fd = os.pipe()
    process = Process()
    process.stdout = os.fdopen(read_fd, 'rb', buffering=0)
    return process, write_fd, live._PreviewLogs(process)


def test_log_tail_is_bounded_and_sanitized():
    process, write_fd, logs = _pipe_capture()
    try:
        for _ in range(40):
            os.write(write_fd, b'x' * 1024)
        os.write(write_fd, b'\n\x1b[31mSyntaxError: broken server\x1b[0m\x00\n')
    finally:
        os.close(write_fd)
    logs.thread.join(timeout=5)
    assert not logs.thread.is_alive()
    assert process.stdout.closed
    assert len(logs.tail) <= live._LOG_BYTES
    assert len(logs.recent()) <= live._LOG_PREVIEW
    assert logs.recent().endswith('SyntaxError: broken server\n')
    assert '\x1b' not in logs.recent() and '\x00' not in logs.recent()


def test_logs_are_opt_in_and_never_added_to_worker_audit(preview):
    db, folder, spawned, killed = preview
    call(db, 'start')
    entry = live._SESSIONS['a']
    process, write_fd, logs = _pipe_capture()
    try:
        os.write(write_fd, b'private project diagnostic')
    finally:
        os.close(write_fd)
    logs.thread.join(timeout=5)
    entry['logs'] = logs
    assert 'recent_logs' not in live.info('a')
    assert live.info('a', include_logs=True)['recent_logs'] == 'private project diagnostic'
    status = call(db, 'status')
    assert 'recent_logs' not in status and 'private' not in status['output']
    set_policy(db, 'a', 'blocked', '')
    assert live.info('a', include_logs=True) == {'status': 'stopped'}


def test_concurrent_stop_closes_capture_even_if_descendant_keeps_pipe_open(preview):
    db, folder, spawned, killed = preview
    call(db, 'start')
    entry = live._SESSIONS['a']
    process, write_fd, logs = _pipe_capture()
    entry['logs'] = logs
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(live.stop, 'a', expected=entry) for _ in range(2)]
            assert all(f.result(timeout=3)['status'] == 'stopped' for f in futures)
        assert not logs.thread.is_alive() and process.stdout.closed
        assert len(killed) == 1
        live.stop('a', expected=entry)  # idempotent
    finally:
        os.close(write_fd)


def test_startup_logs_not_returned_after_authorization_revocation(preview, monkeypatch):
    db, folder, spawned, killed = preview
    process, write_fd, logs = _pipe_capture()
    os.write(write_fd, b'diagnostic not for a revoked caller')
    os.close(write_fd)
    logs.thread.join(timeout=5)
    original = live._PreviewLogs

    def revoked(proc):
        set_policy(db, 'a', 'blocked', '')
        return logs

    def spawn(*args, **kwargs):
        # stdout presence starts capture; fake process is already dead.
        proc = Process()
        proc.code = 1
        proc.stdout = object()
        return proc

    monkeypatch.setattr(live.subprocess, 'Popen', spawn)
    monkeypatch.setattr(live, '_PreviewLogs', revoked)
    with pytest.raises(HTTPException) as error:
        call(db, 'start')
    assert error.value.status_code == 403
    assert 'diagnostic not for' not in error.value.detail
    assert not live._SESSIONS
