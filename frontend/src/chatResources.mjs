import { createResourceClient } from './resourceClient.mjs'

const normalize = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim()
export function parseResourceCommand(text) {
  const match = String(text).trim().match(/^\/(skills?|plugins?)\b(?:\s+(.*))?$/i)
  if (!match) return null
  const rest = (match[2] || '').trim()
  const action = rest.match(/^(ativar|desativar|listar)\b\s*(.*)$/i)
  return { kind: /^skill/i.test(match[1]) ? 'skill' : 'plugin',
    action: action ? normalize(action[1]) : 'listar', query: (action ? action[2] : rest).trim() }
}

export function resourceName(item) {
  return item.metadata?.name || item.metadata?.server_id || item.id
}

export function matchingResources(items, command) {
  const candidates = items.filter(item => command.kind === 'skill' ? item.kind === 'skill' : item.kind !== 'skill')
  if (!command.query) return candidates
  const query = normalize(command.query.replace(/^['"]|['"]$/g, ''))
  const exact = candidates.filter(item => [item.id, resourceName(item), item.metadata?.server_id].some(name => normalize(name) === query))
  return exact.length ? exact : candidates.filter(item => normalize(resourceName(item)).includes(query))
}

export async function setChatResourceState(api, item, enabled, scope) {
  // Re-read metadata and digest immediately before the same guarded endpoints
  // used by ResourcesPanel. Slash commands never execute an imported command.
  const fresh = await api('/resources/' + encodeURIComponent(item.id))
  if (fresh.kind === 'vsix') throw new Error('Extensões VS Code precisam de instalação. Use “Gerenciar integrações”.')
  if (fresh.state === 'revoked') throw new Error('Este recurso foi revogado. Reimporte-o em Skills e integrações.')
  if (fresh.kind === 'skill') {
    if (!scope?.target_id || !['project', 'agent', 'run'].includes(scope.target_kind)) {
      throw new Error('Escolha o projeto, trabalhador ou execução que usará esta skill.')
    }
    await api('/resources/' + encodeURIComponent(fresh.id) + '/bindings', 'POST', {
      target_kind: scope.target_kind, target_id: scope.target_id, enabled,
    })
    // Disabling a Skill in this chat removes only this binding, preserving
    // other projects that may still use the same resource.
    if (enabled && fresh.state !== 'active') await createResourceClient(api).state(fresh, 'active', true)
    return `${resourceName(fresh)}: ${enabled ? 'ativa e associada a' : 'removida de'} ${scope.label}.`
  }
  await createResourceClient(api).state(fresh, enabled ? 'active' : 'inactive', true)
  return `${resourceName(fresh)}: ${enabled ? 'plugin ativado' : 'plugin desativado'}.`
}
