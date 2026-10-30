"""Explicit per-user run exports without provider credentials or workspace paths."""
from fastapi import HTTPException
from .security import require_owned


def run_report(db, user_id, run_id):
    run = require_owned(db, 'runs', run_id, user_id)
    fields = ('id', 'status', 'mode', 'prompt', 'output', 'created_at', 'updated_at', 'total_cost')
    result = {key: run[key] for key in fields}
    result['cost_notice'] = 'Custo estimado; não representa cobrança do provedor.'
    result['steps'] = db.all('SELECT id,name,kind,status,model,attempts,output '
                             'FROM steps WHERE run_id=? ORDER BY rowid', (run_id,))
    return result


def markdown(report):
    content = ['# Relatório de execução', '', 'ID: ' + report['id'],
               'Estado: ' + report['status'], '', '## Solicitação', report['prompt'],
               '', '## Resultado', report['output'] or '(Sem resultado)', '',
               report['cost_notice']]
    for step in report['steps']:
        content.extend(['', '## ' + step['name'], 'Estado: ' + step['status'],
                        '', step['output'] or '(Sem saída)'])
    return '\n'.join(content)
