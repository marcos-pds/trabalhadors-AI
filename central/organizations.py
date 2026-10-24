"""Organization RBAC and project boundary checks.

Personal credentials, chat history, workers and computer grants remain owned by
their individual users. Sharing a project does not share those private assets.
"""
from fastapi import HTTPException
from .database import uid, utcnow

ROLES = {'admin', 'operator', 'analyst'}
WRITE_ROLES = {'admin', 'operator'}


def ensure_personal(db, user_id):
    existing = db.one(
        'SELECT id FROM organizations WHERE created_by=? AND is_personal=1',
        (user_id,))
    if existing:
        return existing['id']
    with db.lock, db.conn:
        existing = db.one(
            'SELECT id FROM organizations WHERE created_by=? AND is_personal=1',
            (user_id,))
        if existing:
            return existing['id']
        organization_id = uid()
        db.conn.execute(
            'INSERT INTO organizations(id,name,created_by,is_personal,created_at) '
            'VALUES(?,?,?,?,?)',
            (organization_id,'Meu espaço',user_id,1,utcnow()))
        db.conn.execute(
            'INSERT INTO organization_members(organization_id,user_id,role,created_at) '
            'VALUES(?,?,?,?)', (organization_id,user_id,'admin',utcnow()))
        return organization_id


def membership(db, organization_id, user_id):
    return db.one(
        'SELECT o.id,o.name,o.is_personal,o.daily_run_limit,'
        'o.active_run_limit,o.estimated_budget_usd,m.role '
        'FROM organization_members m JOIN organizations o '
        'ON o.id=m.organization_id WHERE m.organization_id=? AND m.user_id=?',
        (organization_id,user_id))


def require_org(db, organization_id, user_id, write=False, admin=False):
    member = membership(db,organization_id,user_id)
    if not member:
        raise HTTPException(404, 'Organização não encontrada.')
    if admin and member['role'] != 'admin':
        raise HTTPException(403, 'Somente administradores podem realizar esta ação.')
    if write and member['role'] not in WRITE_ROLES:
        raise HTTPException(403, 'Analistas têm acesso somente de leitura.')
    return member


def project_org(db, project_id):
    return db.one(
        'SELECT organization_id FROM organization_projects WHERE project_id=?',
        (project_id,))


def require_project(db, project_id, user_id, write=False):
    project = db.one('SELECT * FROM projects WHERE id=?', (project_id,))
    if not project:
        raise HTTPException(404, 'Projeto não encontrado.')
    mapping = project_org(db,project_id)
    if not mapping:
        # Legacy fixture/rows without organization mapping remain personal,
        # and can only be read by their original owner.
        if project['user_id'] != user_id:
            raise HTTPException(404,'Projeto não encontrado.')
        return project
    require_org(db,mapping['organization_id'],user_id,write=write)
    return dict(project,organization_id=mapping['organization_id'])


def visible_projects(db,user_id):
    return db.all(
        """SELECT p.*,op.organization_id
           FROM projects p LEFT JOIN organization_projects op
             ON op.project_id=p.id
           WHERE (op.organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id=?
                  ) OR (op.organization_id IS NULL AND p.user_id=?))
           ORDER BY p.created_at DESC""", (user_id,user_id))


def require_conversation_scope(db, conversation, user_id, write=False):
    if conversation['user_id'] != user_id:
        raise HTTPException(404,'Registro não encontrado.')
    if conversation.get('project_id'):
        require_project(db,conversation['project_id'],user_id,write=write)
    return conversation


def require_run_scope(db, run, user_id):
    if run['user_id'] != user_id:
        raise HTTPException(404,'Registro não encontrado.')
    mapping=db.one('SELECT organization_id FROM organization_runs WHERE run_id=?',
                   (run['id'],))
    if mapping:
        require_org(db,mapping['organization_id'],user_id)
    return run


