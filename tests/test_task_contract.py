"""Task-to-action contracts: model prose is not filesystem or test evidence."""
import json
import pytest

from central.task_contract import (
    is_implementation_request, is_workspace_inspection_request,
    needs_workspace_tools, delivery_evidence, is_continuation_request,
    resolve_continuation_prompt,
    assert_implementation_delivered, assert_inspection_performed,
    requires_browser_validation,
)


class FakeEvents:
    def __init__(self):
        self.events = []

    def add(self, kind, **payload):
        self.events.append({
            'seq': len(self.events) + 1,
            'event': kind,
            'payload': json.dumps(payload, ensure_ascii=False),
        })

    def all(self, query, args):
        assert args == ('run',)
        return list(self.events)


def test_nova_studio_long_implementation_request_is_not_just_a_plan():
    prompt = ('Desenvolva uma landing page premium NOVA STUDIO em React. '
              'Crie componentes, implemente visual moderno e execute os testes.')
    assert is_implementation_request(prompt)
    assert needs_workspace_tools(prompt)
    assert not is_workspace_inspection_request(prompt)


def test_explicit_chrome_devtools_request_requires_live_browser_validation():
    prompt = ('Desenvolva o app local e use Chrome DevTools MCP para testar '
              'snapshot, console e Lighthouse.')
    assert requires_browser_validation(prompt)
    assert not requires_browser_validation('Corrija uma função Python e rode pytest.')


@pytest.mark.parametrize('prompt', [
    'verique os documentos e me de um ressumo dos projetos nela',
    'Liste os arquivos do workspace antes de analisar os projetos',
    'Leia os documentos desta pasta e resuma os requisitos',
])
def test_local_file_inspection_must_use_real_tools(prompt):
    assert is_workspace_inspection_request(prompt)
    assert needs_workspace_tools(prompt)


@pytest.mark.parametrize('prompt', [
    'Crie um prompt para desenvolver uma landing page',
    'Explique o que é React e como funciona',
    'Planeje o sistema sem modificar arquivos',
    'Me dê ideias de um ecommerce',
])
def test_text_or_prompt_writing_remains_possible_without_computer_access(prompt):
    assert not needs_workspace_tools(prompt)


def test_text_only_architect_cannot_complete_implementation():
    db = FakeEvents()
    with pytest.raises(RuntimeError, match='nenhum arquivo'):
        assert_implementation_delivered(db, {'id': 'run'})


def test_short_project_continuation_inherits_prior_implementation_and_evidence():
    from central.database import Database, uid, utcnow

    db = Database(':memory:')
    try:
        user, conversation, previous_run = 'user', 'chat', 'previous-run'
        now = utcnow()
        db.execute('INSERT INTO users VALUES(?,?,?,?)',
                   (user, 'test@example.com', 'hash', now))
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)',
                   (conversation, user, 'Project', None, now, now))
        original = ('Desenvolva uma landing page NOVA STUDIO em React. '
                    'Crie a interface real e execute o build.')
        db.execute(
            'INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,'
            'plan,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (previous_run, user, conversation, original, 'completed', 'auto', '[]',
             '[]', now, now))
        db.event(previous_run, 'workspace_action_result', {
            'success': True, 'summary': {'action': 'write', 'path': 'src/App.jsx'}})
        continuation = 'continue o projeto'

        assert is_continuation_request(continuation)
        resolved = resolve_continuation_prompt(db, conversation, continuation)

        assert resolved != continuation
        assert original in resolved
        assert 'src/App.jsx' in resolved
        assert 'não comprovados como aprovados' in resolved
        assert is_implementation_request(resolved)
        assert needs_workspace_tools(resolved)
        from central.run_policy import classify_task
        assert classify_task(resolved)['task_type'] == 'code'
        assert resolve_continuation_prompt(db, 'other-chat', continuation) == continuation
        assert resolve_continuation_prompt(db, conversation, 'Explique React') == 'Explique React'
    finally:
        db.close()


@pytest.mark.parametrize('prompt', [
    'continue o projeto sem alterar arquivos',
    'continue o projeto, apenas explique o plano',
])
def test_non_mutating_followup_is_not_treated_as_implementation_continuation(prompt):
    assert not is_continuation_request(prompt)


def test_build_without_actual_edits_fails_evidence():
    db = FakeEvents()
    db.add('workspace_validation', passed=True, results=[])
    with pytest.raises(RuntimeError, match='nenhum arquivo'):
        assert_implementation_delivered(db, {'id': 'run'})


