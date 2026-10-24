"""Single-use approval plans for draft PR/MR creation, never merge or deploy."""
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException
from .database import uid, utcnow
from .git_gateway import Gateway, RemoteRejected, connection

SCHEMA = '''CREATE TABLE IF NOT EXISTS git_change_plans (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 connection_id TEXT NOT NULL REFERENCES git_connections(id) ON DELETE CASCADE,
 plan_json TEXT NOT NULL, confirmation_hash TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','executing','completed','failed','uncertain')),
 result_json TEXT, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
)'''
BRANCH = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_./-]{0,199}$')


def validate_branch(value):
    if (not isinstance(value, str) or not BRANCH.fullmatch(value) or '..' in value
            or value.endswith(('/', '.', '.lock')) or '//' in value
            or any(part.startswith('.') or part.endswith('.lock') for part in value.split('/'))):
        raise HTTPException(422, 'Nome de branch inválido.')


def fingerprint(row):
    return hashlib.sha256((row['service'] + '\0' + row['repository'] + '\0' + row['token_enc']).encode()).hexdigest()


def create(db, security, user_id, connection_id, head, base, title, body='', transport=None):
    validate_branch(head); validate_branch(base)
    if head == base or not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise HTTPException(422, 'Informe branches diferentes e um título de até 200 caracteres.')
    if not isinstance(body, str) or len(body) > 10000:
        raise HTTPException(422, 'Descrição deve ter até 10000 caracteres.')
    row = connection(db, user_id, connection_id)
    gateway = Gateway(row, security, transport)
    try:
        head_sha, base_sha = gateway.branch_sha(head), gateway.branch_sha(base)
    except (httpx.HTTPError, RemoteRejected, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, 'Não foi possível validar as branches no serviço Git.') from exc
    identifier = uid()
    plan = {'id': identifier, 'operation': 'create_draft_review', 'service': row['service'],
            'repository': row['repository'], 'head': head, 'base': base,
            'head_sha': head_sha, 'base_sha': base_sha, 'title': title.strip(), 'body': body,
            'connection_fingerprint': fingerprint(row)}
    encoded = json.dumps(plan, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    db.execute('INSERT INTO git_change_plans '
               '(id,user_id,connection_id,plan_json,confirmation_hash,expires_at,created_at) '
               'VALUES(?,?,?,?,?,?,?)', (identifier, user_id, connection_id, encoded, digest, expires, utcnow()))
    # Token and encrypted credentials are never included in the reviewable plan.
    visible = {k: v for k, v in plan.items() if k != 'connection_fingerprint'}
    return {**visible, 'confirmation': digest, 'expires_at': expires, 'state': 'pending'}


def status(db, user_id, plan_id):
    row = db.one('SELECT state,result_json,expires_at FROM git_change_plans WHERE id=? AND user_id=?',
                 (plan_id, user_id))
    if not row:
        raise HTTPException(404, 'Plano não encontrado.')
    state = 'expired' if row['state'] == 'pending' and row['expires_at'] <= utcnow() else row['state']
    return {'state': state, 'expires_at': row['expires_at'],
            'result': json.loads(row['result_json']) if row['result_json'] else None}


def execute(db, security, user_id, plan_id, confirmation, transport=None):
    row = db.one('SELECT * FROM git_change_plans WHERE id=? AND user_id=?', (plan_id, user_id))
    if not row:
        raise HTTPException(404, 'Plano não encontrado.')
    if (not isinstance(confirmation, str) or
            not hmac.compare_digest(confirmation.encode(), row['confirmation_hash'].encode())):
        raise HTTPException(409, 'Confirmação não corresponde ao plano apresentado.')
    plan = json.loads(row['plan_json'])
    current = connection(db, user_id, row['connection_id'])
    if fingerprint(current) != plan['connection_fingerprint']:
        raise HTTPException(409, 'Conexão alterada; gere e revise um novo plano.')
    changed = db.execute("UPDATE git_change_plans SET state='executing' "
                         "WHERE id=? AND user_id=? AND state='pending' AND expires_at>?",
                         (plan_id, user_id, utcnow()))
    if changed != 1:
        raise HTTPException(409, 'Plano expirado ou já utilizado; consulte o estado antes de criar outro.')
    posted = False
    try:
        gateway = Gateway(current, security, transport)
        if gateway.branch_sha(plan['head']) != plan['head_sha'] or gateway.branch_sha(plan['base']) != plan['base_sha']:
            raise HTTPException(409, 'Branches mudaram; revise um novo plano antes de publicar.')
        description = plan['body'] + '\n\n<!-- central-plan:' + plan_id + ' -->'
        if gateway.github:
            suffix = '/pulls'
            payload = {'head': plan['head'], 'base': plan['base'], 'title': plan['title'],
                       'body': description, 'draft': True, 'maintainer_can_modify': False}
        else:
            suffix = '/merge_requests'
            payload = {'source_branch': plan['head'], 'target_branch': plan['base'],
                       'title': 'Draft: ' + plan['title'], 'description': description,
                       'remove_source_branch': False, 'squash': False}
        # No automatic retries. A transport error after this point is uncertain.
        posted = True
        response, _ = gateway.request('POST', suffix, payload)
        number = response['number' if gateway.github else 'iid']
        if type(number) is not int or number < 1:
            raise ValueError('Invalid review number')
        actual_sha = response.get('head', {}).get('sha') if gateway.github else response.get('sha')
        actual_base = (response.get('base', {}).get('sha') if gateway.github else
                       (response.get('diff_refs') or {}).get('start_sha'))
        actual_draft = response.get('draft', response.get('work_in_progress', False))
        result = {'number': number, 'url': ('https://github.com/' + plan['repository'] + '/pull/' + str(number)
                  if gateway.github else 'https://gitlab.com/' + plan['repository'] + '/-/merge_requests/' + str(number)),
                  'draft': bool(actual_draft), 'head_matches_plan': actual_sha == plan['head_sha'],
                  'base_matches_plan': actual_base == plan['base_sha'],
                  'requires_review': (actual_sha != plan['head_sha'] or actual_base != plan['base_sha']
                                      or not actual_draft)}
        db.execute("UPDATE git_change_plans SET state='completed',result_json=? WHERE id=?",
                    (json.dumps(result), plan_id))
        return {'state': 'completed', 'result': result}
    except HTTPException:
        db.execute("UPDATE git_change_plans SET state='failed' WHERE id=?", (plan_id,))
        raise
    except (httpx.HTTPError, RemoteRejected, ValueError, KeyError, TypeError) as exc:
        uncertain = posted and (not isinstance(exc, RemoteRejected) or not 400 <= exc.status < 500)
        state = 'uncertain' if uncertain else 'failed'
        db.execute('UPDATE git_change_plans SET state=? WHERE id=?', (state, plan_id))
        raise HTTPException(502, 'Resultado remoto incerto; verifique o serviço antes de criar outro plano.'
                            if uncertain else 'Operação recusada; revise conexão e permissões.') from exc
