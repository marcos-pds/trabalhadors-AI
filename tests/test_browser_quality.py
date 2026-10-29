"""Quality verdicts are based on actual DevTools output, not successful transport."""
import json

import pytest

from central.browser_quality import assess


def _result(text):
    return {'success': True, 'output': json.dumps({'text': text})}


@pytest.mark.parametrize('tool, text', [
    ('take_snapshot', '## Latest page snapshot\nuid=1_0 RootWebArea "Meu app"'),
    ('list_console_messages', '## Console messages\n<no console messages found>'),
    ('list_console_messages', '## Console messages\nShowing 1-1 of 1 (Page 1 of 1).\nmsgid=1 [info] ok'),
    ('lighthouse_audit', '## Lighthouse Audit Results\n### Audit Summary\nPassed: 46\nFailed: 0'),
])
def test_real_clean_reports_qualify(tool, text):
    assert assess(tool, _result(text)) == {'qa_pass': True, 'qa_issue': ''}


@pytest.mark.parametrize('tool, text, issue', [
    ('take_snapshot', 'No page selected', 'Snapshot'),
    ('list_console_messages',
     '## Console messages\nmsgid=1 [error] Failed to load resource: 404',
     'Console contém 1'),
    ('list_console_messages',
     '## Console messages\nShowing 1-50 of 70 (Page 1 of 2).\nmsgid=1 [log] ok',
     'paginado'),
    ('lighthouse_audit',
     '## Lighthouse Audit Results\n### Audit Summary\nPassed: 44\nFailed: 2',
     '2 auditoria'),
    ('lighthouse_audit', '## Lighthouse Audit Results\nno data', 'não informou'),
    ('list_console_messages', 'hello', 'sem identificação'),
])
def test_reported_errors_or_missing_evidence_do_not_qualify(tool, text, issue):
    result = assess(tool, _result(text))
    assert result['qa_pass'] is False
    assert issue in result['qa_issue']


def test_transport_success_alone_is_not_quality_approval():
    assert assess('lighthouse_audit', {'success': True, 'output': ''})['qa_pass'] is False
    assert assess('take_snapshot', {'success': False, 'output': ''})['qa_pass'] is False
    assert assess('new_page', {'success': True, 'output': ''}) == {}
