"""Create durable, bounded DAG stages while a user-authorized run is active.

The model selects an existing enabled worker, never invents an identity or grants
files, shell, browser, paid services or access to another project.
"""
import hashlib
import json
import re

from .database import uid, utcnow
from .agent_registry import effective_specialty
from .task_contract import is_implementation_request
from .workspace_guard import enforce_run_scope

MAX_DYNAMIC_STEPS = 8
MAX_TOTAL_STEPS = 32
MAX_DELEGATION_DEPTH = 4
CAN_DELEGATE = frozenset({
    'coordination', 'architecture', 'code', 'frontend', 'backend',
    'design', 'research', 'devops',
})

SCHEMA = (
    "CREATE TABLE dynamic_step_requests("
    "step_id TEXT PRIMARY KEY REFERENCES steps(id) ON DELETE CASCADE,"
    "run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,"
    "requester_step_id TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,"
    "request_id TEXT NOT NULL,"
    "request_hash TEXT NOT NULL,"
    "depth INTEGER NOT NULL CHECK(depth BETWEEN 1 AND 4),"
    "created_at TEXT NOT NULL,"
    "UNIQUE(run_id,requester_step_id,request_id))",
    "CREATE INDEX idx_dynamic_step_run ON dynamic_step_requests(run_id,created_at)",
)


