"""Exercise a real three-worker graph using an already running local Ollama.

No external provider, production DB or credentials. Keeps the resulting SQLite
journal in the supplied new directory for inspection. This is a collaboration
test, not proof of complete application generation.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path

from central.database import Database, utcnow
from central.engine import Engine
from central.security import Security


async def validate(destination, model, project=False, runtime='ollama', pause_test=False):
    destination.mkdir(parents=True, exist_ok=False)
    os.environ['CENTRAL_JOB_MODE'] = 'api'
    db = Database(destination / 'central.sqlite3')
    security = Security(db, destination)
    engine = Engine(db, security)
    now = utcnow()
    db.execute('INSERT INTO users VALUES(?,?,?,?)', ('local-test', 'team@example.test', 'no-login', now))
    from central.organizations import ensure_personal
    ensure_personal(db, 'local-test')
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', ('chat', 'local-test', 'Local team', None, now, now))
    db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,input_price,output_price,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
               ('ollama', 'local-test', 'Codex CLI' if runtime == 'codex' else 'Ollama local',
                'codex_cli' if runtime == 'codex' else 'ollama',
                'codex://local' if runtime == 'codex' else 'http://127.0.0.1:11434/v1', model,
                None if runtime == 'codex' else 0, None if runtime == 'codex' else 0, now))
    nodes = []
    for index, role in enumerate(('code', 'review') if project else ('architecture', 'code', 'review')):
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,provider_id,model,created_at) VALUES(?,?,?,?,?,?,?,?)',
                   (role, 'local-test', role, role,
                    'Implemente arquivos completos e pequenos. Use ferramentas para verificar o resultado.' if project else
                    'Responda em português em até 40 palavras. Use o resultado anterior quando disponível.', 'ollama', model, now))
        nodes.append({'id': role, 'kind': 'agent', 'agent_id': role, 'name': role,
                      'deps': [nodes[-1]['id']] if nodes else [], 'instructions': ''})
    try:
        if project:
            from central.computer_access import set_policy
            workspace = destination / 'workspace'
            workspace.mkdir()
            set_policy(db, 'local-test', 'full', str(workspace))
        if pause_test:
            import central.agent_autonomy as autonomy
            autonomy.MAX_ROUNDS = 2
        prompt = ('Crie uma aplicação simples em um único arquivo server.py, usando somente a biblioteca padrão Python. '
                  'Sirva em 127.0.0.1:8891 uma página HTML responsiva com título Central IA, botão Contar e contador '
                  'que aumenta ao clicar com JavaScript. O backend deve responder GET /api/health com JSON {"ok":true}. '
                  'Use HTTPServer e BaseHTTPRequestHandler. Execute python_compile e finalize após validar os arquivos.'
                  if project else
                  'Explique conceitualmente como testar um contador de cliques, sem editar arquivos: '
                  'arquiteto define o critério, programador descreve a lógica, revisor avalia o resultado.')
        run_id = engine.create_run('local-test', 'chat',
            prompt, 'manual' if project else 'team', flow={'nodes': nodes}, autonomous=project)
        await asyncio.wait_for(engine.process(run_id), timeout=480 if project else 240)
        run = db.one('SELECT status,error FROM runs WHERE id=?', (run_id,))
        messages = db.all('SELECT message_type,state,sender_agent_id,recipient_agent_id FROM agent_messages WHERE run_id=?', (run_id,))
        result = {'run_id': run_id, 'run': run, 'messages': messages,
                  'completed_steps': db.one("SELECT COUNT(*) n FROM steps WHERE run_id=? AND status='completed'", (run_id,))['n']}
        print(json.dumps(result, ensure_ascii=False))
        if pause_test and run['status'] == 'paused_limit':
            print('Checkpoint persisted; resume this directory in a NEW Python process with --resume.')
            return
        if project:
            from central.task_contract import delivery_evidence
            print(json.dumps(delivery_evidence(db, run_id), ensure_ascii=False))
        if (run['status'] != 'completed' or result['completed_steps'] != (2 if project else 3)
                or (not project and (len(messages) != 2 or any(m['state'] != 'delivered' for m in messages)))):
            raise RuntimeError('Real team validation did not satisfy collaboration checks')
    finally:
        db.close()


async def resume(destination):
    os.environ['CENTRAL_JOB_MODE'] = 'api'
    db = Database(destination / 'central.sqlite3')
    engine = Engine(db, Security(db, destination))
    try:
        run = db.one('SELECT * FROM runs ORDER BY created_at DESC LIMIT 1')
        if not run or run['status'] not in ('paused_limit', 'failed'):
            raise RuntimeError('This recovery check requires a paused run')
        before = db.one("SELECT COUNT(*) n FROM events WHERE event='workspace_action_result'")['n']
        engine.resume_run(run['id'])
        await asyncio.wait_for(engine.process(run['id']), timeout=480)
        result = db.one('SELECT status,error FROM runs WHERE id=?', (run['id'],))
        print(json.dumps({'run_id': run['id'], 'run': result, 'prior_action_events': before,
                          'native_resumes': db.one("SELECT COUNT(*) n FROM events WHERE event='native_session_resumed'")['n']}, ensure_ascii=False))
        if result['status'] != 'completed':
            raise RuntimeError('Real cross-process recovery failed')
    finally:
        db.close()


async def adjust(destination, prompt):
    """Test a short request against the actual previous project, without patches."""
    os.environ['CENTRAL_JOB_MODE'] = 'api'
    db = Database(destination / 'central.sqlite3')
    engine = Engine(db, Security(db, destination))
    try:
        previous = db.one('SELECT * FROM runs ORDER BY created_at DESC LIMIT 1')
        if not previous or previous['status'] != 'completed':
            raise RuntimeError('Finish the previous project before testing a short adjustment')
        run_id = engine.create_run(previous['user_id'], previous['conversation_id'], prompt,
                                   'manual', agent_ids=['code', 'review'], autonomous=True)
        await asyncio.wait_for(engine.process(run_id), timeout=480)
        result = db.one('SELECT status,error FROM runs WHERE id=?', (run_id,))
        print(json.dumps({'run_id': run_id, 'prompt': prompt, 'run': result}, ensure_ascii=False))
        if result['status'] != 'completed':
            raise RuntimeError('The actual short-request adjustment did not finish')
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--model', default='qwen2.5-coder:3b')
    parser.add_argument('--project', action='store_true')
    parser.add_argument('--runtime', choices=('ollama', 'codex'), default='ollama')
    parser.add_argument('--pause-test', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--adjust', type=str)
    args = parser.parse_args()
    if args.adjust:
        asyncio.run(adjust(args.destination, args.adjust))
    elif args.resume:
        asyncio.run(resume(args.destination))
    else:
        asyncio.run(validate(args.destination, args.model, args.project, args.runtime, args.pause_test))
