"""Workflow graph construction and DAG validation independent of execution."""
from .database import uid

def create_plan(agents, sequential=False):
    if not agents: return []
    jobs = []
    for a in agents:
        deps = [jobs[-1]['id']] if sequential and jobs else []
        jobs.append({'id': uid(), 'agent_id': a['id'], 'name': a['name'],
                     'kind': 'agent', 'deps': deps, 'instructions': ''})
    return jobs


def validate_flow(definition, agents):
    """Small DAG workflow builder, with agent and human approval nodes."""
    nodes = definition.get('nodes', [])
    if not isinstance(nodes, list) or len(nodes) > 20 or not nodes:
        raise ValueError('O fluxo deve conter entre 1 e 20 blocos.')
    ids = {n.get('id') for n in nodes}
    if len(ids) != len(nodes) or None in ids: raise ValueError('IDs de blocos duplicados/inválidos.')
    known_agents = {a['id'] for a in agents}
    for n in nodes:
        if n.get('kind') not in ('agent','approval'):
            raise ValueError('Somente blocos de agente e aprovação são executáveis nesta versão.')
        if n['kind']=='agent' and n.get('agent_id') not in known_agents:
            raise ValueError('O fluxo referencia trabalhador indisponível.')
        if not isinstance(n.get('deps', []),list) or any(d not in ids or d==n['id'] for d in n.get('deps',[])):
            raise ValueError('Dependências de fluxo inválidas.')
    seen = set()
    remaining = nodes[:]
    while remaining:
        ready = [n for n in remaining if all(d in seen for d in n.get('deps',[]))]
        if not ready: raise ValueError('Fluxo contém dependências cíclicas.')
        for n in ready:
            seen.add(n['id'])
            remaining.remove(n)
    return nodes
