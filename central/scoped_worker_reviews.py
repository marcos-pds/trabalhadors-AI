"""User-scoped, local-only worktree review gateway.

All mutations are initiated by an authenticated operator after the run is no
longer active. This does NOT route AI tools or auto-merge project files.
"""
import os
from pathlib import Path

from fastapi import HTTPException

from .computer_access import allowed_folder, policy
from .database import utcnow
from .organizations import require_run_write
from .worker_worktrees import WorktreeError, prepare, inspect
from .worker_worktree_reviews import prepare_review, inspect_review, apply_review
from .workspace_guard import current_organization

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS scoped_worker_worktrees("
    "run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,"
    "step_id TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,"
    "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "folder TEXT NOT NULL,created_at TEXT NOT NULL,"
    "PRIMARY KEY(run_id,step_id))",
    "CREATE TABLE IF NOT EXISTS scoped_worktree_reviews("
    "plan_id TEXT PRIMARY KEY,"
    "run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,"
    "step_id TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,"
    "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    "folder TEXT NOT NULL,"
    "state TEXT NOT NULL CHECK(state IN ('pending','applying','applied','manual_review')),"
    "created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_scoped_worktree_user "
    "ON scoped_worktree_reviews(user_id,run_id,created_at)",
)

_ALLOWED_RUN_STATES = frozenset({'completed', 'failed', 'paused_limit', 'cancelled'})


