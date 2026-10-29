"""Read-only evaluation of real routing; fixture embeddings are not live inference.

Run ``python -m central.context_evaluation`` for the versioned corpus in a fresh
temporary SQLite database. No provider calls or production database are used.
``evaluate(db, cases)`` only reads an existing database and never seeds it.
"""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .database import Database
from .task_contract import (
    delivery_evidence, is_implementation_request, is_workspace_inspection_request,
    resolve_continuation_prompt,
)

DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / 'docs' / 'context-evaluation-corpus.json'


class _ObservedDatabase:
    """Record evidence reads made by the real resolver, not inferred citations."""

    def __init__(self, db):
        self.db = db
        self.source_run_ids = []

    def all(self, query, args=()):
        rows = self.db.all(query, args)
        if 'FROM events' in query and 'workspace_action_result' in query:
            self.source_run_ids.append(args[0])
        return rows


def evaluate(db, cases):
    """Return per-case actual behavior, provenance and explicit failed checks.

    Cases identify an authorized user/conversation/project and an ``expect``
    object. Supported expectations: expanded, implementation, inspection,
    clarification_required, source_run_ids, recorded_changed_files, contains,
    excludes, scope_error.
    Clarification means an instruction in the resolved prompt, not proof that
    a model asked a question. Scope preconditions here are harness checks;
    authentication of the application's endpoint is outside this evaluation.
    """
    results = []
    ids = set()
    supported = {'expanded', 'implementation', 'inspection', 'clarification_required',
                 'source_run_ids', 'recorded_changed_files', 'contains', 'excludes', 'scope_error'}
    for case in cases:
        case_id = case['id']
        if case_id in ids or not case.get('expect') or set(case['expect']) - supported:
            raise ValueError('Duplicate case ID or invalid expectations: ' + case_id)
        ids.add(case_id)
        observed = _ObservedDatabase(db)
        prompt = case['prompt']
        conversation = db.one('SELECT user_id,project_id FROM conversations WHERE id=?',
                              (case['conversation_id'],))
        scope_error = (not conversation or conversation['user_id'] != case['user_id'] or
                       conversation['project_id'] != case.get('project_id'))
        errors = []
        provenance = []
        resolved = prompt
        if scope_error and case['expect'].get('scope_error') is not True:
            errors.append('scope_mismatch: user/conversation/project precondition failed')
        if not scope_error:
            try:
                resolved = resolve_continuation_prompt(observed, case['conversation_id'], prompt)
            except Exception as exc:
                errors.append('resolver_error: ' + type(exc).__name__ + ': ' + str(exc))
        for source_id in observed.source_run_ids:
            source = db.one('SELECT r.conversation_id,r.user_id,c.project_id FROM runs r '
                            'JOIN conversations c ON c.id=r.conversation_id WHERE r.id=?', (source_id,))
            if (not source or source['conversation_id'] != case['conversation_id'] or
                    source['user_id'] != case['user_id'] or
                    source['project_id'] != case.get('project_id')):
                errors.append('source_outside_scope: ' + str(source_id))
            else:
                evidence = delivery_evidence(db, source_id)
                provenance.append(dict(source, run_id=source_id,
                                       recorded_changed_files=evidence['changed_files'],
                                       validation_verified=(evidence['tests_passed'] and
                                                            evidence['validation_after_last_change'])))
        lower = resolved.casefold()
        actual = {
            'expanded': resolved != prompt,
            'implementation': is_implementation_request(resolved),
            'inspection': is_workspace_inspection_request(resolved),
            'clarification_required': 'esclarecimento' in lower,
            'source_run_ids': list(dict.fromkeys(observed.source_run_ids)),
            'recorded_changed_files': list(dict.fromkeys(
                path for source in provenance for path in source['recorded_changed_files'])),
            'scope_error': bool(scope_error),
        }
        for key, expected in case['expect'].items():
            if key == 'contains':
                errors.extend('missing_text: ' + text for text in expected if text not in resolved)
            elif key == 'excludes':
                errors.extend('unexpected_text: ' + text for text in expected if text in resolved)
            elif actual[key] != expected:
                errors.append(f'{key}: expected {expected!r}, got {actual[key]!r}')
        results.append({'id': case_id, 'passed': not errors, 'errors': errors,
                        'actual': actual, 'provenance': provenance, 'resolved_prompt': resolved})
    passed = sum(result['passed'] for result in results)
    return {'mode': 'deterministic_real_resolver', 'live_inference': False,
            'benchmark_complete': False, 'total': len(results), 'passed': passed,
            'failed': len(results) - passed, 'results': results}


def seed_fixture(db, corpus):
    """Seed only an empty, disposable evaluation database, never an existing app."""
    if db.one('SELECT COUNT(*) n FROM users')['n']:
        raise ValueError('Evaluation fixtures require an empty database.')
    fixture = corpus['fixture']
    now = '2026-10-29T12:00:00+00:00'
    for user in fixture['users']:
        db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, user + '@example.test', 'fixture', now))
    for project in fixture['projects']:
        db.execute('INSERT INTO projects(id,user_id,name,description,created_at) VALUES(?,?,?,?,?)',
                   (project['id'], project['user_id'], project['name'], '', now))
    for chat in fixture['conversations']:
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                   (chat['id'], chat['user_id'], chat['id'], chat.get('project_id'), now, now))
    for run in fixture['runs']:
        db.execute('INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,'
                   'output,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (run['id'], run['user_id'], run['conversation_id'], run['prompt'],
                    run.get('status', 'completed'), 'team', '[]', '[]', run.get('output'), now, now))
        for event in run.get('events', []):
            db.event(run['id'], event['event'], event['payload'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args(argv)
    corpus = json.loads(args.corpus.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='central-context-evaluation-') as folder:
        db = Database(Path(folder) / 'evaluation.sqlite')
        try:
            seed_fixture(db, corpus)
            report = evaluate(db, corpus['cases'])
        finally:
            db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(report['failed']))


if __name__ == '__main__':
    raise SystemExit(main())
