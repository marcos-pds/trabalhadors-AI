"""Bounded final-delivery recovery; never replay an entire workflow or approval."""
import json

from .database import utcnow
from .agent_registry import effective_specialty

MAX_DELIVERY_REPAIRS = 2


def queue_delivery_repair(db, registry, run, error, emit):
    if not run.get('autonomous'):
        return False
    # Only called for a failed final evidence contract, never a tool or provider error.
    with db.lock:
        db.conn.execute('BEGIN IMMEDIATE')
        try:
            current = db.one('SELECT status FROM runs WHERE id=?', (run['id'],))
            count = db.one("SELECT COUNT(*) n FROM events WHERE run_id=? AND event='delivery_repair_queued'",
                           (run['id'],))['n']
            if not current or current['status'] != 'running' or count >= MAX_DELIVERY_REPAIRS:
                db.conn.execute('ROLLBACK')
                return False
            candidates = []
            for step in db.all("SELECT * FROM steps WHERE run_id=? AND kind='agent' AND status='completed' ORDER BY rowid DESC",
                               (run['id'],)):
                agent = registry.get(run['user_id'], step['agent_id'])
                if agent and effective_specialty(agent) in ('review', 'code', 'frontend', 'backend'):
                    candidates.append((effective_specialty(agent) == 'review', step))
            if not candidates:
                db.conn.execute('ROLLBACK')
                return False
            step = max(candidates, key=lambda item: item[0])[1]
            note = ('VALIDAÇÃO FINAL REPROVADA (tentativa ' + str(count + 1) +
                    '/' + str(MAX_DELIVERY_REPAIRS) + '): ' + str(error)[:1400] +
                    '\nInspecione o estado atual e corrija apenas a pendência. '
                    'Preserve o escopo original, respeite permissões, não repita ações '
                    'já concluídas e execute novamente as validações após a correção.')
            checkpoint = db.one('SELECT transcript_json FROM worker_checkpoints WHERE run_id=? AND step_id=?',
                                (run['id'], step['id']))
            if checkpoint:
                transcript = json.loads(checkpoint['transcript_json'])
                transcript.append({'role': 'user', 'content': note})
                db.execute("UPDATE worker_checkpoints SET transcript_json=?,state='working',updated_at=? WHERE run_id=? AND step_id=?",
                           (json.dumps(transcript, ensure_ascii=False), utcnow(), run['id'], step['id']))
            db.execute("UPDATE steps SET status='queued',error=NULL,instructions=?,updated_at=? WHERE id=?",
                       (note + '\n' + (step['instructions'] or ''), utcnow(), step['id']))
            db.event(run['id'], 'delivery_repair_queued', {
                'step_id': step['id'], 'attempt': count + 1,
                'limit': MAX_DELIVERY_REPAIRS, 'reason': str(error)[:1400]})
            db.conn.execute('COMMIT')
        except BaseException:
            db.conn.execute('ROLLBACK')
            raise
    # The durable event above is the retry budget, including across restarts.
    emit(run['id'], 'worker_phase', {'step_id': step['id'],
         'stage': 'Corrigindo pendência identificada na validação final'})
    return True
