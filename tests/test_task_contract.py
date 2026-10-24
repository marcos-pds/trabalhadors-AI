"""Task-to-action contracts: model prose is not filesystem or test evidence."""
import json
import pytest

from central.task_contract import (
    is_implementation_request, is_workspace_inspection_request,
    needs_workspace_tools, delivery_evidence,
    assert_implementation_delivered, assert_inspection_performed,
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