def enabled():
    return (os.environ.get('CENTRAL_WORKTREE_REVIEWS_ENABLED') == '1'
            and os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local') == 'local')


def _scope(db, user_id, run_id, step_id=None):
    if not enabled():
        raise HTTPException(409, 'Ative CENTRAL_WORKTREE_REVIEWS_ENABLED=1 apenas no ambiente local de testes.')
    run = require_run_write(db, run_id, user_id)
    # Do not allow collaborators to take over an owner's local filesystem.
    if run['user_id'] != user_id:
        raise HTTPException(403, 'Somente o responsável pela execução pode integrar arquivos locais.')
    if run['status'] not in _ALLOWED_RUN_STATES:
        raise HTTPException(409, 'Aguarde o término ou pausa da execução antes de manipular worktrees.')
    grant = policy(db, user_id)
    binding = db.one('SELECT * FROM run_workspace_bindings WHERE run_id=? AND user_id=?',
                     (run_id, user_id))
    if not binding or grant['mode'] not in ('full', 'ask') or not grant['folder']:
        raise HTTPException(403, 'Esta execução exige um workspace originalmente vinculado e ainda autorizado.')
    root = allowed_folder(grant['folder'])
    if (root != binding['folder'] or
            binding['organization_id'] != current_organization(db, run_id)):
        raise HTTPException(409, 'Permissão ou organização do workspace mudou após a execução.')
    if step_id is not None:
        step = db.one("SELECT id FROM steps WHERE id=? AND run_id=? AND kind='agent'",
                      (step_id, run_id))
        if not step:
            raise HTTPException(404, 'Etapa de trabalhador não encontrada nesta execução.')
    from .worker_worktrees import _repo
    try:
        exact_repo = _repo(root)
    except WorktreeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return str(exact_repo)


def _existing(db, user_id, run_id, step_id):
    row = db.one(
        'SELECT * FROM scoped_worker_worktrees WHERE user_id=? AND run_id=? AND step_id=?',
        (user_id, run_id, step_id))
    if not row:
        raise HTTPException(409, 'Prepare e registre o worktree antes de revisar.')
    return row


def list_worktrees(db, user_id, run_id):
    run = require_run_write(db, run_id, user_id)
    if run['user_id'] != user_id:
        raise HTTPException(403, 'Execução de outro usuário.')
    if not enabled():
        return {'enabled': False, 'worktrees': []}
    rows = db.all('SELECT step_id,folder,created_at FROM scoped_worker_worktrees '
                  'WHERE run_id=? AND user_id=? ORDER BY created_at',
                  (run_id, user_id))
    result = []
    for item in rows:
        try:
            root = _scope(db, user_id, run_id, item['step_id'])
            if root != item['folder']:
                raise HTTPException(409, 'Pasta do worktree diferente da autorização.')
            state = inspect(root, run_id, item['step_id'])
            result.append({'step_id': item['step_id'], 'clean': state['clean'],
                           'changes': state['changes'], 'path': state['path']})
        except (HTTPException, WorktreeError):
            result.append({'step_id': item['step_id'], 'blocked': True})
    return {'enabled': True, 'worktrees': result}


def register_worktree(db, user_id, run_id, step_id):
    root = _scope(db, user_id, run_id, step_id)
    previous = db.one('SELECT * FROM scoped_worker_worktrees WHERE run_id=? AND step_id=?',
                      (run_id, step_id))
    if previous and (previous['user_id'] != user_id or previous['folder'] != root):
        raise HTTPException(409, 'Worktree já registrado com outro escopo.')
    try:
        created = prepare(root, run_id, step_id)
    except WorktreeError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.execute('INSERT OR IGNORE INTO scoped_worker_worktrees '
               '(run_id,step_id,user_id,folder,created_at) VALUES(?,?,?,?,?)',
               (run_id, step_id, user_id, root, utcnow()))
    db.event(run_id, 'scoped_worktree_prepared',
             {'step_id': step_id, 'reused': created['reused']})
    return created


def create_review(db, user_id, run_id, step_id):
    root = _scope(db, user_id, run_id, step_id)
    row = _existing(db, user_id, run_id, step_id)
    if root != row['folder']:
        raise HTTPException(409, 'Pasta registrada não corresponde à permissão.')
    try:
        review = prepare_review(root, run_id, step_id)
    except WorktreeError as exc:
        raise HTTPException(409, str(exc)) from exc
    # File-backed plan is inaccessible through the API until explicitly owned.
    db.execute('INSERT INTO scoped_worktree_reviews '
               '(plan_id,run_id,step_id,user_id,folder,state,created_at,updated_at) '
               'VALUES(?,?,?,?,?,?,?,?)',
               (review['plan_id'],run_id,step_id,user_id,root,'pending',utcnow(),utcnow()))
    db.event(run_id, 'scoped_worktree_review_created',
             {'step_id':step_id,'plan_id':review['plan_id'],'file_count':len(review['files'])})
    return review


def _plan_scope(db, user_id, run_id, plan_id):
    row = db.one('SELECT * FROM scoped_worktree_reviews '
                 'WHERE plan_id=? AND run_id=? AND user_id=?',
                 (plan_id, run_id, user_id))
    if not row:
        raise HTTPException(404, 'Plano de integração indisponível para esta conta.')
    root = _scope(db, user_id, run_id, row['step_id'])
    if row['folder'] != root or _existing(db, user_id, run_id, row['step_id'])['folder'] != root:
        raise HTTPException(409, 'Pasta do plano não corresponde ao workspace autorizado.')
    try:
        record = inspect_review(root, plan_id)
    except WorktreeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if record['run_id'] != run_id or record['step_id'] != row['step_id']:
        raise HTTPException(409, 'Plano não pertence à etapa registrada.')
    return row, record


def get_review(db, user_id, run_id, plan_id):
    row, record = _plan_scope(db, user_id, run_id, plan_id)
    return {'plan_id': plan_id, 'state': row['state'], 'step_id': row['step_id'],
            'files': record['files'], 'head': record['head'],
            'note': 'O código só pode ser integrado com a confirmação recebida ao preparar o plano.'}


def approve_review(db, user_id, run_id, plan_id, confirmation):
    row, record = _plan_scope(db, user_id, run_id, plan_id)
    if row['state'] != 'pending' or record['state'] != 'prepared':
        raise HTTPException(409, 'Este plano já foi utilizado ou precisa de inspeção.')
    # Claim exactly once in SQLite before any filesystem mutation; on crash,
    # "applying" is never automatically replayed by the API.
    claimed = db.execute("UPDATE scoped_worktree_reviews SET state='applying',updated_at=? "
                         "WHERE plan_id=? AND user_id=? AND run_id=? AND state='pending'",
                         (utcnow(), plan_id, user_id, run_id))
    if claimed != 1:
        raise HTTPException(409, 'Plano já utilizado por outra solicitação.')
    try:
        result = apply_review(row['folder'], plan_id, confirmation)
    except (WorktreeError, OSError, ValueError) as exc:
        db.execute("UPDATE scoped_worktree_reviews SET state='manual_review',updated_at=? "
                   "WHERE plan_id=? AND state='applying'", (utcnow(), plan_id))
        db.event(run_id, 'scoped_worktree_apply_blocked',
                 {'plan_id': plan_id, 'step_id': row['step_id']})
        raise HTTPException(409, 'Integração interrompida; confira o Git e prepare novo plano. '
                                 + str(exc)[:260]) from exc
    db.execute("UPDATE scoped_worktree_reviews SET state='applied',updated_at=? "
               "WHERE plan_id=? AND state='applying'", (utcnow(), plan_id))
    db.event(run_id, 'scoped_worktree_applied', {
        'step_id': row['step_id'], 'plan_id': plan_id, 'files': result['files'],
        'validation_required': True})
    # IMPORTANT: a previous "completed" run no longer proves delivered code
    # once reviewed bytes have been copied after its last validated build.
    db.event(run_id, 'workspace_validation', {
        'step_id': row['step_id'], 'passed': False,
        'reason': 'Arquivos promovidos após o último build: revalidar projeto principal.',
        'results': [{'command': 'post_worktree_promotion', 'success': False}]})
    return dict(result, validation_required=True)
