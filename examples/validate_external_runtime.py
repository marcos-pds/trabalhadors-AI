"""Real, bounded CLI worker + reviewer against an operator-injected Python bug.

Reads one authorized API source read-only. Keys live only in memory and child
environment, never in the lab DB. Does not use Codex or repair generated code.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys


async def validate(args):
    from cryptography.fernet import Fernet
    from central.acceptance_providers import SourceProviders
    from central.database import Database, utcnow
    from central.engine import Engine
    from central.security import Security
    from central.computer_access import set_policy
    from central.organizations import ensure_personal
    from central.providers import ProviderClient
    from central.worker_checkpoint import WorkerPaused
    from central.task_contract import delivery_evidence
    kinds = {'claude': {'anthropic'}, 'gemini': {'gemini'}, 'acp': {'gemini'}, 'opencode': {args.source_kind}}
    source = SourceProviders.load(args.source_data, user_id=args.source_user, kinds=kinds[args.runtime])
    selected = next(iter(source._selected.values()))
    key = Fernet((args.source_data / 'secret.key').read_bytes()).decrypt(selected.ciphertext.encode()).decode()
    model = (('google' if args.source_kind == 'gemini' else args.source_kind) + '/' + selected.model) if args.runtime == 'opencode' else selected.model
    kind = {'claude': 'claude_cli', 'gemini': 'gemini_cli', 'opencode': 'opencode_cli', 'acp': 'acp'}[args.runtime]
    if args.runtime == 'acp':
        os.environ['CENTRAL_ACP_BACKEND'] = 'gemini'
    destination = args.destination.resolve()
    data, workspace = destination / 'data', destination / 'workspace'
    previous = None
    if args.resume:
        previous = json.loads((destination / 'report.json').read_text(encoding='utf-8'))
        if previous.get('runtime') != args.runtime or previous.get('model') != model or not (data / 'central.sqlite3').is_file():
            raise ValueError('Resume requires the original runtime, model and lab database.')
    else:
        destination.mkdir(parents=True, exist_ok=False)
        data.mkdir(); workspace.mkdir()
    os.environ['CENTRAL_DATA_DIR'] = str(data)
    os.environ['CENTRAL_JOB_MODE'] = 'api'
    if not args.resume:
        (workspace / 'app.py').write_text('def somar(a, b):\n    return a - b\n', encoding='utf-8')
        (workspace / 'test_app.py').write_text('from app import somar\ndef test_somar():\n    assert somar(3, 2) == 5\n    assert somar(-1, 1) == 0\n', encoding='utf-8')
    calls = []
    class Client:
        async def stream(self, provider, ignored_key, chosen_model, system, messages):
            if provider['kind'] != kind or chosen_model != model:
                raise RuntimeError('Unexpected runtime selection')
            if len(calls) >= args.max_calls:
                raise WorkerPaused('Limite de invocacoes CLI deste ensaio.')
            calls.append(kind)
            async for text in ProviderClient().stream(provider, key, chosen_model, system, messages):
                yield text
    db = Database(data / 'central.sqlite3')
    security = Security(db, data)
    now, user, chat = utcnow(), 'runtime-operator', 'runtime-chat'
    if not args.resume:
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, 'runtime@example.test', 'no-login', now))
        ensure_personal(db, user)
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', (chat, user, 'Runtime lab', None, now, now))
        db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) VALUES(?,?,?,?,?,?,?)',
               ('runtime', user, args.runtime, kind, 'runtime://' + args.runtime, model, now))
    for role in ('code', 'review'):
        if args.resume:
            break
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,provider_id,model,created_at) VALUES(?,?,?,?,?,?,?,?)',
                   (role, user, role, role, 'Use JSON de acoes da Central. Leia os arquivos, use replace com SHA e valide. Nao use ferramentas nativas do CLI.', 'runtime', model, now))
    if not args.resume:
        set_policy(db, user, 'full', str(workspace))
    engine = Engine(db, security, client=Client())
    rid = previous['run_id'] if previous else engine.create_run(user, chat,
        'Corrija a funcao somar(a,b) em app.py para retornar a soma dos dois numeros. '
        'Leia os testes existentes, preserve o contrato e execute os testes reais. Nao crie outro projeto.',
        'manual', agent_ids=['code', 'review'], autonomous=True)
    report = {'runtime': args.runtime, 'model': model, 'run_id': rid, 'codex_used': False,
              'operator_injected_defect': True, 'operator_application_repairs': 0}
    try:
        if args.resume:
            engine.resume_run(rid)
        try:
            await asyncio.wait_for(engine.process(rid), timeout=args.timeout)
        except asyncio.TimeoutError:
            engine.cancel(rid)
        run = db.one('SELECT status,error FROM runs WHERE id=?', (rid,))
        proof = delivery_evidence(db, rid)
        checked = subprocess.run([sys.executable, '-I', '-c',
            'import importlib.util,sys; s=importlib.util.spec_from_file_location("app",sys.argv[1]); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
            'assert m.somar(3,2)==5; assert m.somar(-1,1)==0; assert m.somar(0,0)==0',
            str(workspace / 'app.py')], capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        report.update(run=run, cli_invocations=len(calls), evidence=proof,
                      independent_functional_check=checked.returncode == 0,
                      passed=run['status']=='completed' and checked.returncode == 0
                             and proof['tests_passed'] and proof['validation_after_last_change'])
        with (destination / 'attempts.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(report, ensure_ascii=False) + '\n')
        (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 0 if report['passed'] else 2
    finally:
        key = None
        from central.browser_mcp import close_run
        from central.worker_preview import close_run as close_preview
        await close_run(rid); await close_preview(rid)
        db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime',choices=('claude','gemini','opencode','acp'))
    parser.add_argument('destination',type=Path)
    parser.add_argument('--source-data',type=Path,required=True)
    parser.add_argument('--source-user')
    parser.add_argument('--source-kind', choices=('groq','gemini','anthropic','openai','openrouter'), default='groq')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--max-calls',type=int,default=12)
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    if not 1<=args.max_calls<=40 or not 1<=args.timeout<=600:
        parser.error('max-calls 1..40; timeout 1..600')
    try:
        return asyncio.run(validate(args))
    except Exception as exc:
        print(json.dumps({'failed':True,'error_type':type(exc).__name__}),flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
