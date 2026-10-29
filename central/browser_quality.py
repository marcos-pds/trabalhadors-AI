"""Deterministic quality verdicts for approved Chrome DevTools responses.

A successful MCP call only means the tool ran; it does not mean the UI passed.
This module consumes tool outputs as untrusted data and never grants access.
"""
import json
import re

QUALITY_TOOLS = frozenset({'take_snapshot', 'list_console_messages', 'lighthouse_audit'})


def _report_text(result):
    payload = result.get('output')
    if not isinstance(payload, str):
        return ''
    try:
        parsed = json.loads(payload)
    except (ValueError, TypeError):
        return payload[:120000]
    if isinstance(parsed, dict) and isinstance(parsed.get('text'), str):
        return parsed['text'][:120000]
    return ''


def assess(tool, result):
    """Return qa_pass/qa_issue for QA tools, never guess a passing result."""
    if tool not in QUALITY_TOOLS:
        return {}
    if result.get('success') is not True:
        return {'qa_pass': False, 'qa_issue': 'A chamada DevTools não foi concluída.'}
    report = _report_text(result)
    if not report.strip():
        return {'qa_pass': False, 'qa_issue': 'O DevTools não retornou evidência interpretável.'}
    if tool == 'take_snapshot':
        if not re.search(r'\bRootWebArea\b', report):
            return {'qa_pass': False, 'qa_issue': 'Snapshot sem árvore da página (RootWebArea).'}
        return {'qa_pass': True, 'qa_issue': ''}
    if tool == 'list_console_messages':
        if '## Console messages' not in report:
            return {'qa_pass': False, 'qa_issue': 'Resposta de console sem identificação verificável.'}
        errors = len(re.findall(r'\[error\]', report, flags=re.IGNORECASE))
        if errors:
            return {'qa_pass': False, 'qa_issue': f'Console contém {errors} mensagem(ns) de erro.'}
        page = re.search(r'Showing\s+(\d+)\s*-\s*(\d+)\s+of\s+(\d+)', report)
        if page and int(page.group(2)) < int(page.group(3)):
            return {'qa_pass': False, 'qa_issue': 'Console paginado: ainda há mensagens não inspecionadas.'}
        if '<no console messages found>' not in report and not re.search(
                r'\bmsgid=\d+\b', report):
            return {'qa_pass': False, 'qa_issue': 'Console sem lista ou indicação de ausência de mensagens.'}
        return {'qa_pass': True, 'qa_issue': ''}
    if '## Lighthouse Audit Results' not in report:
        return {'qa_pass': False, 'qa_issue': 'Relatório Lighthouse ausente ou inválido.'}
    failed = re.search(r'^\s*Failed:\s*(\d+)\s*$', report, re.MULTILINE)
    if not failed:
        return {'qa_pass': False, 'qa_issue': 'Lighthouse não informou o total de auditorias reprovadas.'}
    count = int(failed.group(1))
    if count:
        return {'qa_pass': False, 'qa_issue': f'Lighthouse identificou {count} auditoria(s) reprovada(s).'}
    return {'qa_pass': True, 'qa_issue': ''}
