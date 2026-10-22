"""Resolve legacy/customized worker specialties without granting broad aliases.

Canonical specialty always wins. An exact built-in worker name may restore the
role if its specialty was changed to an unrecognized descriptive phrase.
A worker explicitly assigned a *different* canonical specialty stays in that role.
"""
import unicodedata

CANONICAL = frozenset({
    'architecture','frontend','backend','design','code','review',
    'research','devops','video','coordination',
})
ROLE_ALIASES = {
    'arquiteto ia':'architecture',
    'frontend ia':'frontend',
    'designer ia':'design',
    'backend ia':'backend',
    'programador ia':'code',
    'revisor ia':'review',
    'pesquisador ia':'research',
    'devops ia':'devops',
    'video e legendas ia':'video',
    'coordenador ia':'coordination',
}
SPECIALTY_ALIASES = {
    'arquitetura':'architecture',
    'arquiteto':'architecture',
    'front-end':'frontend',
    'react frontend':'frontend',
    'design ux/ui':'design',
    'designer':'design',
    'ux/ui':'design',
    'programacao':'code',
    'revisao':'review',
}

def _normalized(value):
    text=unicodedata.normalize('NFKD',str(value or '').casefold())
    text=''.join(ch for ch in text if not unicodedata.combining(ch))
    return ' '.join(text.strip().split())

def worker_role(agent):
    """Resolve a safe worker role from persisted metadata; never mutate records."""
    specialty=_normalized(agent.get('specialty'))
    if specialty in CANONICAL:
        return specialty
    if specialty in SPECIALTY_ALIASES:
        return SPECIALTY_ALIASES[specialty]
    return ROLE_ALIASES.get(_normalized(agent.get('name')),specialty)

def role_source(agent):
    """Human-readable explanation for diagnostics."""
    specialty=_normalized(agent.get('specialty'))
    return 'canonical' if specialty in CANONICAL else (
        'alias' if specialty in SPECIALTY_ALIASES else (
            'name' if _normalized(agent.get('name')) in ROLE_ALIASES else 'unknown'))
