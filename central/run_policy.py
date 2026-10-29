"""Explainable, deterministic task classification and execution policies.

These rules are informational and constrain workflows; they DO NOT grant
workspace permissions or bypass the existing validation/approval controls.
"""
from .task_contract import (is_implementation_request,
                            is_workspace_inspection_request)

POLICY_VERSION = 2


def classify_task(prompt, autonomous=False):
    if is_implementation_request(prompt):
        task_type = 'code'
        capabilities = ['workspace_write', 'workspace_read']
        checks = ['actual_file_change', 'build_or_test_after_change']
        review = True
        reason = 'Pedido de criar ou alterar um elemento do projeto; exige ferramentas e evidências.'
    elif is_workspace_inspection_request(prompt):
        task_type = 'inspection'
        capabilities = ['workspace_read']
        checks = ['recorded_read_or_listing']
        review = False
        reason = 'Pedido de diagnóstico ou consulta do projeto; exige leitura, sem obrigação de editar.'
    else:
        task_type = 'conversation'
        capabilities = []
        checks = []
        review = False
        reason = 'Pergunta, explicação ou pedido sem uma alteração concreta identificada.'
    return {
        'policy_version': POLICY_VERSION,
        'task_type': task_type,
        'interpretation_reason': reason,
        'capabilities': capabilities,
        'required_checks': checks,
        'requires_workspace': bool(capabilities),
        'requires_approval': bool(capabilities) and not autonomous,
        'recommended_review': review,
        'autonomous_requested': bool(autonomous),
    }


def validate_run_policy(classification, autonomous):
    if classification['requires_workspace'] and not autonomous:
        raise ValueError(
            'Esta tarefa exige acesso real ao workspace. Autorize uma pasta '
            'em Computador e ative Autonomia; não é permitido simular alterações.')
    return classification
