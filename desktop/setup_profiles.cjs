'use strict'
// Read-only optional component plan; never builds install commands or executes
// them. A detected executable is NOT proof of a usable installation.
const PROFILES = Object.freeze([
  { id: 'essential', title: 'Essencial / desenvolvimento',
    description: 'Git, VS Code e Node para projetos gerados pela Central.',
    components: ['git', 'vscode', 'node'] },
  { id: 'local_ai', title: 'IA local',
    description: 'Ollama, um ou mais modelos aprovados e Codex opcional.',
    components: ['ollama', 'models', 'codex'] },
  { id: 'browser_qa', title: 'QA com navegador',
    description: 'Playwright e Chrome DevTools MCP, com permissões individuais.',
    components: ['playwright', 'browser_mcp', 'node'] },
  { id: 'motion', title: 'AI Motion Studio',
    description: 'Ferramentas de vídeo e geração, com requisitos de GPU próprios.',
    components: ['ffmpeg', 'node', 'whisperx', 'remotion', 'comfyui'] },
])

function planFor(id, inventory) {
  if (!inventory || !Array.isArray(inventory.dependencies))
    throw new TypeError('Inventory is required')
  const profile = PROFILES.find(p => p.id === id)
  if (!profile) throw new RangeError('Unknown installation profile')
  const byId = new Map(inventory.dependencies.map(d => [d.id, d]))
  const requested = profile.components.map(key => {
    const item = byId.get(key)
    if (!item) throw new Error('Component is not in the approved catalog')
    return { id: item.id, label: item.label, state: item.status,
      verified: false, installable: false }
  })
  return {
    schema_version: 1, profile: profile.id, title: profile.title,
    description: profile.description, components: requested,
    installs_performed: 0, ready_to_install: false,
    note: 'Plano informativo. Não baixa, instala ou modifica ferramentas. A próxima etapa verificará versões, licença, espaço, fonte e aprovação explícita.',
  }
}

function planText(plan) {
  return [
    plan.description, '',
    ...plan.components.map(x => (x.state === 'found_on_path' ? 'Detectado (não verificado): ' :
      x.state === 'not_found_on_path' ? 'Não encontrado no PATH: ' : 'Ainda não verificado: ') + x.label),
    '',
    plan.note,
  ].join('\n')
}
module.exports = { PROFILES, planFor, planText }
