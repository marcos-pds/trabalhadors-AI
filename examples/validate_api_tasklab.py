"""Operator lab using configured API providers, never Codex/native runtimes.

Creates no application source. Workers must generate TaskLab themselves. Source
credentials stay in memory; production SQLite is opened read-only by the bridge.
Worktree promotion and dependency installs require concrete operator decisions.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
ROLES = ('architecture', 'backend', 'frontend', 'code', 'review')


def brief():
    protocol = (ROOT / 'docs/ACEITACAO-FULLSTACK-INDEPENDENTE.md').read_text(encoding='utf-8')
    prompt = '\n'.join(line[2:] for line in protocol.splitlines() if line.startswith('> '))
    if not prompt.strip():
        raise ValueError('Acceptance brief is missing.')
    return prompt


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def state_at(destination):
    state = json.loads((destination / 'state.json').read_text(encoding='utf-8'))
    if state.get('schema_version') != 1 or state.get('codex_allowed') is not False:
        raise ValueError('Invalid lab state; Codex must remain excluded.')
    return state


def connect(destination):
    from central.database import Database
    data = destination / 'data'
    if not (data / 'central.sqlite3').is_file():
        raise ValueError('Existing lab database required.')
    return Database(data / 'central.sqlite3'), data


def providers(args):
    from central.acceptance_providers import SourceProviders
    return SourceProviders.load(args.source_data, user_id=args.source_user)


async def prepare(args):
    from central.database import Database, uid, utcnow
    from central.security import Security
    from central.engine import Engine
    from central.organizations import ensure_personal
    from central.computer_access import set_policy
    from central.addon_catalog import Catalog
    source = providers(args)
    descriptors = source.descriptors
    if not descriptors:
        raise ValueError('No authorized API providers available.')
    destination = args.destination
    destination.mkdir(parents=True, exist_ok=False)
    data, workspace = destination / 'data', destination / 'workspace'
    data.mkdir(); workspace.mkdir()
    # Only harness metadata, never implementation code or acceptance fixtures.
    (workspace / '.gitignore').write_text('node_modules/\n.venv/\n__pycache__/\n*.sqlite3\n.central-*/\n', encoding='utf-8')
    (workspace / 'README.md').write_text('# TaskLab\nWorkspace de laboratorio. Aplicacao ainda nao criada.\n', encoding='utf-8')
    for command in (['git', 'init', '--quiet'], ['git', 'add', '.gitignore', 'README.md'],
                    ['git', '-c', 'user.name=Central Acceptance', '-c', 'user.email=acceptance@example.test',
                     'commit', '--quiet', '-m', 'Initialize empty acceptance workspace']):
        subprocess.run(command, cwd=workspace, check=True, capture_output=True)
    db = Database(data / 'central.sqlite3')
    try:
        security = Security(db, data)
        now, user, project, chat = utcnow(), 'api-lab-operator', uid(), uid()
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, 'api-lab@example.test', 'no-login', now))
        org = ensure_personal(db, user)
        db.execute('INSERT INTO projects(id,user_id,name,description,created_at) VALUES(?,?,?,?,?)',
                   (project, user, 'TaskLab API acceptance', 'Isolated real-provider lab; no Codex.', now))
        db.execute('INSERT INTO organization_projects VALUES(?,?)', (project, org))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', (chat, user, 'TaskLab', project, now, now))
        for index, descriptor in enumerate(descriptors):
            db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,priority,created_at) VALUES(?,?,?,?,?,?,?,?)',
                       (descriptor['id'], user, 'API lab ' + descriptor['kind'], descriptor['kind'],
                        descriptor['base_url'], descriptor['model'], index, now))
        preferred = next((p for p in descriptors if p['kind'] == 'groq' and 'qwen' in p['model'].lower()), descriptors[0])
        instructions = {
            'architecture': 'Planeje sem editar. Crie uma subtarefa real via delegate_task para recipient_agent_id code, '
                'request_id tasklab-integration, title Testes de integracao, instructions Criar testes reais de integracao e corrigir falhas apos frontend/backend. '
                'Depois finalize seu planejamento. Nao simule delegacao em texto.',
            'backend': 'Implemente a API e um frontend minimo executavel para validar a integracao. '
                'Crie backend/main.py e frontend/src/App.tsx. Organize npm run dev na raiz para iniciar a aplicacao local '
                'e encaminhar /api para o backend. Use as ferramentas e teste o site real.',
            'frontend': 'Leia o que o backend entregou e complete a interface responsiva React/TypeScript. '
                'Preserve os contratos API e os testids do brief. Teste os controles reais e corrija falhas.',
            'code': 'Implemente testes reais para os fluxos de autenticacao, equipes e tarefas; corrija os erros encontrados.',
            'review': 'Revise o projeto integrado, rode build e testes novamente e faca QA no navegador desktop e mobile. '
                'Nao considere evidencias anteriores a ultima promocao suficientes. Nao declare sucesso sem testes reais.',
        }
        for role in ROLES:
            db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,provider_id,model,created_at) VALUES(?,?,?,?,?,?,?,?)',
                       (role, user, 'TaskLab ' + role, role, instructions[role], preferred['id'], preferred['model'], now))
        set_policy(db, user, 'full', str(workspace))
        catalog = Catalog(db, security)
        pending = catalog.preview(user, 'mcp', 'server.json', (ROOT / 'examples/chrome-devtools/server.json').read_bytes())
        resource = catalog.confirm(user, pending['preview_id'], pending['confirmation'])
        catalog.state(user, resource['id'], 'active', resource['sha256'])
        nodes = []
        for role in ('architecture', 'backend', 'frontend', 'review'):
            nodes.append({'id': role, 'kind': 'agent', 'agent_id': role, 'name': role,
                          'deps': [nodes[-1]['id']] if nodes else [], 'instructions': instructions[role]})
        engine = Engine(db, security, client=source.client(max_calls=args.max_calls))
        rid = engine.create_run(user, chat, brief(), 'team', flow={'nodes': nodes},
                                autonomous=True, isolate_workers=True, idempotency_key='tasklab-api-01')
        state = {'schema_version': 1, 'codex_allowed': False, 'user_id': user, 'run_id': rid,
                 'source_user': args.source_user, 'providers': descriptors,
                 'prompt_mode': 'detailed_acceptance_brief', 'application_source_written_by_harness': False}
        save(destination / 'state.json', state)
        print(json.dumps({'prepared': True, 'run_id': rid, 'codex_allowed': False, 'providers': descriptors}, ensure_ascii=False))
    finally:
        db.close()


def snapshot(db, state):
    rid = state['run_id']
    return {'run': db.one('SELECT id,status,error FROM runs WHERE id=?', (rid,)),
            'steps': db.all('SELECT id,agent_id,status,error FROM steps WHERE run_id=?', (rid,)),
            'pending_approvals': db.all("SELECT id,folder,request_json FROM workspace_action_approvals WHERE run_id=? AND status='pending'", (rid,)),
            'workspaces': db.all('SELECT step_id,state FROM isolated_workspace_steps WHERE run_id=?', (rid,))}


async def process(args):
    from central.engine import Engine
    from central.security import Security
    from central.approval_engine import decide
    from central import live_preview, browser_mcp, worker_preview
    state = state_at(args.destination)
    if args.source_user is None:
        args.source_user = state.get('source_user')
    source = providers(args)
    if state['providers'] != source.descriptors:
        raise ValueError('Provider selection changed; explicit new lab required.')
    db, data = connect(args.destination)
    engine = Engine(db, Security(db, data), client=source.client(max_calls=args.max_calls))
    original = engine.emit
    rid, user = state['run_id'], state['user_id']

    def emit(run_id, kind, payload):
        original(run_id, kind, payload)
        if kind in ('run_status', 'step_status', 'model_selected', 'workspace_approval_required', 'workspace_validation'):
            print(json.dumps({'event': kind, 'run_id': run_id, **payload}, ensure_ascii=False), flush=True)
        if kind != 'workspace_approval_required':
            return
        row = db.one('SELECT request_json FROM workspace_action_approvals WHERE id=?', (payload['approval_id'],))
        request = json.loads(row['request_json'])
        allowed = run_id == rid and request['action'] == 'preview' and request.get('operation') == 'start'
        if request['action'] == 'browser_tool' and run_id == rid:
            allowed = True
            url = request.get('arguments', {}).get('url')
            if url:
                base = live_preview.info(user).get('url', '')
                parsed, expected = urlsplit(url), urlsplit(base)
                allowed = bool(base) and (parsed.scheme, parsed.hostname, parsed.port) == (expected.scheme, expected.hostname, expected.port)
        if allowed:
            decide(db, user, rid, payload['approval_id'], True)
            original(rid, 'test_operator_approval', {'approval_id': payload['approval_id'], 'policy': 'isolated_local_preview_browser_only', 'approved': True})
        # Other approvals stay pending for concrete operator review.

    engine.emit = emit
    try:
        current = db.one('SELECT status FROM runs WHERE id=?', (rid,))['status']
        if current in ('failed', 'cancelled', 'paused_limit', 'paused_operator', 'awaiting_integration'):
            engine.resume_run(rid)
        try:
            await asyncio.wait_for(engine.process(rid), timeout=args.timeout)
        except asyncio.TimeoutError:
            engine.cancel(rid)
            print(json.dumps({'time_limit_reached': True, 'run_id': rid}), flush=True)
        result = snapshot(db, state)
        result['api_calls_this_segment'] = engine.client.calls
        result['independent_acceptance_complete'] = False
        save(args.destination / 'latest.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0 if result['run']['status'] == 'completed' else 2
    finally:
        await browser_mcp.close_run(rid)
        await worker_preview.close_run(rid)
        db.close()


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run', 'status', 'review', 'approve', 'approve-action'))
    parser.add_argument('destination', type=Path)
    parser.add_argument('--source-data', type=Path)
    parser.add_argument('--source-user')
    parser.add_argument('--max-calls', type=int, default=120)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--step-id')
    parser.add_argument('--confirmation')
    parser.add_argument('--approval-id')
    args = parser.parse_args(argv)
    args.destination = args.destination.resolve()
    if not 1 <= args.max_calls <= 200 or not 1 <= args.timeout <= 1800:
        parser.error('max-calls 1..200; timeout 1..1800')
    if args.action in ('prepare', 'run') and not args.source_data:
        parser.error('--source-data is required; keys must not be supplied as CLI arguments')
    os.environ['CENTRAL_DATA_DIR'] = str(args.destination / 'data')
    os.environ['CENTRAL_JOB_MODE'] = 'api'
    if args.action == 'prepare':
        return await prepare(args)
    if args.action == 'run':
        return await process(args)
    state = state_at(args.destination)
    db, data = connect(args.destination)
    try:
        if args.action == 'status':
            result = snapshot(db, state)
        elif args.action in ('review', 'approve'):
            from central import isolated_workspaces
            if not args.step_id:
                parser.error('--step-id is required')
            if args.action == 'review':
                result = isolated_workspaces.review(db, state['user_id'], state['run_id'], args.step_id)
            else:
                if not args.confirmation:
                    parser.error('--confirmation from a reviewed diff is required')
                from central.engine import Engine
                from central.security import Security
                result = isolated_workspaces.approve(db, state['user_id'], state['run_id'], args.step_id, args.confirmation)
                Engine(db, Security(db, data)).finish_promoted_step(state['run_id'], args.step_id)
        else:
            from central.approval_engine import decide
            if not args.approval_id:
                parser.error('--approval-id of the inspected request is required')
            decide(db, state['user_id'], state['run_id'], args.approval_id, True)
            result = {'approved': True, 'approval_id': args.approval_id}
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()) or 0)
    except Exception as exc:
        # CLI output must never include source credential or response bodies.
        print(json.dumps({'failed': True, 'error_type': type(exc).__name__}), flush=True)
        raise SystemExit(1)
