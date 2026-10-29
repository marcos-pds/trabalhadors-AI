"""One-time workspace approval issuance, expiry and scope revalidation."""
import json
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from .database import uid, utcnow
from .computer_access import policy
from .workspace_guard import enforce_run_scope

def issue_approval(db, user_id, run_id, step_id, folder, request, summary):
    # Reuse the current approval when a recovered worker replays the same action.
    request_json = json.dumps(request, ensure_ascii=False, sort_keys=True)
    now = datetime.now(timezone.utc).isoformat()
    existing = db.one('''SELECT id FROM workspace_action_approvals
      WHERE user_id=? AND run_id=? AND step_id=? AND folder=? AND request_json=?
        AND status='pending' AND expires_at>?
      ORDER BY created_at DESC LIMIT 1''',
      (user_id, run_id, step_id, folder, request_json, now))
    if existing:
        db.execute('''UPDATE workspace_action_approvals SET status='denied'
          WHERE user_id=? AND run_id=? AND step_id=? AND folder=? AND request_json=?
            AND status='pending' AND id<>?''',
          (user_id, run_id, step_id, folder, request_json, existing['id']))
        return existing['id']

    # Store pending edits/commands inside the local DB; no secrets are returned to other users.
    token = uid()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    db.execute('''INSERT INTO workspace_action_approvals
      (id,user_id,run_id,step_id,folder,request_json,status,expires_at,created_at)
      VALUES(?,?,?,?,?,?,?,?,?)''',
      (token, user_id, run_id, step_id, folder, request_json, 'pending', expires, utcnow()))
    return token


def decide(db, user_id, run_id, approval_id, approved):
    from .workspace_tools import needs_explicit_approval
    row = db.one('''SELECT * FROM workspace_action_approvals
      WHERE id=? AND user_id=? AND run_id=?''', (approval_id, user_id, run_id))
    if not row or row['status'] != 'pending':
        raise HTTPException(409, 'Autorização indisponível ou já respondida.')
    current = policy(db, user_id)
    requested = json.loads(row['request_json'])
    from .step_scope import execution_folder
    expected_folder = execution_folder(db, user_id, run_id, row['step_id'])
    if (current['mode'] not in ('full','ask') or expected_folder != row['folder']
            or (current['mode'] == 'full' and
                not needs_explicit_approval(db,user_id,run_id,requested))):
        raise HTTPException(409, 'Permissão alterada ou revogada.')
    enforce_run_scope(db,user_id,run_id,write=(requested.get('action') in ('mkdir','write','replace','command')
                      or (requested.get('action') == 'preview' and requested.get('operation') == 'start')))
    if datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
        raise HTTPException(409, 'Autorização expirada.')
    changed = db.execute("UPDATE workspace_action_approvals SET status=? WHERE id=? AND status='pending'",
                         ('approved' if approved else 'denied', approval_id))
    if changed != 1:
        raise HTTPException(409, 'Autorização já respondida por outra solicitação.')
    return {'ok': True, 'approved': approved}


class ApprovalEngine:
    """Bound, injectable approval service preserving one-time scope checks."""
    def __init__(self, db):
        self.db = db

    def issue(self, user_id, run_id, step_id, folder, request, summary):
        return issue_approval(self.db, user_id, run_id, step_id, folder, request, summary)

    def decide(self, user_id, run_id, approval_id, approved):
        return decide(self.db, user_id, run_id, approval_id, approved)

    def required(self, user_id, run_id, request):
        from .workspace_tools import needs_explicit_approval
        return needs_explicit_approval(self.db, user_id, run_id, request)
