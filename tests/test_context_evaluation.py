"""Offline contract tests, not a claim about live model or embedding quality."""
import json

import pytest

from central import semantic_memory
from central.context_evaluation import DEFAULT_CORPUS, evaluate, main, seed_fixture
from central.database import Database, utcnow
from central.memory import build_memory, matching_project_messages
from central.task_contract import delivery_evidence


CORPUS = json.loads(DEFAULT_CORPUS.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def no_embedding_network(monkeypatch):
    def denied(_texts):
        raise AssertionError('Live embeddings are forbidden in this deterministic evaluation.')
    monkeypatch.setattr(semantic_memory, 'embed', denied)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / 'evaluation.sqlite')
    seed_fixture(database, CORPUS)
    yield database
    database.close()


@pytest.mark.parametrize('case', CORPUS['cases'], ids=lambda case: case['id'])
def test_versioned_portuguese_corpus_uses_actual_resolver(db, case):
    changes = db.conn.total_changes
    report = evaluate(db, [case])
    assert report['failed'] == 0, report['results']
    assert report['success'] is True
    assert report['total'] == report['passed'] == 1
    assert report['live_inference'] is False
    assert report['benchmark_complete'] is False
    assert db.conn.total_changes == changes


def test_harness_fails_incorrect_expectations_and_is_repeatable(db):
    bad = dict(CORPUS['cases'][0], expect={'expanded': True, 'source_run_ids': ['invented']})
    first = evaluate(db, [bad])
    assert first == evaluate(db, [bad])
    assert first['failed'] == 1
    assert len(first['results'][0]['errors']) == 2
    assert first['results'][0]['actual']['source_run_ids'] == []


def test_full_corpus_reports_actual_results_and_gap_metadata_never_waives_failure(db):
    report = evaluate(db, CORPUS['cases'])
    assert report['status'] == 'passed' and report['success'] is True
    assert report['failed'] == 0
    assert report['total'] == sum(category['total'] for category in report['categories'].values())
    assert report['passed'] == sum(category['passed'] for category in report['categories'].values())
    assert report['pass_rate_percent'] == round(100 * report['passed'] / report['total'], 2)
    # Metadata must never change whether the expectations passed.
    bad = dict(CORPUS['cases'][0], expect={'expanded': True}, known_gap='Not a waiver')
    assert evaluate(db, [bad])['failed'] == 1


def test_category_percentages_are_case_weighted_and_count_failures(db):
    good = dict(CORPUS['cases'][0], id='good', category='create')
    bad = dict(good, id='bad', expect={'expanded': True})
    other = dict(good, id='other', category='change')
    report = evaluate(db, [good, bad, other])
    assert report['pass_rate_percent'] == 66.67
    assert report['categories'] == {
        'create': {'total': 2, 'passed': 1, 'failed': 1, 'pass_rate_percent': 50.0},
        'change': {'total': 1, 'passed': 1, 'failed': 0, 'pass_rate_percent': 100.0},
    }
    assert [case['category'] for case in report['results']] == ['create', 'create', 'change']


def test_empty_evaluation_is_not_success_or_one_hundred_percent(db):
    report = evaluate(db, [])
    assert report['total'] == report['passed'] == report['failed'] == 0
    assert report['status'] == 'empty' and report['success'] is False
    assert report['evaluation_errors'] == ['empty_corpus']
    assert report['pass_rate_percent'] is None
    assert report['categories'] == {} and report['results'] == []
    assert report['live_inference'] is False and report['benchmark_complete'] is False


@pytest.mark.parametrize('cases_key,exit_code', [('empty', 1), ('failing', 1), ('passing', 0), ('corpus', 0)])
def test_cli_exit_code_respects_empty_and_failing_reports(tmp_path, capsys, cases_key, exit_code):
    cases = {'empty': [], 'corpus': CORPUS['cases'], 'passing': [CORPUS['cases'][0]],
             'failing': [dict(CORPUS['cases'][0], expect={'expanded': True})]}[cases_key]
    path = tmp_path / 'corpus.json'
    path.write_text(json.dumps(dict(CORPUS, cases=cases)), encoding='utf-8')
    assert main(['--corpus', str(path)]) == exit_code
    report = json.loads(capsys.readouterr().out)
    assert report['success'] is (exit_code == 0)
    assert report['live_inference'] is False and report['benchmark_complete'] is False


