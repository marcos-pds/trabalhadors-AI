"""Agent templates, role recovery and deterministic team selection."""
TEMPLATES = [
 ('Arquiteto IA','architecture','Planeje soluções técnicas de maneira clara. Defina dependências, interfaces e critérios de aceite.','◈'),
 ('Frontend IA','frontend','Implemente frontend com foco em UX, acessibilidade, componentes reais e responsividade.','◇'),
 ('Backend IA','backend','Projete e implemente APIs, autenticação, persistência, validações e segurança.','⬡'),
 ('Designer IA','design','Produza direção visual, UI elegante, microinterações, hierarquia tipográfica e experiência do usuário.','✺'),
 ('Programador IA','code','Implemente código completo, coerente, legível e testável.','⌘'),
 ('Revisor IA','review','Analise resultados criticamente, aponte defeitos e valide critérios com rigor.','✓'),
 ('Pesquisador IA','research','Pesquise e compare alternativas. Sem ferramenta de busca, reconheça limitações e não invente referências.','◎'),
 ('DevOps IA','devops','Pipelines, infraestrutura, observabilidade, confiabilidade e execução segura.','⚙'),
 ('Vídeo e Legendas IA','video','Oriente transcrição, legendagem, edição e automação de vídeos.','▣'),
 ('Coordenador IA','coordination','Una resultados, priorize entregas e explique decisões e pendências.','✦'),
]


STANDARD_SPECIALTIES = {name: (specialty, instructions)
                        for name, specialty, instructions, _avatar in TEMPLATES}


def suggested_default_specialty(agent):
    """Recover the role of an unchanged factory agent, never an arbitrary custom agent.

    Only the exact built-in name plus the original system instructions qualifies.
    User-customized instructions and renamed workers keep their configured role.
    """
    template = STANDARD_SPECIALTIES.get(agent.get('name'))
    if template and (agent.get('instructions') or '').strip() == template[1].strip():
        return template[0]
    return None


def effective_specialty(agent):
    return suggested_default_specialty(agent) or agent['specialty']


def recoverable_default_agents(agents):
    """Offer an explicit migration to fix incorrectly saved factory specialties."""
    return [dict(agent, suggested_specialty=suggested_default_specialty(agent))
            for agent in agents if suggested_default_specialty(agent)
            and agent['specialty'] != suggested_default_specialty(agent)]


def team_for_task(agents, prompt):
    """Select planning, an implementation specialist, and review in order."""
    available = [a for a in agents if a['enabled']]
    if not available:
        return []
    lowered = prompt.casefold()
    from .task_contract import _plain
    normalized = _plain(prompt)
    ui = any(x in normalized for x in
             ('landing page', 'landing-page', 'frontend', 'front-end', 'interface',
              'react', 'pagina', 'website', 'design visual', 'layout'))
    api = any(x in normalized for x in
              ('backend', 'back-end', 'api', 'autenticacao', 'servidor', 'banco de dados'))
    order = (('frontend', 'code', 'backend') if ui else
             ('backend', 'code', 'frontend') if api else
             ('code', 'frontend', 'backend'))
    def select(specialties, exclude):
        return next((a for specialty in specialties for a in available
                     if effective_specialty(a) == specialty and a['id'] not in exclude), None)
    result = []
    for candidates in (('architecture', 'coordination'), order,
                       ('review',)):
        pick = select(candidates, {a['id'] for a in result})
        if pick is not None:
            result.append(pick)
    return result


KEYWORDS = {
 'architecture': ['arquitet','arquitetura','sistema','estrutura','dependência','design técnico'],
 'frontend': ['frontend','front-end','react','interface','componente','css','html','tela','página','dashboard'],
 'backend': ['backend','back-end','api','servidor','banco','database','autenticação','login','endpoint'],
 'design': ['design','layout','visual','estilo','figma','ui','identidade'],
 'research': ['pesquis','compare','compar','estud','analis'],
 'devops': ['deploy','docker','devops','infra','ci/cd','pipeline'],
 'video': ['vídeo','video','legenda','transcri','reels'],
 'code': ['código','program','função','script','bug','corrij'],
 'review': ['revis','avalie','valid','auditoria','qualidade','critique'],
 'coordination': ['coordene','organize','resuma','sintetize','equipe','multiagente'],
}


def discover_agents(agents, prompt, mode='auto', agent_ids=None):
    candidates = [a for a in agents if a['enabled']]
    if agent_ids:
        selected = [a for a in candidates if a['id'] in agent_ids]
        return selected[:5]
    if not candidates: return []
    if mode == 'manual': return candidates[:1]
    lower = prompt.lower()
    specialties = [name for name, words in KEYWORDS.items() if any(w in lower for w in words)]
    filtered = [a for a in candidates if effective_specialty(a) in specialties]
    if mode == 'team':
        # 'Equipe' must never be silently reduced to the single keyword match.
        selected = filtered[:2]
        for specialty in ('architecture', 'code', 'review'):
            agent = next((a for a in candidates if effective_specialty(a) == specialty), None)
            if agent and agent not in selected:
                selected.append(agent)
            if len(selected) >= 3:
                break
        if len(selected) < 2:
            selected.extend(a for a in candidates if a not in selected)
        return selected[:3]
    return filtered[:3] if filtered else [next((a for a in candidates if effective_specialty(a)=='coordination'), candidates[0])]