def validate_command(command):
    required = {'action', 'recipient_agent_id', 'title', 'instructions', 'request_id'}
    if not isinstance(command, dict) or set(command) != required or command.get('action') != 'delegate_task':
        raise ValueError('Delegação exige action, recipient_agent_id, title, instructions e request_id.')
    if not isinstance(command['recipient_agent_id'], str) or not 1 <= len(command['recipient_agent_id']) <= 128:
        raise ValueError('ID de trabalhador destinatário inválido.')
    if not isinstance(command['title'], str) or not 3 <= len(command['title'].strip()) <= 100:
        raise ValueError('Título de subtarefa inválido.')
    if not isinstance(command['instructions'], str) or not 10 <= len(command['instructions'].strip()) <= 2500:
        raise ValueError('Instruções de subtarefa inválidas.')
    if not isinstance(command['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{5,80}', command['request_id']):
        raise ValueError('request_id deve ser estável, com 5-80 letras, números, _ ou -.')
    return command


def _ancestors(step_id, steps):
    """Reachable prerequisite steps; rejects corrupt cycles or missing IDs."""
    seen, pending = set(), list(json.loads(steps[step_id]['deps']))
    while pending:
        item = pending.pop()
        if item == step_id or item in seen:
            if item == step_id:
                raise ValueError('Dependência cíclica no fluxo existente.')
            continue
        if item not in steps:
            raise ValueError('Dependência ausente no fluxo existente.')
        seen.add(item)
        pending.extend(json.loads(steps[item]['deps']))
    return seen


def delegate(db, user_id, run_id, step_id, command, emit):
    validate_command(command)
    # Read permissions before claiming a write transaction; perform the same
    # check again inside the transaction to guard against changed grants.
    enforce_run_scope(db, user_id, run_id, write=True)
    fingerprint = hashlib.sha256(json.dumps(
        command, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    created = None
    with db.lock:
        db.conn.execute('BEGIN IMMEDIATE')
        try:
            enforce_run_scope(db, user_id, run_id, write=True)
            run = db.one('SELECT * FROM runs WHERE id=? AND user_id=?', (run_id, user_id))
            sender = db.one(
                'SELECT s.*,a.name AS agent_name,a.specialty AS specialty '
                'FROM steps s JOIN agents a ON a.id=s.agent_id AND a.user_id=? '
                'WHERE s.id=? AND s.run_id=?',
                (user_id, step_id, run_id))
            if not run or run['status'] != 'running' or not run['autonomous']:
                raise ValueError('Delegação exige execução autônoma ativa e pertencente à conta.')
            if not sender or sender['status'] != 'running':
                raise ValueError('Somente o trabalhador ativo pode criar subtarefas.')
            source_agent = db.one('SELECT * FROM agents WHERE id=? AND user_id=? AND enabled=1',
                                  (sender['agent_id'], user_id))
            if not source_agent or effective_specialty(source_agent) not in CAN_DELEGATE:
                raise ValueError('Este papel não está autorizado a delegar etapas.')
            previous = db.one(
                'SELECT step_id,request_hash FROM dynamic_step_requests '
                'WHERE run_id=? AND requester_step_id=? AND request_id=?',
                (run_id, step_id, command['request_id']))
            if previous:
                if previous['request_hash'] != fingerprint:
                    raise ValueError('request_id reutilizado com instruções diferentes.')
                db.conn.execute('COMMIT')
                return {'success': True, 'step_id': previous['step_id'],
                        'created': False, 'idempotent': True}

            target = db.one('SELECT * FROM agents WHERE id=? AND user_id=? AND enabled=1',
                            (command['recipient_agent_id'], user_id))
            if not target or target['id'] == sender['agent_id']:
                raise ValueError('Escolha outro trabalhador habilitado da sua conta.')
            if effective_specialty(target) == 'review':
                raise ValueError('O Revisor é a etapa de aceite e não pode receber subtarefa dinâmica.')
            # Prevent delegation back to an ancestor agent (model-created loops).
            lineage, current = set(), step_id
            depth = 1
            while current:
                if current in lineage:
                    raise ValueError('Ciclo de delegação detectado.')
                lineage.add(current)
                stage = db.one('SELECT agent_id FROM steps WHERE id=? AND run_id=?',
                               (current, run_id))
                if not stage or target['id'] == stage['agent_id']:
                    raise ValueError('Delegação circular ou etapa indisponível.')
                previous_stage = db.one(
                    'SELECT requester_step_id FROM dynamic_step_requests WHERE step_id=? AND run_id=?',
                    (current, run_id))
                if not previous_stage:
                    break
                current = previous_stage['requester_step_id']
                depth += 1
            if depth > MAX_DELEGATION_DEPTH:
                raise ValueError('Profundidade máxima de delegação atingida.')
            steps = {row['id']: row for row in db.all('SELECT * FROM steps WHERE run_id=?',
                                                       (run_id,))}
            count = db.one('SELECT COUNT(*) AS n FROM dynamic_step_requests WHERE run_id=?',
                           (run_id,))['n']
            if count >= MAX_DYNAMIC_STEPS or len(steps) >= MAX_TOTAL_STEPS:
                raise ValueError('Limite de subtarefas desta execução atingido.')
            if step_id not in steps:
                raise ValueError('Etapa solicitante não pertence à execução.')
            reviews = []
            for stage in steps.values():
                agent = (db.one('SELECT * FROM agents WHERE id=? AND user_id=?',
                                (stage['agent_id'], user_id))
                         if stage['agent_id'] else None)
                if agent and effective_specialty(agent) == 'review':
                    reviews.append(stage)
            if is_implementation_request(run['prompt']) and not reviews:
                raise ValueError('Implementação precisa de Revisor existente no fluxo.')
            for review in reviews:
                if (review['status'] != 'queued' or
                        step_id not in _ancestors(review['id'], steps)):
                    raise ValueError('O Revisor já começou ou não depende desta etapa; '
                                     'delegação dinâmica não é segura neste fluxo.')
            # Prevent concurrent editing of the shared workspace until per-agent
            # worktrees are available: wait for all earlier non-review stages.
            reviewers = {row['id'] for row in reviews}
            dependencies = [stage['id'] for stage in steps.values()
                            if stage['id'] not in reviewers and
                            stage['status'] in ('running', 'queued', 'awaiting_approval')]
            if step_id not in dependencies:
                dependencies.append(step_id)
            for dep in dependencies:
                if reviewers.intersection(_ancestors(dep, steps)):
                    raise ValueError('O fluxo atual exige uma etapa depois do Revisor; '
                                     'não é seguro inserir subtarefa nesta posição.')
            plan = json.loads(run['plan'])
            if not isinstance(plan, list):
                raise ValueError('Plano persistido incompatível com delegação.')
            new_id, now = uid(), utcnow()
            title, instructions = command['title'].strip(), command['instructions'].strip()
            db.execute(
                'INSERT INTO steps(id,run_id,agent_id,kind,name,deps,instructions,status,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                (new_id, run_id, target['id'], 'agent', title,
                 json.dumps(dependencies), instructions, 'queued', now, now))
            db.execute(
                'INSERT INTO dynamic_step_requests'
                '(step_id,run_id,requester_step_id,request_id,request_hash,depth,created_at) '
                'VALUES(?,?,?,?,?,?,?)',
                (new_id, run_id, step_id, command['request_id'], fingerprint, depth, now))
            from .agent_messages import create_message
            project = db.one(
                'SELECT c.project_id FROM runs r JOIN conversations c ON c.id=r.conversation_id '
                'WHERE r.id=? AND r.user_id=?', (run_id, user_id))
            if not project:
                raise ValueError('Projeto da execução não encontrado.')
            message = create_message(
                db, user_id, run_id, project['project_id'], sender['agent_id'],
                target['id'], 'task_request', instructions)
            plan.append({'id': new_id, 'agent_id': target['id'], 'name': title,
                         'kind': 'agent', 'deps': dependencies, 'instructions': instructions})
            for review in reviews:
                prior = json.loads(review['deps'])
                if new_id not in prior:
                    prior.append(new_id)
                db.execute('UPDATE steps SET deps=?,updated_at=? WHERE id=?',
                           (json.dumps(prior), now, review['id']))
                for stage in plan:
                    if stage.get('id') == review['id']:
                        stage['deps'] = prior
            db.execute('UPDATE runs SET plan=?,updated_at=? WHERE id=?',
                       (json.dumps(plan, ensure_ascii=False), now, run_id))
            db.event(run_id, 'dynamic_step_registered', {
                'step_id': new_id, 'requester_step_id': step_id,
                'recipient_agent_id': target['id'], 'depth': depth,
                'message_id': message['id']})
            db.conn.execute('COMMIT')
            created = {'success': True, 'step_id': new_id, 'created': True,
                       'recipient_agent_id': target['id'], 'depth': depth}
        except BaseException:
            db.conn.execute('ROLLBACK')
            raise
    if created:
        emit(run_id, 'dynamic_step_created', {
            'step_id': created['step_id'], 'requester_step_id': step_id,
            'recipient_agent_id': created['recipient_agent_id'],
            'depth': created['depth'], 'title': command['title'].strip()})
    return created