def require_run_write(db,run_id,user_id):
    run=db.one('SELECT * FROM runs WHERE id=? AND user_id=?',
               (run_id,user_id))
    if not run:
        raise HTTPException(404,'Registro não encontrado.')
    mapping=db.one('SELECT organization_id FROM organization_runs WHERE run_id=?',
                   (run_id,))
    if mapping:
        require_org(db,mapping['organization_id'],user_id,write=True)
    return run


def all_organizations(db,user_id):
    return db.all(
        """SELECT o.id,o.name,o.is_personal,m.role,o.daily_run_limit,
                  o.active_run_limit,o.estimated_budget_usd
           FROM organization_members m JOIN organizations o
             ON o.id=m.organization_id
           WHERE m.user_id=? ORDER BY o.is_personal DESC,o.name""", (user_id,))


def create_organization(db,user_id,name):
    with db.lock,db.conn:
        org_id=uid()
        db.conn.execute(
            'INSERT INTO organizations(id,name,created_by,created_at) '
            'VALUES(?,?,?,?)',(org_id,name,user_id,utcnow()))
        db.conn.execute(
            'INSERT INTO organization_members(organization_id,user_id,role,created_at) '
            'VALUES(?,?,?,?)',(org_id,user_id,'admin',utcnow()))
    return org_id


def set_member(db,org_id,acting_user,member_user,role):
    if role not in ROLES:
        raise HTTPException(422,'Papel inválido.')
    with db.lock, db.conn:
        org=require_org(db,org_id,acting_user,admin=True)
        if org['is_personal']:
            raise HTTPException(403,'Espaços pessoais não aceitam outros membros.')
        person=db.one('SELECT id FROM users WHERE id=?',(member_user,))
        if not person:
            raise HTTPException(404,'Usuário não encontrado.')
        old=membership(db,org_id,member_user)
        if old and old['role'] in WRITE_ROLES and role=='analyst':
            active=db.one(
                """SELECT COUNT(*) AS n FROM runs r
                   JOIN organization_runs x ON x.run_id=r.id
                   WHERE x.organization_id=? AND r.user_id=?
                   AND r.status IN ('queued','running','awaiting_approval')""",
                (org_id,member_user))['n']
            if active:
                raise HTTPException(
                    409,'Finalize ou cancele as tarefas ativas antes de reduzir o papel.')
        if old and old['role']=='admin' and role!='admin':
            n=db.one("SELECT COUNT(*) n FROM organization_members "
                     "WHERE organization_id=? AND role='admin'",(org_id,))['n']
            if n<=1:
                raise HTTPException(409,'A organização precisa manter um administrador.')
        db.conn.execute(
            'INSERT INTO organization_members(organization_id,user_id,role,created_at) '
            'VALUES(?,?,?,?) ON CONFLICT(organization_id,user_id) DO UPDATE SET role=excluded.role',
            (org_id,member_user,role,utcnow()))
    return role


def remove_member(db,org_id,actor,user_id):
    with db.lock,db.conn:
        org=require_org(db,org_id,actor,admin=True)
        if org['is_personal']:
            raise HTTPException(403,'Espaços pessoais não permitem remover o proprietário.')
        old=membership(db,org_id,user_id)
        if not old:
            raise HTTPException(404,'Membro não encontrado.')
        if old['role']=='admin':
            n=db.one("SELECT COUNT(*) n FROM organization_members "
                     "WHERE organization_id=? AND role='admin'",(org_id,))['n']
            if n<=1:
                raise HTTPException(409,'A organização precisa manter um administrador.')
        active=db.one(
            """SELECT COUNT(*) n FROM runs r
               JOIN organization_runs x ON x.run_id=r.id
               WHERE x.organization_id=? AND r.user_id=?
               AND r.status IN ('queued','running','awaiting_approval')""",
            (org_id,user_id))['n']
        if active:
            raise HTTPException(409,'Aguarde ou cancele as tarefas ativas deste membro.')
        db.conn.execute(
            'DELETE FROM organization_members WHERE organization_id=? AND user_id=?',
            (org_id,user_id))
        # Shared projects remain in the organization. Their former private
        # conversation owner cannot access their project context after removal.
    return True