def test_uncategorized_compatibility_and_invalid_categories(db):
    case = dict(CORPUS['cases'][0])
    case.pop('category')
    assert evaluate(db, [case])['categories']['uncategorized']['total'] == 1
    for invalid in ('', ' ', None, []):
        with pytest.raises(ValueError, match='Invalid category'):
            evaluate(db, [dict(case, category=invalid)])


def test_fixture_seeding_refuses_existing_database_and_corpus_is_broad(db):
    with pytest.raises(ValueError, match='empty database'):
        seed_fixture(db, CORPUS)
    assert len(CORPUS['cases']) >= 25
    assert {'create', 'change', 'continue', 'read_only', 'ambiguous', 'isolation'} <= {
        case['category'] for case in CORPUS['cases']}
    with pytest.raises(ValueError, match='Duplicate'):
        evaluate(db, [CORPUS['cases'][0], CORPUS['cases'][0]])


def test_provenance_uses_event_paths_not_untrusted_worker_claims(db):
    case = next(case for case in CORPUS['cases'] if case['id'] == 'continue-bare')
    report = evaluate(db, [dict(case, expect={
        'source_run_ids': ['site-run'], 'recorded_changed_files': ['src/Aurora.jsx']})])
    assert report['failed'] == 0
    result = report['results'][0]
    assert result['provenance'] == [{
        'conversation_id': 'site', 'user_id': 'alice', 'project_id': 'aurora',
        'run_id': 'site-run', 'recorded_changed_files': ['src/Aurora.jsx'],
        'validation_verified': False,
    }]
    assert 'inventado.tsx' not in result['actual']['recorded_changed_files']
    assert 'dado não confiável' in result['resolved_prompt']


def test_scope_mismatch_is_not_a_silent_pass(db):
    case = dict(CORPUS['cases'][0], user_id='bob', expect={'expanded': False})
    result = evaluate(db, [case])
    assert result['failed'] == 1
    assert result['results'][0]['errors'][0].startswith('scope_mismatch')


def add_message(db, message_id, user, conversation, content):
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
               (message_id, conversation, user, 'user', None, content, utcnow()))


@pytest.fixture
def recall_db(db):
    add_message(db, 'auth', 'alice', 'site', 'Sessões usam refresh tokens. MEMORIA-AURORA')
    add_message(db, 'visual', 'alice', 'peer', 'Paleta usa tons violeta. DISTRATOR-VISUAL')
    add_message(db, 'finance-auth', 'alice', 'other',
                'Credenciais do financeiro usam certificados. MEMORIA-FINANCE')
    add_message(db, 'foreign', 'bob', 'private', 'Credenciais SECRET-BOB')
    # A mismatched message owner must also be excluded by the real SQL filters.
    add_message(db, 'mismatched', 'bob', 'site', 'Credenciais SECRET-INCONSISTENTE')
    add_message(db, 'current', 'alice', 'fresh', 'Credenciais HISTORICO-LOCAL')
    return db


@pytest.fixture
def deterministic_provider(monkeypatch):
    calls = []

    def embed(texts):
        # Deliberate fixture semantics; this does not measure an embedding model.
        calls.append(list(texts))
        vectors = []
        for text in texts:
            lower = text.casefold()
            if any(word in lower for word in ('credenciais', 'refresh', 'certificados')):
                vectors.append([1.0, 0.0, 0.0])
            elif any(word in lower for word in ('paleta', 'violeta')):
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors

    monkeypatch.setattr(semantic_memory, 'embed', embed)
    return calls


def test_semantic_relevance_beats_recent_distractor_with_real_project_filters(
        recall_db, deterministic_provider):
    semantic_memory.preference(recall_db, 'alice', 'aurora', True)
    # No lexical overlap: the deterministic provider connects these concepts.
    assert matching_project_messages(recall_db, 'alice', 'aurora', 'fresh', 'credenciais') == []
    memory = build_memory(recall_db, 'alice', 'fresh', 'credenciais')
    assert [source['conversation_id'] for source in memory['sources']] == ['site']
    assert memory['sources'][0]['retrieval'] == 'semantic'
    assert memory['sources'][0]['score'] == 1.0
    assert 'MEMORIA-AURORA' in memory['text']
    assert 'HISTORICO-LOCAL' in memory['text']
    assert 'id=site' in memory['text']
    assert 'DISTRATOR-VISUAL' not in memory['text']
    transmitted = ' '.join(text for batch in deterministic_provider for text in batch)
    assert 'DISTRATOR-VISUAL' in transmitted
    for secret in ('MEMORIA-FINANCE', 'SECRET-BOB', 'SECRET-INCONSISTENTE', 'HISTORICO-LOCAL'):
        assert secret not in transmitted


