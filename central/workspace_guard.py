"""Immutable workspace bindings for autonomous runs (logical isolation, not OS sandbox).

Only a user-owned, explicitly authorized local folder can be bound to a run.
Different organizations cannot bind overlapping paths, even across historical
runs. Protect against a workspace grant being silently switched mid-execution.
"""
from pathlib import Path
from fastapi import HTTPException
from .computer_access import policy, allowed_folder
from .database import utcnow


def _inside(a, b):
    return a == b or a.is_relative_to(b)


def current_organization(db, run_id):
    row = db.one('SELECT organization_id FROM organization_runs WHERE run_id=?', (run_id,))
    return row['organization_id'] if row else None


def bind_run(db, user_id, run_id, organization_id=None):
    grant = policy(db, user_id)
    if grant['mode'] not in ('ask', 'full') or not grant['folder']:
        raise HTTPException(403, 'Autorize uma pasta antes de criar a tarefa autônoma.')
    folder = allowed_folder(grant['folder'])
    root = Path(folder)
    org_id = organization_id or current_organization(db, run_id)
    if org_id:
        from .organizations import require_org
        require_org(db, org_id, user_id, write=True)
    with db.lock:
        # Called from the already active BEGIN IMMEDIATE in Engine.create_run;
        # do not commit early, so failed authorization rolls back the run.
        existing = db.one('SELECT * FROM run_workspace_bindings WHERE run_id=?',
                          (run_id,))
        if existing:
            if (existing['user_id'] != user_id or existing['folder'] != folder
                    or existing['organization_id'] != org_id):
                raise HTTPException(409, 'O workspace original desta tarefa não pode ser alterado.')
            return existing
        other = db.all(
            'SELECT folder,organization_id FROM run_workspace_bindings '
            'WHERE run_id!=?', (run_id,))
        for record in other:
            if record['organization_id'] == org_id:
                continue
            other_root = Path(record['folder'])
            if _inside(root, other_root) or _inside(other_root, root):
                raise HTTPException(
                    409,'Esta pasta já está vinculada a outra organização. '
                        'Autorize uma pasta separada para cada organização.')
        db.execute(
            'INSERT INTO run_workspace_bindings(run_id,user_id,organization_id,'
            'folder,initial_mode,created_at) VALUES(?,?,?,?,?,?)',
            (run_id,user_id,org_id,folder,grant['mode'],utcnow()))
    return db.one('SELECT * FROM run_workspace_bindings WHERE run_id=?', (run_id,))


def enforce_run_scope(db, user_id, run_id, *, write=False):
    run = db.one('SELECT id,user_id,status,autonomous FROM runs WHERE id=?',
                 (run_id,))
    if not run or run['user_id'] != user_id:
        raise HTTPException(404,'Tarefa não encontrada para esta conta.')
    if run['status'] in ('cancelled','failed','completed','paused_limit'):
        raise HTTPException(409,'Esta tarefa não está ativa; nenhuma nova ferramenta será executada.')
    org = current_organization(db, run_id)
    if org:
        from .organizations import require_org
        require_org(db,org,user_id,write=write)
    current = policy(db,user_id)
    if current['mode'] not in ('full','ask') or not current['folder']:
        raise HTTPException(403,'Permissão de computador bloqueada.')
    folder = allowed_folder(current['folder'])
    binding = db.one('SELECT * FROM run_workspace_bindings WHERE run_id=?',(run_id,))
    if binding:
        if (binding['user_id'] != user_id or binding['folder'] != folder
                or binding['organization_id'] != org):
            raise HTTPException(409,'O workspace mudou ou a organização não corresponde. '
                                     'Volte à pasta originalmente autorizada.')
    elif run['autonomous']:
        # Legacy autonomous tasks created before this feature can be resumed
        # explicitly through Engine.resume_run, which binds their current grant.
        raise HTTPException(409,'Tarefa antiga sem vínculo de workspace. '
                                 'Retome-a explicitamente para autorizar a pasta.')
    return folder


def enforce_host_command_policy(db,user_id,run_id):
    # An isolated Docker command does not require opt-in for uncontained host
    # scripts, but still passes RBAC and individual team approval.
    from .sandbox_executor import backend
    if backend() == 'docker':
        return
    org_id = current_organization(db,run_id)
    if not org_id:
        return
    from .organizations import require_org
    member = require_org(db,org_id,user_id,write=True)
    if not member['is_personal'] and not member['host_commands_enabled']:
        raise HTTPException(
            403,'Comandos locais desta organização estão bloqueados. '
                'O administrador precisa autorizar explicitamente a execução '
                'de scripts no computador. Isso não é uma sandbox.')


def binding_summary(db,user_id,run_id):
    row=db.one(
        'SELECT folder,organization_id,initial_mode,created_at '
        'FROM run_workspace_bindings WHERE run_id=? AND user_id=?',
        (run_id,user_id))
    return row
