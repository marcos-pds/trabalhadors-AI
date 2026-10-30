"""Durable cooperative step controls; no tasks, effects or checkpoints replayed.

Call check_control BEFORE each new action (including finish/validation), outside
any database transaction. Catch signals outside provider failover, persist the
worker checkpoint, and park the step. Never interrupt an in-flight action.
Only an authenticated user/API may call request_control, never model tools.
"""
import json
from contextlib import contextmanager

from fastapi import HTTPException

from .database import uid, utcnow
from .organizations import require_run_write, require_run_scope

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS worker_controls (
    step_id TEXT PRIMARY KEY REFERENCES steps(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id),
    request_id TEXT NOT NULL UNIQUE,
    operation TEXT NOT NULL CHECK(operation IN ('pause','resume','cancel')),
    state TEXT NOT NULL CHECK(state IN ('active','paused','cancelled')),
    pending INTEGER NOT NULL CHECK(pending IN (0,1)),
    requested_at TEXT NOT NULL, applied_at TEXT,
    diagnostic TEXT NOT NULL DEFAULT '')""",
    'CREATE INDEX IF NOT EXISTS idx_worker_controls_run ON worker_controls(user_id,run_id,pending)',
)
ACTIVE_RUNS = frozenset(('queued', 'running', 'awaiting_approval', 'paused_operator', 'paused_limit'))
TERMINAL_STEPS = frozenset(('completed', 'failed', 'cancelled', 'skipped'))


class WorkerControlPaused(RuntimeError):
    """Save a checkpoint and park this step; do not fail over providers."""


class WorkerControlCancelled(RuntimeError):
    """Stop this step at the boundary; retain all already completed effects."""


@contextmanager
def _transaction(db):
    with db.lock:
        db.conn.execute('BEGIN IMMEDIATE')
        try:
            yield
            db.conn.execute('COMMIT')
        except BaseException:
            db.conn.execute('ROLLBACK')
            raise


def _scope(db, user, rid, sid=None, *, write=False, organization_id=None,
           allow_legacy_unassigned=False):
    if write:
        run = require_run_write(db, rid, user)
    else:
        run = db.one('SELECT * FROM runs WHERE id=? AND user_id=?', (rid, user))
        if not run:
            raise HTTPException(404, 'Execução não encontrada.')
        require_run_scope(db, run, user)
    mapping = db.one('SELECT organization_id FROM organization_runs WHERE run_id=?', (rid,))
    org = mapping['organization_id'] if mapping else None
    if organization_id is not None and org != organization_id:
        raise HTTPException(404, 'Execução fora da organização ativa.')
    if sid is None:
        return run, org, None
    step = db.one("SELECT * FROM steps WHERE id=? AND run_id=? AND kind='agent'", (sid, rid))
    if not step:
        raise HTTPException(404, 'Trabalhador não encontrado nesta execução.')
    # Old test/legacy steps can be unassigned. The control boundary cannot
    # grant any new permission, but an operator must never control a step
    # without an actual owned worker. Foreign non-null IDs always fail closed.
    if step['agent_id'] is None and allow_legacy_unassigned:
        return run, org, step
    agent = db.one('SELECT id FROM agents WHERE id=? AND user_id=?', (step['agent_id'], user))
    if not agent:
        raise HTTPException(404, 'Trabalhador fora do proprietário da execução.')
    return run, org, step


def request_control(db, user, rid, sid, operation, *, organization_id=None):
    """User-authorized transition. Identical retries preserve request_id/time.

    Cancel is irreversible for this step. Resume clears a pause and requeues
    only a paused_operator step. The caller schedules a paused run explicitly.
    """
    if operation not in ('pause', 'resume', 'cancel'):
        raise HTTPException(422, 'Controle inválido.')
    with _transaction(db):
        run, org, step = _scope(db, user, rid, sid, write=True, organization_id=organization_id)
        old = db.one('SELECT * FROM worker_controls WHERE step_id=?', (sid,))
        if old and old['organization_id'] != org:
            raise HTTPException(409, 'O escopo da organização mudou.')
        if old and old['operation'] == operation == 'cancel' and step['status'] == 'cancelled':
            return old
        if run['status'] not in ACTIVE_RUNS or step['status'] in TERMINAL_STEPS:
            raise HTTPException(409, 'Execução ou trabalhador encerrado.')
        if old and old['operation'] == operation:
            return old
        if old and old['state'] == 'cancelled':
            raise HTTPException(409, 'Trabalhador cancelado não pode ser retomado.')
        if operation == 'resume' and (not old or old['state'] != 'paused'):
            raise HTTPException(409, 'Somente trabalhador pausado pode ser retomado.')
        state = {'pause': 'paused', 'resume': 'active', 'cancel': 'cancelled'}[operation]
        db.execute('INSERT INTO worker_controls '
                   '(step_id,run_id,user_id,organization_id,request_id,operation,state,pending,requested_at,diagnostic) '
                   'VALUES(?,?,?,?,?,?,?,1,?,?) ON CONFLICT(step_id) DO UPDATE SET '
                   'request_id=excluded.request_id,operation=excluded.operation,state=excluded.state,'
                   'pending=1,requested_at=excluded.requested_at,applied_at=NULL,diagnostic=excluded.diagnostic',
                   (sid, rid, user, org, uid(), operation, state, utcnow(),
                    'Aguardando limite seguro entre ações.'))
        if operation == 'resume':
            db.execute("UPDATE steps SET status='queued',error=NULL,updated_at=? "
                       "WHERE id=? AND run_id=? AND status='paused_operator'",
                       (utcnow(), sid, rid))
        return db.one('SELECT * FROM worker_controls WHERE step_id=?', (sid,))


def check_control(db, user, rid, sid, *, organization_id=None):
    """Consume pending once, commit, then signal durable pause/cancel.

    Repeated checks continue blocking until explicit resume; pending is only a
    one-use diagnostic/decision marker, never permission to bypass a stop.
    Returns a consumed resume record, or None if no decision is pending.
    """
    decision = None
    with _transaction(db):
        run, org, step = _scope(db, user, rid, sid, write=True, organization_id=organization_id,
                                allow_legacy_unassigned=True)
        row = db.one('SELECT * FROM worker_controls WHERE step_id=? AND run_id=? AND user_id=?', (sid, rid, user))
        if row and row['organization_id'] != org:
            raise HTTPException(409, 'O escopo da organização mudou.')
        if row and row['pending']:
            db.execute('UPDATE worker_controls SET pending=0,applied_at=?,diagnostic=? WHERE step_id=?',
                       (utcnow(), 'Controle observado no limite seguro entre ações.', sid))
            row = db.one('SELECT * FROM worker_controls WHERE step_id=?', (sid,))
            decision = row
    # Signals MUST escape after commit, otherwise acknowledgment rolls back.
    if run['status'] == 'cancelled' or step['status'] == 'cancelled' or (row and row['state'] == 'cancelled'):
        raise WorkerControlCancelled('Trabalhador cancelado; efeitos concluídos preservados.')
    if row and row['state'] == 'paused':
        raise WorkerControlPaused('Trabalhador pausado pelo usuário no limite seguro.')
    if run['status'] not in ACTIVE_RUNS or step['status'] in TERMINAL_STEPS:
        raise HTTPException(409, 'Execução ou trabalhador encerrado.')
    return decision


def list_controls(db, user, rid, *, organization_id=None):
    """Return worker state, pending controls, dependency blockers and errors."""
    with db.lock:
        _, org, _ = _scope(db, user, rid, organization_id=organization_id)
        steps = db.all('SELECT id,name,kind,status,deps,error FROM steps WHERE run_id=? ORDER BY rowid', (rid,))
        by_id = {step['id']: step for step in steps}
        controls = {row['step_id']: row for row in db.all(
            'SELECT * FROM worker_controls WHERE run_id=? AND user_id=?', (rid, user))}
        result = []
        for step in steps:
            if step['kind'] != 'agent':
                continue
            try:
                deps = json.loads(step['deps'])
                if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
                    raise ValueError('Invalid dependency list')
            except (TypeError, ValueError):
                deps = []
                step['error'] = step['error'] or 'Dependências inválidas.'
            control = controls.get(step['id'])
            if control and control['organization_id'] != org:
                raise HTTPException(409, 'O escopo da organização mudou.')
            blockers = []
            for dep in deps:
                source = by_id.get(dep)
                stop = controls.get(dep)
                if not source or source['status'] != 'completed' or (stop and stop['state'] in ('paused', 'cancelled')):
                    blockers.append({'step_id': dep, 'name': source['name'] if source else dep,
                                     'status': stop['state'] if stop and stop['state'] != 'active' else source['status'] if source else 'missing'})
            result.append(dict(step, deps=deps, blockers=blockers, control=control))
        return {'run_id': rid, 'steps': result,
                'pending_controls': [row for row in controls.values() if row['pending']]}
