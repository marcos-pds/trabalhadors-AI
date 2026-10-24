"""Durable, user-scoped worker checkpoints for explicit continuation.

Only the model/tool conversational context is persisted, never provider API keys.
Filesystem changes are not rolled back; safety still comes from per-action
permission checks, hashes and the restricted command allowlist.
"""
import json
from .database import utcnow

MAX_RESUMES = 8
MAX_TRANSCRIPT_CHARS = 105000


class WorkerPaused(RuntimeError):
    """A recoverable per-segment resource limit, not a provider failure."""


def load_checkpoint(db, user_id, run_id, step_id, folder):
    row = db.one(
        'SELECT * FROM worker_checkpoints WHERE step_id=? AND run_id=? AND user_id=?',
        (step_id, run_id, user_id))
    if not row:
        return None
    if row['folder'] != folder:
        raise RuntimeError(
            'A pasta autorizada mudou desde o checkpoint. '
            'Restaure a pasta original antes de continuar esta tarefa.')
    try:
        row['transcript'] = json.loads(row['transcript_json'])
        row['changed_files'] = json.loads(row['changed_files_json'])
        row['observed_actions'] = json.loads(row['observed_actions_json'])
    except (ValueError, TypeError) as exc:
        raise RuntimeError('Checkpoint corrompido. Não é seguro retomar automaticamente.') from exc
    return row


def save_checkpoint(db, user_id, run_id, step_id, folder, transcript, *,
                    changed_files, observed_actions, validation_failures,
                    rounds_total, actions_total, state='working',
                    last_action='', last_result='', last_validation=''):
    # Save a bounded tail plus original user request. Strip oldest tool exchanges,
    # not the original instructions or the latest read hashes/validation messages.
    preserved = [dict(role=m.get('role', 'user'), content=str(m.get('content', ''))[:16000])
                 for m in transcript if isinstance(m, dict)]
    if len(preserved) > 13:
        preserved = [preserved[0]] + preserved[-12:]
    while len(json.dumps(preserved, ensure_ascii=False)) > MAX_TRANSCRIPT_CHARS and len(preserved) > 2:
        preserved.pop(1)
    db.execute(
        """INSERT INTO worker_checkpoints
           (step_id,run_id,user_id,folder,transcript_json,changed_files_json,
            observed_actions_json,validation_failures,rounds_total,actions_total,
            state,last_action,last_result,last_validation,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(step_id) DO UPDATE SET
            transcript_json=excluded.transcript_json,
            changed_files_json=excluded.changed_files_json,
            observed_actions_json=excluded.observed_actions_json,
            validation_failures=excluded.validation_failures,
            rounds_total=excluded.rounds_total,
            actions_total=excluded.actions_total,
            state=excluded.state,last_action=excluded.last_action,
            last_result=excluded.last_result,
            last_validation=excluded.last_validation,
            updated_at=excluded.updated_at""",
        (step_id, run_id, user_id, folder,
         json.dumps(preserved, ensure_ascii=False),
         json.dumps(sorted(set(changed_files))),
         json.dumps(sorted(set(observed_actions))), int(validation_failures),
         int(rounds_total), int(actions_total), state,
         str(last_action)[:180], str(last_result)[:1200],
         str(last_validation)[:1800], utcnow()))


def checkpoint_summary(db, user_id, run_id):
    rows = db.all(
        'SELECT step_id,state,changed_files_json,observed_actions_json,'
        'rounds_total,actions_total,resumes,last_action,last_result,last_validation,updated_at '
        'FROM worker_checkpoints WHERE run_id=? AND user_id=? ORDER BY updated_at DESC',
        (run_id, user_id))
    results = []
    for row in rows:
        try:
            changes = json.loads(row['changed_files_json'])
            observed = json.loads(row['observed_actions_json'])
        except (ValueError, TypeError):
            changes, observed = [], []
        results.append({
            'step_id': row['step_id'], 'state': row['state'],
            'changed_files': changes[:40], 'observed_actions': observed,
            'rounds_total': row['rounds_total'], 'actions_total': row['actions_total'],
            'resumes': row['resumes'], 'last_action': row['last_action'],
            'last_result': row['last_result'],
            'last_validation': row['last_validation'],
            'updated_at': row['updated_at'],
        })
    return results



def legacy_step_progress(db, run_id, step_id):
    """Recover safe, metadata-only progress from runs made before checkpoints.

    Read/write contents are never replayed from the event journal. The resumed
    worker must inspect current files; previous writes are detected using
    authoritative successful action events, not model claims.
    """
    rows = db.all(
        "SELECT event,payload FROM events WHERE run_id=? AND "
        "event IN ('workspace_action_result','worker_message','workspace_validation') "
        "ORDER BY seq DESC LIMIT 180", (run_id,))
    changed = set()
    actions = []
    last_validation = ''
    for item in rows:
        try:
            data = json.loads(item['payload'])
        except (TypeError, ValueError):
            continue
        if data.get('step_id') != step_id:
            continue
        if item['event'] == 'workspace_validation' and not last_validation:
            last_validation = json.dumps({
                'passed': data.get('passed') is True,
                'checks': data.get('results', [])}, ensure_ascii=False)[:1200]
        if item['event'] == 'workspace_action_result':
            summary = data.get('summary') or {}
            action = summary.get('action')
            path = summary.get('path') or ''
            success = data.get('success') is True
            if success and action in ('write', 'replace') and path:
                changed.add(path)
            if len(actions) < 10:
                actions.append((action or 'ferramenta') + ' ' + str(path)[:90] +
                               (' · sucesso' if success else ' · falhou'))
    return {'changed_files': sorted(changed),
            'actions': list(reversed(actions)),
            'last_validation': last_validation}