def test_context_switches_projects_without_reusing_prior_recall(
        recall_db, deterministic_provider):
    for project in ('aurora', 'finance'):
        semantic_memory.preference(recall_db, 'alice', project, True)
    first = build_memory(recall_db, 'alice', 'fresh', 'credenciais')
    second = build_memory(recall_db, 'alice', 'finance-empty', 'credenciais')
    again = build_memory(recall_db, 'alice', 'fresh', 'credenciais')
    assert [source['conversation_id'] for source in first['sources']] == ['site']
    assert [source['conversation_id'] for source in second['sources']] == ['other']
    assert 'MEMORIA-FINANCE' in second['text'] and 'MEMORIA-AURORA' not in second['text']
    assert 'MEMORIA-FINANCE' not in again['text'] and 'MEMORIA-AURORA' in again['text']
    assert deterministic_provider[-1] == ['search_query: credenciais']  # actual cache reuse


def test_semantic_fingerprint_invalidates_changed_source(recall_db, deterministic_provider):
    semantic_memory.preference(recall_db, 'alice', 'aurora', True)
    assert semantic_memory.retrieve(recall_db, 'alice', 'aurora', 'fresh', 'credenciais')
    recall_db.execute("UPDATE messages SET content='Paleta violeta editada' WHERE id='auth'")
    assert semantic_memory.retrieve(recall_db, 'alice', 'aurora', 'fresh', 'credenciais') == []
    assert deterministic_provider[-1] == [
        'search_query: credenciais',
        'search_document: Paleta violeta editada',
    ]


def test_lexical_relevance_and_opt_out_never_call_provider(recall_db):
    memory = build_memory(recall_db, 'alice', 'fresh', 'refresh tokens')
    assert [source['conversation_id'] for source in memory['sources']] == ['site']
    assert all('retrieval' not in source for source in memory['sources'])
    assert 'DISTRATOR-VISUAL' not in memory['text']
    free = build_memory(recall_db, 'alice', 'free-empty', 'refresh tokens')
    assert free['scope'] == 'avulsa' and free['sources'] == []
    assert 'MEMORIA-AURORA' not in free['text']


def test_embedding_failure_retains_real_lexical_recall(recall_db, monkeypatch):
    semantic_memory.preference(recall_db, 'alice', 'aurora', True)

    def failed_provider(_texts):
        raise ValueError('Deterministic unavailable-provider fixture')

    monkeypatch.setattr(semantic_memory, 'embed', failed_provider)
    memory = build_memory(recall_db, 'alice', 'fresh', 'refresh tokens')
    assert [source['conversation_id'] for source in memory['sources']] == ['site']
    assert all('retrieval' not in source for source in memory['sources'])


def test_isolated_events_cannot_prove_root_delivery(db):
    for event, payload in [
        ('workspace_action_result', {'success': True, 'summary': {'action': 'write', 'path': 'isolated.py'}}),
        ('workspace_validation', {'passed': True, 'results': []}),
    ]:
        db.event('peer-run', event, dict(payload, workspace='isolated'))
    evidence = delivery_evidence(db, 'peer-run')
    assert evidence['changed_files'] == []
    assert evidence['tests_passed'] is False
    assert evidence['validation_after_last_change'] is False
    db.event('peer-run', 'workspace_action_result', {
        'success': True, 'summary': {'action': 'write', 'path': 'promoted.py'}})
    db.event('peer-run', 'workspace_validation', {'passed': True, 'results': []})
    # Later isolated failures must not invalidate verified root evidence either.
    db.event('peer-run', 'workspace_action_result', {
        'workspace': 'isolated', 'success': True,
        'summary': {'action': 'write', 'path': 'unpromoted.py'}})
    db.event('peer-run', 'workspace_validation', {'workspace': 'isolated', 'passed': False})
    evidence = delivery_evidence(db, 'peer-run')
    assert evidence['changed_files'] == ['promoted.py']
    assert evidence['tests_passed'] is True
    assert evidence['validation_after_last_change'] is True
