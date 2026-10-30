export const resourceKinds = {
  skill: { label: 'Skills de IA', accept: '.md,.zip', notice: 'Instruções não confiáveis. Importar não ativa. Scripts e anexos nunca são executados; somente o corpo de SKILL.md pode entrar no contexto.' },
  vsix: { label: 'Extensões VS Code', accept: '.vsix', notice: 'Somente inspeção e armazenamento. Não instala no VS Code nem fornece ferramentas aos agentes. Uma extensão instalada no VS Code pode executar código com seus privilégios.' },
  mcp: { label: 'Configurações MCP', accept: '.json', notice: 'Apenas o manifesto oficial Chrome DevTools MCP 1.0.1 pode ser ativado. A Central executa o pacote npm fixado, nunca comandos importados, e exige aprovação para cada ferramenta. Somente navegação HTTP(S) local é permitida.' },
}

export function preflight(kind, filename, size) {
  if (!resourceKinds[kind] || !Number.isSafeInteger(size) || size < 1 || size > 8 * 1024 * 1024) throw new Error('Arquivo vazio ou acima de 8 MiB.')
  if (/[\\/:\x00-\x1f]/.test(filename) || filename.includes('..')) throw new Error('Nome de arquivo inválido.')
  const valid = kind === 'skill' ? filename === 'SKILL.md' || filename.toLowerCase().endsWith('.zip') : filename.toLowerCase().endsWith(kind === 'vsix' ? '.vsix' : '.json')
  if (!valid) throw new Error('Formato incompatível com o tipo selecionado.')
  if (kind === 'mcp' && size > 128 * 1024) throw new Error('Configuração MCP: máximo de 128 KiB.')
  if (kind === 'skill' && size > 1024 * 1024) throw new Error('Skill: máximo de 1 MiB.')
}

export function createResourceClient(api, fetcher = fetch) {
  return {
    async preview(kind, file) {
      preflight(kind, file.name, file.size)
      const response = await fetcher('/api/resources/preview/' + kind, {
        method: 'POST', credentials: 'same-origin', body: file,
        headers: { 'X-Central-Request': '1', 'X-Resource-Filename': encodeURIComponent(file.name) },
      })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Falha ao inspecionar o pacote.')
      return data
    },
    confirm(preview, consent) {
      if (consent !== true || !preview?.preview_id || !preview?.confirmation) throw new Error('Revise e confirme a importação.')
      return api('/resources/previews/' + encodeURIComponent(preview.preview_id) + '/confirm', 'POST', { confirmation: preview.confirmation })
    },
    state(resource, state, consent) {
      if (consent !== true) throw new Error('Confirmação separada obrigatória.')
      if (state === 'active' && resource.kind !== 'skill' &&
          !(resource.kind === 'mcp' && resource.metadata?.server_id === 'chrome-devtools' &&
            resource.metadata?.version === '1.0.1')) {
        throw new Error('Somente o Chrome DevTools MCP oficial e fixado pode ser ativado.')
      }
      return api('/resources/' + encodeURIComponent(resource.id) + '/state', 'POST', { state, confirmation: resource.sha256 })
    },
  }
}

export function searchMarketplace(api, query, consent) {
  if (consent !== true) throw new Error('Autorize o envio do termo de busca ao Marketplace.')
  if (typeof query !== 'string' || query.trim().length < 2 || query.trim().length > 100) {
    throw new Error('Informe uma busca entre 2 e 100 caracteres.')
  }
  return api('/resources/marketplace/search', 'POST', { query: query.trim(), consent: true })
}