def test_build_before_code_edit_does_not_count_as_validated_delivery():
    db = FakeEvents()
    db.add('workspace_validation', passed=True, results=[])
    db.add('workspace_action_result', success=True,
           summary={'action': 'replace', 'path': 'src/App.jsx'})
    with pytest.raises(RuntimeError, match='DEPOIS'):
        assert_implementation_delivered(db, {'id': 'run'})


def test_failing_last_validation_overrides_prior_success():
    db = FakeEvents()
    db.add('workspace_action_result', success=True,
           summary={'action': 'write', 'path': 'src/App.jsx'})
    db.add('workspace_validation', passed=True, results=[])
    db.add('workspace_validation', passed=False, results=[])
    with pytest.raises(RuntimeError, match='testes/build'):
        assert_implementation_delivered(db, {'id': 'run'})


def test_only_verified_edits_and_post_edit_build_can_complete_run():
    db = FakeEvents()
    db.add('workspace_action_result', success=True,
           summary={'action': 'read', 'path': 'src/App.jsx'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'replace', 'path': 'src/App.jsx'})
    db.add('workspace_validation', passed=True, results=[
        {'command': 'npm_build', 'success': True, 'exit_code': 0},
    ])
    evidence = assert_implementation_delivered(db, {'id': 'run'})
    assert evidence['changed_files'] == ['src/App.jsx']
    assert evidence['tests_passed'] is True
    assert evidence['validation_after_last_change'] is True


def test_browser_requested_delivery_requires_snapshot_console_and_lighthouse_after_edits():
    db = FakeEvents()
    db.add('workspace_action_result', success=True,
           summary={'action': 'replace', 'path': 'src/App.jsx'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'take_snapshot'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'list_console_messages'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'lighthouse_audit'})
    db.add('workspace_validation', passed=True, results=[
        {'command': 'npm_test', 'success': True},
    ])
    evidence = assert_implementation_delivered(
        db, {'id': 'run'}, require_browser=True)
    assert evidence['browser_tools'] == [
        'lighthouse_audit', 'list_console_messages', 'take_snapshot']


def test_browser_validation_before_last_edit_does_not_prove_delivery():
    db = FakeEvents()
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'take_snapshot'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'list_console_messages'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'lighthouse_audit'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'replace', 'path': 'src/App.jsx'})
    db.add('workspace_validation', passed=True, results=[])
    with pytest.raises(RuntimeError, match='Chrome DevTools'):
        assert_implementation_delivered(
            db, {'id': 'run'}, require_browser=True)


def test_autonomous_delivery_requires_reviewer_to_read_changed_code():
    db = FakeEvents()
    db.add('workspace_action_result', success=True,
           summary={'action': 'replace', 'path': 'src/App.jsx'})
    db.add('workspace_validation', passed=True, results=[])
    with pytest.raises(RuntimeError, match='Revisão não comprovada'):
        assert_implementation_delivered(
            db, {'id': 'run'}, require_review_step_id='review-step')

    db.add('workspace_action_result', success=True, step_id='review-step',
           summary={'action': 'read', 'path': 'src/App.jsx'})
    evidence = assert_implementation_delivered(
        db, {'id': 'run'}, require_review_step_id='review-step')
    assert evidence['inspected'][-1]['step_id'] == 'review-step'


def test_document_summary_requires_content_read_not_just_file_names():
    db = FakeEvents()
    db.add('workspace_action_result', success=True,
           summary={'action': 'list', 'path': ''})
    with pytest.raises(RuntimeError, match='Leitura não comprovada'):
        assert_inspection_performed(
            db, {'id': 'run', 'prompt': 'Leia os documentos e resuma o projeto'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'read', 'path': 'requirements.md'})
    evidence = assert_inspection_performed(
        db, {'id': 'run', 'prompt': 'Leia os documentos e resuma o projeto'})
    assert len(evidence['inspected']) == 2

def test_every_required_browser_check_must_follow_last_edit():
    db = FakeEvents()
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'take_snapshot'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'list_console_messages'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'replace', 'path': 'src/App.jsx'})
    db.add('workspace_action_result', success=True,
           summary={'action': 'browser_tool', 'tool': 'lighthouse_audit'})
    db.add('workspace_validation', passed=True, results=[])
    with pytest.raises(RuntimeError, match='Ferramentas pendentes'):
        assert_implementation_delivered(db, {'id': 'run'}, require_browser=True)
