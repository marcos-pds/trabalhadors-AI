"""End-to-end resumable worker checkpoints and pause/continue regression tests."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from central.agent_autonomy import autonomous_worker
from central.computer_access import set_policy
from central.database import Database, utcnow
from central.engine import Engine
from central.worker_checkpoint import WorkerPaused, load_checkpoint, checkpoint_summary, MAX_RESUMES
import hashlib


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'hello.py').write_bytes(b"print('old')\n")
    db = Database(':memory:')
    db.execute('INSERT INTO users VALUES(?,?,?,?)',
               ('user', 'u@example.com', 'hash', utcnow()))
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
               ('convo', 'user', 'Teste', None, utcnow(), utcnow()))
    db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
               ('run', 'user', 'convo', 'Corrigir', 'running', 'manual', '[]', '[]', utcnow(), utcnow()))
    db.execute('INSERT INTO steps(id,run_id,agent_id,kind,name,deps,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
               ('step', 'run', None, 'agent', 'Programador', '[]', 'running', utcnow(), utcnow()))
    yield db, root
    db.close()


def h(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class FakeModel:
    def __init__(self, answers):
        self.answers = list(answers)
        self.seen = []

    async def stream(self, provider, key, model, system, messages):
        self.seen.append((system, messages))
        yield self.answers.pop(0)


def calls_until_pause():
    actions = [
        {'action': 'read', 'path': 'hello.py'},
        {'action': 'replace', 'path': 'hello.py', 'old': "print('old')",
         'new': "print('new')", 'expected_sha256': h("print('old')\n")},
    ]
    actions.extend({'action': 'read', 'path': 'hello.py'} for _ in range(10))
    return [json.dumps(item) for item in actions]


def test_checkpoint_survives_worker_restart_and_never_replays_file_edit(workspace):
    db, folder = workspace
    set_policy(db, 'user', 'full', str(folder))
    first = FakeModel(calls_until_pause())
    events = []
    with pytest.raises(WorkerPaused, match='Pausado|pausado'):
        asyncio.run(autonomous_worker(
            first, db, 'user', 'run', 'step', {'kind': 'openai'},
            'key', 'mock', 'Implementador', [{'role':'user','content':'Corrija hello.py'}],
            lambda *args: events.append(args), require_code_changes=True))
    assert (folder / 'hello.py').read_bytes() == b"print('new')\n"
    saved = load_checkpoint(db, 'user', 'run', 'step', str(folder))
    assert saved['state'] == 'paused_limit'
    assert saved['rounds_total'] == 12
    assert saved['actions_total'] == 12
    assert saved['changed_files'] == ['hello.py']
    assert saved['last_action'] == 'read hello.py'
    assert checkpoint_summary(db, 'user', 'run')[0]['state'] == 'paused_limit'
    # Subsequent invocation restores the bounded tool transcript and already
    # modified file list. It must not attempt the stale edit for a second time.
    followup = FakeModel([json.dumps({'action': 'finish',
                                      'message': 'Arquivo ajustado, sem repetir edições.'})])
    result = asyncio.run(autonomous_worker(
        followup, db, 'user', 'run', 'step', {'kind': 'openai'},
        'key', 'mock', 'Implementador', [{'role':'user','content':'Não reinicie'}],
        lambda *args: events.append(args), require_code_changes=True))
    assert 'Validações executadas' in result
    assert (folder / 'hello.py').read_bytes() == b"print('new')\n"
    assert load_checkpoint(db, 'user', 'run', 'step', str(folder))['state'] == 'completed'
    assert any(event[1] == 'worker_checkpoint_restored' for event in events)


def test_checkpoint_scoped_to_owner_and_original_authorized_folder(workspace, tmp_path):
    db, folder = workspace
    set_policy(db, 'user', 'full', str(folder))
    first = FakeModel(calls_until_pause())
    with pytest.raises(WorkerPaused):
        asyncio.run(autonomous_worker(
            first, db, 'user', 'run', 'step', {'kind':'openai'}, 'key',
            'mock', 'Implementador', [{'role':'user','content':'Ajuste'}],
            lambda *args: None))
    assert load_checkpoint(db, 'unknown', 'run', 'step', str(folder)) is None
    other = tmp_path / 'new-workspace'
    other.mkdir()
    with pytest.raises(RuntimeError, match='pasta autorizada mudou'):
        load_checkpoint(db, 'user', 'run', 'step', str(other))


def test_engine_pauses_frontend_then_resumes_without_rerunning_architect(workspace):
    db, folder = workspace
    set_policy(db, 'user', 'full', str(folder))
    for id_, name, specialty in [
        ('architect', 'Arquiteto-Teste', 'architecture'),
        ('coder', 'Programador-Teste', 'code'),
        ('reviewer', 'Revisor-Teste', 'review')]:
        db.execute(
            'INSERT INTO agents(id,user_id,name,specialty,instructions,avatar,created_at) '
            'VALUES(?,?,?,?,?,?,?)',
            (id_, 'user', name, specialty, 'Faça seu trabalho.', '✦', utcnow()))
    db.execute(
        'INSERT INTO providers(id,user_id,name,kind,base_url,model,api_key_enc,created_at) '
        'VALUES(?,?,?,?,?,?,?,?)',
        ('p', 'user', 'Mock', 'openai', 'https://fake.test/v1',
         'test-model', 'encrypted', utcnow()))
    class Crypto:
        def decrypt(self, value):
            return 'key'

    model = FakeModel(
        [json.dumps({'action':'finish','message':'Arquitetura definida.'})] +
        calls_until_pause() +
        [json.dumps({'action':'finish','message':'Código implementado.'}),
         json.dumps({'action':'finish','message':'Revisão finalizada.'})])
    engine = Engine(db, Crypto(), model)

    async def until(rid, status):
        for _ in range(160):
            record = db.one('SELECT status,error FROM runs WHERE id=?', (rid,))
            if record and record['status'] == status:
                # Let the task callback retire before resuming.
                await asyncio.sleep(0.02)
                return record
            if record and record['status'] == 'failed':
                raise AssertionError(record['error'])
            await asyncio.sleep(0.02)
        raise AssertionError('Expected status not reached: ' + status)

    async def scenario():
        rid = engine.create_run('user', 'convo',
                                'Desenvolva um módulo de código com testes.',
                                'team', autonomous=True)
        paused = await until(rid, 'paused_limit')
        assert 'Limite' in paused['error'] or 'limite' in paused['error']
        stages = db.all('SELECT name,status FROM steps WHERE run_id=? ORDER BY rowid', (rid,))
        assert [x['status'] for x in stages] == ['completed', 'paused_limit', 'queued']
        checkpoint = checkpoint_summary(db, 'user', rid)
        assert checkpoint and checkpoint[0]['changed_files']
        assert (folder / 'hello.py').read_bytes() == b"print('new')\n"
        engine.resume_run(rid)
        finished = await until(rid, 'completed')
        assert finished['error'] is None
        after = db.all('SELECT name,status FROM steps WHERE run_id=? ORDER BY rowid', (rid,))
        assert [x['status'] for x in after] == ['completed', 'completed', 'completed']
        events = db.all('SELECT event FROM events WHERE run_id=? ORDER BY seq', (rid,))
        assert sum(x['event'] == 'step_status' for x in events) >= 6
        assert sum(x['event'] == 'run_paused_limit' for x in events) == 1
        assert sum(x['event'] == 'worker_checkpoint_restored' for x in events) == 1
        assert not any(x['event'] == 'run_failed' for x in events)
        assert len(model.seen) == 15
        return rid

    asyncio.run(scenario())


def test_explicit_continuation_is_capped(workspace):
    db, folder = workspace
    set_policy(db, 'user', 'full', str(folder))
    # A direct checkpoint with all continuation quota used: no model request.
    from central.worker_checkpoint import save_checkpoint
    save_checkpoint(db, 'user', 'run', 'step', str(folder),
                    [{'role':'user','content':'Trabalhe'}],
                    changed_files=[], observed_actions=[], validation_failures=0,
                    rounds_total=12, actions_total=12, state='paused_limit')
    db.execute('UPDATE worker_checkpoints SET resumes=? WHERE step_id=?',
               (MAX_RESUMES, 'step'))
    db.execute("UPDATE runs SET status='paused_limit' WHERE id='run'")
    from central.workspace_tools import reset_run_commands
    engine = Engine(db, None)
    with pytest.raises(ValueError, match='Limite'):
        engine.resume_run('run')



def test_nested_vite_application_uses_actual_build_instead_of_empty_python_compile(tmp_path):
    from central.workspace_tools import validation_commands
    root = tmp_path / 'granted'
    nested = root / 'nova-studio' / 'apps' / 'web'
    (nested / 'src').mkdir(parents=True)
    (nested / 'package.json').write_text(
        json.dumps({'name': 'nova-web', 'scripts': {'dev': 'vite', 'build': 'vite build'}}),
        encoding='utf-8')
    (nested / 'src' / 'App.tsx').write_text('export default null', encoding='utf-8')
    checks = validation_commands(str(root), changed_files=[
        'nova-studio/apps/web/src/App.tsx'])
    assert checks == [{'action': 'command', 'command': 'npm_build',
                       'cwd': 'nova-studio/apps/web'}]


def test_no_project_with_real_build_or_python_files_cannot_fake_validation(tmp_path):
    from central.workspace_tools import validation_commands
    root = tmp_path / 'empty-js'
    root.mkdir()
    (root / 'package.json').write_text(
        json.dumps({'scripts': {'dev': 'vite'}}), encoding='utf-8')
    with pytest.raises(RuntimeError, match='Nenhum build'):
        validation_commands(str(root))



def test_legacy_failed_run_recovers_real_previous_edits_without_replaying_them(workspace):
    db, folder = workspace
    set_policy(db, 'user', 'full', str(folder))
    # Simulate a pre-checkpoint task that wrote a file and failed on 12 cycles.
    (folder / 'hello.py').write_bytes(b"print('already done')\n")
    db.execute("UPDATE steps SET attempts=2,status='running' WHERE id='step'")
    db.event('run', 'workspace_action_result', {
        'step_id': 'step', 'success': True,
        'summary': {'action': 'replace', 'path': 'hello.py'}})
    db.event('run', 'worker_message', {
        'step_id': 'step', 'action': 'read', 'path': 'hello.py'})
    model = FakeModel([
        json.dumps({'action': 'finish', 'message': 'O código anterior foi preservado.'})])
    result = asyncio.run(autonomous_worker(
        model, db, 'user', 'run', 'step', {'kind': 'openai'},
        'key', 'mock', 'Implementador', [{'role':'user','content':'Conclua o trabalho'}],
        lambda *args: None, require_code_changes=True))
    assert 'Validações executadas' in result
    assert (folder / 'hello.py').read_bytes() == b"print('already done')\n"
    assert 'Progresso recuperado' in model.seen[0][1][1]['content']
