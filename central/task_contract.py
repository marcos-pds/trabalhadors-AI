"""Deterministic execution contract: a text-only answer is not a software delivery.

Classify explicit build requests before dispatch; validate recorded tools, not model
claims, before marking an implementation run as completed. Heuristics are conservative
and can be refined without delegating permission decisions to a model.
"""
import json
import re
import unicodedata


def _plain(text):
    normalized = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in normalized if not unicodedata.combining(c)).lower()


ACTION = re.compile(
    r'\b(?:crie|criar|criem|desenvolva|desenvolver|implemente|implementar|'
    r'construa|construir|programe|programar|codifique|codificar|'
    r'corrija|corrigir|conserte|consertar|adicione|adicionar|'
    r'modifique|modificar|edite|editar|refatore|refatorar)\b'
)
TARGET = re.compile(
    r'\b(?:landing[\s-]*page|pagina[\s-]*web|website|site|'
    r'front[\s-]*end|back[\s-]*end|e-?commerce|loja[\s-]*virtual|'
    r'aplicac(?:ao|oes)|app|api|interface|tela|pagina|componentes?|'
    r'codigo|arquivos?|sistema|projeto|modulo|funcionalidade|bug|'
    r'erro[\s-]*de[\s-]*compilacao)\b'
)
META_REQUEST = re.compile(
    r'\b(?:crie|criar|escreva|escrever|elabore|elaborar|me[\s]+de|gere)'
    r'[\s\w]{0,45}\bprompt\b'
)


def is_implementation_request(prompt):
    """True for explicit requests to actually change software, not to write a prompt."""
    text = _plain(prompt)
    if META_REQUEST.search(text[:180]):
        return False
    return bool(ACTION.search(text) and TARGET.search(text))


def delivery_evidence(db, run_id):
    """Use only server-recorded events, never assertions from AI-generated prose."""
    rows = db.all(
        "SELECT seq,event,payload FROM events WHERE run_id=? "
        "AND event IN ('workspace_action_result','workspace_validation') ORDER BY seq",
        (run_id,))
    changes, validations = [], []
    for row in rows:
        try:
            payload = json.loads(row['payload'])
        except (ValueError, TypeError):
            continue
        if row['event'] == 'workspace_action_result':
            summary = payload.get('summary') or {}
            if (payload.get('success') is True and
                    summary.get('action') in ('write', 'replace')):
                changes.append({'seq': row['seq'], 'path': summary.get('path', '')})
        elif row['event'] == 'workspace_validation':
            validations.append({'seq': row['seq'], 'passed': payload.get('passed') is True,
                                'checks': payload.get('results', [])})
    return {
        'changed_files': list(dict.fromkeys(c['path'] for c in changes)),
        'changed_count': len(changes),
        'tests_passed': bool(validations and validations[-1]['passed']),
        'checks': validations[-1]['checks'] if validations else [],
        'validation_after_last_change': bool(
            validations and changes and validations[-1]['seq'] > changes[-1]['seq']),
    }


def assert_implementation_delivered(db, run):
    """Raise instead of mislabelling a text-only plan as a completed application."""
    evidence = delivery_evidence(db, run['id'])
    if not evidence['changed_files']:
        raise RuntimeError(
            'Entrega não comprovada: nenhum arquivo de código foi criado ou '
            'alterado pelas ferramentas. Uma resposta de planejamento não conclui a tarefa.')
    if not evidence['tests_passed'] or not evidence['validation_after_last_change']:
        raise RuntimeError(
            'Entrega não validada: faltam testes/build aprovados DEPOIS da última '
            'alteração de código. Veja o histórico de ferramentas.')
    return evidence
