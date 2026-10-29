"""Agent templates, role recovery and deterministic team selection."""
from .task_contract import _plain

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
ROLE_SIGNALS = {
    'architecture': ('arquiteto', 'arquiteta', 'arquitetura', 'solution architect', 'software architect'),
    'frontend': ('frontend', 'front-end', 'react', 'interface', 'desenvolvedor web', 'web developer'),
    'backend': ('backend', 'back-end', 'api', 'servidor', 'desenvolvedor backend', 'backend developer'),
    'design': ('designer', 'design visual', 'ux designer', 'ui designer', 'experiencia do usuario'),
    'code': ('programador', 'programadora', 'desenvolvedor', 'desenvolvedora', 'software engineer', 'engenheiro de software', 'programacao'),
    'review': ('revisor', 'revisora', 'qa', 'quality assurance', 'testador', 'testadora', 'auditoria', 'qualidade'),
    'research': ('pesquisador', 'pesquisadora', 'researcher', 'pesquisa', 'analista de pesquisa'),
    'devops': ('devops', 'sre', 'infraestrutura', 'infrastructure', 'platform engineer', 'engenheiro de confiabilidade'),
    'video': ('video', 'legendas', 'legendagem', 'transcricao', 'editor de video'),
    'coordination': ('coordenador', 'coordenadora', 'coordinator', 'gerente de projeto', 'project manager'),
}


def _contains_signal(text, signal):
    return f' {_plain(signal)} ' in f' {text} '


def suggested_agent_specialty(agent):
    """Infer a role only from a clear profile match; ambiguous agents stay unchanged."""
    default = suggested_default_specialty(agent)
    if default:
        return default
    name = _plain(agent.get('name', ''))
    instructions = _plain(agent.get('instructions', ''))
    scores = {}
    for specialty, signals in ROLE_SIGNALS.items():
        named = any(_contains_signal(name, signal) for signal in signals)
        described = sum(_contains_signal(instructions, signal) for signal in signals)
        scores[specialty] = (4 if named else 0) + min(2, described)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < 2 or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None
    return ranked[0][0]


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
    order = (('frontend', 'code') if ui else
             ('backend', 'code') if api else
             ('code', 'frontend', 'backend'))
    def select(specialties, exclude):
        return next((a for specialty in specialties for a in available
                     if effective_specialty(a) == specialty and a['id'] not in exclude), None)
    result = []
    from .task_contract import requested_text_change
    stages = (order, ('review',)) if requested_text_change(prompt) else (
        ('architecture', 'coordination'), ('research',), order, ('review',))
    for candidates in stages:
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


class AgentRegistry:
    """User-scoped agent storage and deterministic selection policy."""
    def __init__(self, db):
        self.db = db

    def enabled(self, user_id):
        return self.db.all('SELECT * FROM agents WHERE user_id=? AND enabled=1', (user_id,))

    def get(self, user_id, agent_id):
        return self.db.one('SELECT * FROM agents WHERE id=? AND user_id=?', (agent_id, user_id))

    def select(self, agents, prompt, mode='auto', agent_ids=None):
        return discover_agents(agents, prompt, mode, agent_ids)
