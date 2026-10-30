import { useEffect, useMemo, useState } from 'react'
import { createResourceClient, resourceKinds, searchMarketplace } from './resourceClient.mjs'
import officialDevtoolsManifest from '../../examples/chrome-devtools/server.json'

const button = 'rounded-xl border border-white/20 px-3 py-2 text-sm disabled:opacity-40'
const input = 'rounded-lg border border-white/20 bg-panel p-2 text-sm'
const statusLabel = { imported: 'Importado', validated: 'Validado', enabled: 'Habilitado',
  associated: 'Associado', disabled: 'Desabilitado', not_associated: 'Sem associação',
  requires_run_context: 'Disponibilidade depende da execução', not_connected: 'MCP não conectado',
  ready_for_approval: 'Disponível com aprovação por chamada',
  not_installed: 'VSIX não instalado' }

export function ResourceStatuses({ item }) {
  return <div className="flex flex-wrap gap-2 text-xs" aria-label="Estados do recurso">
    <span>{statusLabel[item.import_status] || 'Importado'}</span>
    <span>{statusLabel[item.validation_status] || 'Validado'}</span>
    <span>{item.enabled ? statusLabel.enabled : statusLabel.disabled}</span>
    {item.kind === 'skill' && <span>{item.associated ? statusLabel.associated : statusLabel.not_associated}</span>}
    <span>{statusLabel[item.availability] || item.availability}</span>
  </div>
}

export function VscodeInstallControls({ selected, targets, targetId, busy, result, onTarget, onInstall, onUninstall }) {
  const extensionId = `${selected.metadata.publisher}.${selected.metadata.name}`
  const target = targets.find(item => item.target_id === targetId)
  const installed = target?.installed_extensions?.find(item => item.id.toLowerCase() === extensionId.toLowerCase())
  return <section className="space-y-3 border-t border-white/15 pt-3" aria-label="Instalação VS Code">
    <h3>Instalação explícita no VS Code</h3>
    <p className="text-xs text-muted">A instalação executa o CLI local do VS Code e pode disponibilizar código da extensão com os privilégios da sua conta. A Central não instala dependências nem executa comandos declarados no pacote. Remover da Central não desinstala do VS Code.</p>
    <label className="block">Destino do VS Code <select aria-label="Destino do VS Code" className={input} value={targetId} disabled={busy} onChange={e => onTarget(e.target.value)}><option value="">Selecione um VS Code validado</option>{targets.map(item => <option key={item.target_id} value={item.target_id}>{item.name} {item.version}</option>)}</select></label>
    {target && <p className="text-xs">{installed ? `Instalada neste destino: ${installed.id}@${installed.version}` : 'Ainda não instalada neste destino.'}</p>}
    {!targets.length && <p className="text-xs">Nenhum executável estável do VS Code foi localizado nos caminhos padrão.</p>}
    {result && <p role="status" className="text-xs">{result.installed ? `Instalação verificada: ${result.extension_id}@${result.extension_version}` : `Desinstalação verificada: ${result.extension_id}`}</p>}
    <div className="flex gap-2"><button className={button} disabled={busy || !target || !!installed} onClick={onInstall}>Revisar instalação</button>{installed && <button className={button} disabled={busy} onClick={onUninstall}>Revisar desinstalação</button>}</div>
  </section>
}

export function GitSkillImportControls({ repositoryUrl, onRepositoryUrl, busy, action, onPreview,
  authRequired, connections = [], onUseConnection, token, onToken, onConnect }) {
  const [showOtherToken, setShowOtherToken] = useState(false)
  const matching = authRequired ? connections.filter(item => item.service === authRequired.provider &&
    (item.repository === '*' || item.repository.toLowerCase() === authRequired.repository.toLowerCase())) : []
  return <section className="space-y-2 border-t border-white/15 pt-3">
    <h3>Importar Skill de repositório GitHub</h3>
    <p className="text-xs text-muted">Cole o link. Repositórios públicos são lidos sem token; se o acesso exigir autenticação, você poderá conectar o GitHub nesta tela. A Central lê somente os arquivos da Skill, sem checkout ou execução, e mostra uma prévia antes de salvar.</p>
    <label className="block">Link do repositório ou da pasta da Skill <input aria-label="Link do repositório GitHub" className={input + ' w-full'} value={repositoryUrl} disabled={busy} placeholder="https://github.com/organizacao/repositorio" onChange={e => onRepositoryUrl(e.target.value)} /></label>
    <button type="button" className={button} disabled={busy || !repositoryUrl.trim() || !!action} onClick={onPreview}>Buscar Skill e mostrar prévia</button>
    {authRequired && <div role="group" aria-label="Conectar GitHub para continuar" className="space-y-2 rounded-xl border border-amber-300/25 p-3">
      <p className="text-xs text-amber-100">{matching.length ? 'A leitura pública falhou e a Central tentou a conexão Git salva. O repositório pode ser privado; se ele for público, não precisa de token — tente novamente mais tarde ou verifique o acesso do servidor à API do GitHub.' : 'A leitura pública falhou. O repositório pode ser privado ou o GitHub pode estar temporariamente indisponível. Repositórios públicos não precisam de token.'}</p>
      {matching.map(connection => <button type="button" key={connection.id} className={button} disabled={busy} onClick={() => onUseConnection(connection.id)}>{connection.repository === '*' ? 'Tentar novamente com os repositórios autorizados' : `Tentar conexão salva: ${connection.repository}`}</button>)}
      {matching.length > 0 && !showOtherToken && <button type="button" className={button} disabled={busy} onClick={() => setShowOtherToken(true)}>Conectar outra credencial</button>}
      {(matching.length === 0 || showOtherToken) && <>
        <label className="block text-xs">Token GitHub fine-grained, com leitura de conteúdo para este repositório
          <input aria-label="Token GitHub de leitura" type="password" autoComplete="new-password" spellCheck={false} className={input + ' w-full'} value={token} disabled={busy} onChange={e => onToken(e.target.value)} />
        </label>
        <button type="button" className={button} disabled={busy || !token.trim()} onClick={onConnect}>Conectar e continuar importação</button>
      </>}
    </div>}
  </section>
}

export function OfficialMcpImportButton({ busy, onPreview }) {
  return <button type="button" className={button} disabled={busy} onClick={onPreview}>
    Revisar manifesto oficial Chrome DevTools MCP 1.0.1
  </button>
}

function ImportScopeNotice({ source }) {
  return source?.import_mode === 'instructions_only' ? <p role="note" className="text-amber-200 text-sm">Somente as instruções de SKILL.md serão importadas. {source.omitted_file_count} arquivos auxiliares foram omitidos porque o pacote excede os limites. Comandos, CLI e referências externas da Skill não estarão disponíveis por esta importação.</p> : null
}

export function ImportReview({ preview, consent, busy, onConsent, onConfirm, onCancel }) {
  const isBatch = Array.isArray(preview.skills)
  const count = isBatch ? preview.skills.length : 1
  return <section className="space-y-3 rounded-2xl border border-violet-400/30 p-4" aria-label="Revisão de importação">
    <h2 className="font-semibold">{isBatch ? 'Prévia - ' + count + ' Skills ainda não importadas' : 'Prévia - ainda não importado'}</h2>
    <p>{resourceKinds[preview.kind].notice}</p>
    <ImportScopeNotice source={preview.source} />
    {isBatch && preview.skills.some(skill => skill.source?.import_mode === 'instructions_only') && <p role="note">Este lote contém importações somente de instruções. Confira as limitações em cada Skill antes de confirmar.</p>}
    {isBatch ? <div className="max-h-[36rem] space-y-2 overflow-auto">
      {preview.skills.map((skill, index) => <details key={skill.sha256 + '-' + index} className="rounded-lg border border-white/10 p-3" open={count <= 5}>
        <summary className="cursor-pointer">{skill.metadata.name} - {skill.metadata.version}</summary>
        {skill.source && <p className="break-all text-xs">Origem: {skill.source.provider}/{skill.source.repository} - {skill.source.path}</p>}
        <ImportScopeNotice source={skill.source} />
        <p className="break-all text-xs">SHA-256: {skill.sha256}</p>
        <pre className="mt-2 whitespace-pre-wrap text-xs">{JSON.stringify(skill.metadata, null, 2)}</pre>
      </details>)}
    </div> : <>
      {preview.source && <div className="space-y-1 text-xs"><p className="break-all">Origem Git revisada: {preview.source.provider}/{preview.source.repository} - {preview.source.ref} - commit {preview.source.commit}</p>{preview.source.skill_paths?.length > 1 && <div><p>{preview.source.identical_copies ? 'Encontramos cópias idênticas de SKILL.md em pastas de ferramentas.' : 'Encontramos versões de SKILL.md em pastas de ferramentas.'} A Central importa uma única Skill canônica; VSIX e configurações MCP continuam recursos separados.</p><ul className="list-disc pl-5">{preview.source.skill_paths.map(path => <li className="break-all" key={path}>{path}</li>)}</ul>{preview.source.skill_paths_truncated && <p>Outros caminhos não foram listados.</p>}</div>}{preview.source.scan_complete === false && <p role="note" className="text-amber-200">A árvore do repositório foi truncada pelo GitHub; esta lista pode não incluir todas as cópias.</p>}</div>}
      <p className="break-all text-xs">SHA-256: {preview.sha256}</p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(preview.metadata, null, 2)}</pre>
    </>}
    <label className="block"><input type="checkbox" checked={consent} disabled={busy} onChange={e => onConsent(e.target.checked)} /> {isBatch ? 'Revisei as ' + count + ' Skills listadas e autorizo importar todas como privadas e inativas.' : 'Revisei o conteúdo e autorizo salvar como recurso privado e inativo.'}</label>
    <div className="flex gap-2"><button className={button} disabled={busy || !consent} onClick={onConfirm}>{isBatch ? 'Confirmar importação das ' + count + ' Skills inativas' : 'Confirmar importação inativa'}</button><button className={button} disabled={busy} onClick={onCancel}>Cancelar prévia</button></div>
  </section>
}

export default function ResourcesPanel({ api, data, me }) {
  const client = useMemo(() => createResourceClient(api), [api])
  const [kind, setKind] = useState('skill')
  const [items, setItems] = useState([])
  const [organizations, setOrganizations] = useState([])
  const [preview, setPreview] = useState(null)
  const [selected, setSelected] = useState(null)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [relative, setRelative] = useState('')
  const [gitConnections, setGitConnections] = useState([])
  const [gitConnection, setGitConnection] = useState('')
  const [gitAuthRequired, setGitAuthRequired] = useState(null)
  const [gitToken, setGitToken] = useState('')
  const [gitUrl, setGitUrl] = useState('https://github.com/ChromeDevTools/chrome-devtools-mcp')
  const [marketplaceQuery, setMarketplaceQuery] = useState('')
  const [marketplaceConsent, setMarketplaceConsent] = useState(false)
  const [marketplaceItems, setMarketplaceItems] = useState([])
  const [action, setAction] = useState(null)
  const [org, setOrg] = useState('')
  const [targetKind, setTargetKind] = useState('agent')
  const [target, setTarget] = useState('')
  const [vscodeTargets, setVscodeTargets] = useState([])
  const [vscodeTarget, setVscodeTarget] = useState('')
  const [vscodeResult, setVscodeResult] = useState(null)
  const refresh = async () => setItems(await api('/resources'))
  useEffect(() => {
    let current = true
    Promise.all([api('/resources'), api('/organizations'), api('/git/connections')]).then(([rows, orgs, connections]) => {
      if (current) { setItems(rows); setOrganizations(orgs); setGitConnections(connections) }
    }).catch(e => { if (current) setError(e.message) })
    return () => { current = false }
  }, [api])
  useEffect(() => {
    let current = true
    if (selected?.kind === 'vsix') api('/resources/vscode/targets').then(rows => {
      if (current) setVscodeTargets(rows)
    }).catch(e => { if (current) setError(e.message) })
    else { setVscodeTargets([]); setVscodeTarget(''); setVscodeResult(null) }
    return () => { current = false }
  }, [api, selected?.id, selected?.kind])

  async function perform(fn) {
    if (busy) return
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  async function previewGit(connectionId = null) {
    const payload = { repository_url: gitUrl.trim(), ...(connectionId ? { connection_id: connectionId } : {}) }
    const result = await api('/resources/preview-git', 'POST', payload)
    if (result.requires_connection) {
      setGitAuthRequired(result)
      const match = gitConnections.find(item => item.service === result.provider &&
        item.repository !== '*' && item.repository.toLowerCase() === result.repository.toLowerCase()) ||
        gitConnections.find(item => item.service === result.provider && item.repository === '*')
      setGitConnection(match?.id || '')
      if (match && !connectionId) return previewGit(match.id)
      return
    }
    setGitAuthRequired(null); setGitToken(''); setGitConnection(connectionId || '')
    setPreview(result); setConsent(false); setSelected(null)
  }
  async function previewOfficialMcp() {
    const file = new File(
      [JSON.stringify(officialDevtoolsManifest)],
      'server.json',
      { type: 'application/json' },
    )
    setPreview(await client.preview('mcp', file))
    setConsent(false)
    setSelected(null)
  }
  async function connectGitAndContinue() {
    if (!gitAuthRequired || !gitToken.trim()) return
    const saved = await api('/git/connections', 'POST', {
      service: gitAuthRequired.provider, repository: gitAuthRequired.repository, token: gitToken,
    })
    setGitToken('')
    setGitConnections(rows => [...rows.filter(item => item.id !== saved.id), saved])
    await previewGit(saved.id)
  }
  async function cancelPreview() {
    try { if (preview) await api('/resources/previews/' + encodeURIComponent(preview.preview_id), 'DELETE') }
    finally { setPreview(null); setConsent(false) }
  }
  function ask(type, payload = {}) { setAction({ type, ...payload }); setConsent(false) }
  async function executeAction() {
    if (!consent || !selected || !action) return
    const path = '/resources/' + encodeURIComponent(selected.id)
    if (action.type === 'delete') { await api(path, 'DELETE'); setSelected(null) }
    else if (action.type === 'vscode_install' || action.type === 'vscode_uninstall') {
      const verb = action.type === 'vscode_install' ? 'install' : 'uninstall'
      setVscodeResult(await api(path + '/vscode/' + verb, 'POST', {
        target_id: vscodeTarget, confirmation: selected.sha256, consent: true,
      }))
      setVscodeTargets(await api('/resources/vscode/targets'))
    }
    else if (action.type === 'share') setSelected(await api(path + '/sharing', 'POST', { organization_id: org || null, confirmation: selected.sha256 }))
    else if (action.type === 'bind') setSelected(await api(path + '/bindings', 'POST', { target_kind: targetKind, target_id: target, enabled: true }))
    else if (action.type === 'unbind') setSelected(await api(path + '/bindings', 'POST', { ...action.binding, enabled: false }))
    else setSelected(await client.state(selected, action.type, consent))
    setAction(null); setConsent(false); await refresh()
  }
  const targets = targetKind === 'agent' ? data.agents : targetKind === 'project' ? data.projects : data.runs
  const canManage = selected && (selected.organization_id ? organizations.some(o => o.id === selected.organization_id && o.role === 'admin') : selected.owner_id === me.id)
  const canShare = canManage && selected.owner_id === me.id
  const canInstallVsix = selected?.kind === 'vsix' && selected.owner_id === me.id && !selected.organization_id
  const canBind = selected && (!selected.organization_id || organizations.some(o => o.id === selected.organization_id && ['admin', 'operator'].includes(o.role)))
  const actionText = action?.type === 'share' ? 'Compartilhar o pacote e seu conteúdo na organização selecionada (ou voltar a pessoal). Isso desativa a Skill e remove associações existentes.'
    : action?.type === 'delete' ? 'Remover este pacote e suas associações da Central. Isso não desinstala extensões do VS Code nem altera servidores externos.'
    : action?.type === 'bind' ? 'Associar esta Skill ao destino selecionado para minhas execuções. Se ativa, seu contexto poderá ser enviado aos provedores de IA habilitados.'
    : action?.type === 'active' && selected?.kind === 'mcp' ? 'Autorizar a Central a iniciar o pacote oficial chrome-devtools-mcp@1.0.1. Comandos importados nunca serão executados; cada ferramenta do navegador exigirá nova aprovação e só poderá acessar páginas locais.'
    : action?.type === 'active' ? 'Ativar esta Skill como contexto não confiável. Ela só será usada após uma associação explícita. Conteúdo selecionado pode ser enviado aos provedores de IA habilitados.'
    : action?.type === 'vscode_install' ? 'Confirmo instalar este VSIX, com os metadados e o hash revisados, neste VS Code. Extensões podem executar código com os privilégios da sua conta. A Central usará somente o caminho do pacote e flags fixas do CLI; não instalará dependências declaradas.'
    : action?.type === 'vscode_uninstall' ? 'Confirmo desinstalar esta extensão do VS Code selecionado. Isso é separado de remover o pacote da Central.'
    : 'Confirmar a alteração selecionada. Revogar remove as associações; desativar interrompe a injeção nas próximas chamadas ao modelo.'

  return <div className="mx-auto max-w-5xl space-y-5 p-6">
    <h1 className="text-2xl font-semibold">Skills, VS Code e MCP</h1>
    <p className="text-sm text-muted">Skills do Chrome DevTools: importe pelo repositório oficial, revise a prévia e confirme o lote. O pacote MCP é separado e requer ativação explícita.</p>
    <label className="block">Tipo de recurso <select aria-label="Tipo de recurso" className={input} value={kind} disabled={busy || !!preview || !!action}
      onChange={e => { setKind(e.target.value); setSelected(null); setError(''); setGitAuthRequired(null); setGitToken(''); setGitConnection('') }}>
      {Object.entries(resourceKinds).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}
    </select></label>
    <p role="note" className="rounded-xl border border-amber-300/30 p-3 text-sm">{resourceKinds[kind].notice}</p>
    {!preview && <section className="space-y-3 rounded-2xl border border-white/15 p-4">
      <label className="block text-sm">Selecionar arquivo para inspeção
        <input type="file" accept={resourceKinds[kind].accept} disabled={busy || !!action} className="mt-2 block" onChange={e => {
          const file = e.target.files?.[0]; e.target.value = ''
          if (file) perform(async () => { setPreview(await client.preview(kind, file)); setConsent(false); setSelected(null) })
        }} />
      </label>
      {kind === 'skill' && <div className="space-y-2">
        <p className="text-xs text-muted">SKILL.md em UTF-8 ou ZIP de até 1 MiB. Também é possível ler uma pasta dentro do workspace já autorizado com acesso completo em Computador.</p>
        <label>Caminho relativo da pasta <input className={input} value={relative} disabled={busy} placeholder="minhas-skills/revisao" onChange={e => setRelative(e.target.value)} /></label>
        <button className={button} disabled={busy || !relative || !!action} onClick={() => perform(async () => {
          setPreview(await api('/resources/preview-folder', 'POST', { relative_path: relative })); setConsent(false); setSelected(null)
        })}>Inspecionar pasta autorizada</button>
      </div>}
      {kind === 'skill' && <div className="space-y-2">
        <p className="text-xs text-muted">O repositório oficial Chrome DevTools MCP contém as Skills chrome-devtools, chrome-devtools-cli, a11y-debugging, debug-optimize-lcp, memory-leak-debugging e troubleshooting. A busca mostra a prévia do lote; a importação fica inativa até você associar e ativar cada Skill.</p>
        <GitSkillImportControls repositoryUrl={gitUrl}
        onRepositoryUrl={value => { setGitUrl(value); setGitAuthRequired(null); setGitToken(''); setGitConnection('') }}
        busy={busy} action={action} onPreview={() => perform(() => previewGit())}
        authRequired={gitAuthRequired} connections={gitConnections}
        onUseConnection={id => perform(() => previewGit(id))}
        token={gitToken} onToken={setGitToken}
        onConnect={() => perform(connectGitAndContinue)} />
      </div>}
      {kind === 'vsix' && <div className="space-y-2 border-t border-white/15 pt-3">
        <h3>Listar extensões do Visual Studio Marketplace</h3>
        <p className="text-xs text-muted">A busca envia somente o texto abaixo à Microsoft para consultar metadados públicos. Não baixa VSIX, não instala extensões nem compartilha arquivos locais.</p>
        <label className="block">Buscar extensão <input className={input} value={marketplaceQuery} disabled={busy} maxLength={100} onChange={e => setMarketplaceQuery(e.target.value)} /></label>
        <label className="block text-xs"><input type="checkbox" checked={marketplaceConsent} disabled={busy} onChange={e => setMarketplaceConsent(e.target.checked)} /> Autorizo enviar este termo de busca ao Visual Studio Marketplace.</label>
        <button className={button} disabled={busy || !marketplaceConsent || marketplaceQuery.trim().length < 2} onClick={() => perform(async () => {
          const result = await searchMarketplace(api, marketplaceQuery, marketplaceConsent); setMarketplaceItems(result.items); setMarketplaceConsent(false)
        })}>Buscar metadados públicos</button>
        {marketplaceItems.map(extension => <div key={extension.id} className="rounded-lg border border-white/10 p-2 text-sm"><strong>{extension.display_name}</strong> <span className="text-xs">{extension.id} · {extension.version}</span><p className="text-xs text-muted">{extension.description}</p><span className="text-xs">Metadados somente; instalação indisponível.</span></div>)}
      </div>}
      {kind === 'mcp' && <div className="space-y-2">
        <p className="text-xs text-muted">Use o manifesto oficial fixado em 1.0.1 ou selecione outro arquivo para inspeção. A Central não executa comandos do manifesto: inicia somente o pacote npm fixado. Nenhuma ferramenta opera sem sua aprovação.</p>
        <OfficialMcpImportButton busy={busy || !!action}
          onPreview={() => perform(previewOfficialMcp)} />
      </div>}
    </section>}
    {error && <p role="alert" className="text-rose-300">{error}</p>}
    {preview && <ImportReview preview={preview} consent={consent} busy={busy} onConsent={setConsent} onConfirm={() => perform(async () => {
        const imported = await client.confirm(preview, consent)
        setSelected(imported.resources?.[0] || imported); setPreview(null); setConsent(false); await refresh()
      })} onCancel={() => perform(cancelPreview)} />}
    <section className="space-y-2" aria-label="Recursos importados">
      <h2 className="font-semibold">Recursos importados</h2>
      {items.filter(item => item.kind === kind).map(item => <div key={item.id} className="space-y-2 rounded-xl border border-white/10 p-3">
        <button disabled={busy || !!preview || !!action} className={button} onClick={() => perform(async () => {
          setSelected(await api('/resources/' + encodeURIComponent(item.id))); setOrg(item.organization_id || ''); setTarget('')
        })}>{item.metadata.name} — {item.metadata.version} — {item.state} — {item.organization_id ? 'Organização' : 'Pessoal'}</button>
        <ResourceStatuses item={item} />
      </div>)}
      {!items.some(item => item.kind === kind) && <p className="text-sm text-muted">Nenhum recurso deste tipo.</p>}
    </section>
    {selected && !preview && <section className="space-y-3 rounded-2xl border border-white/15 p-4" aria-label="Detalhes do recurso">
      <h2 className="font-semibold">{selected.metadata.name} — {selected.state}</h2>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(selected.metadata, null, 2)}{selected.instructions ? '\n\n' + selected.instructions : ''}</pre>
      <p className="break-all text-xs">SHA-256: {selected.sha256}</p>
      <a className={button + ' inline-block'} href={'/api/resources/' + encodeURIComponent(selected.id) + '/export'} download>Exportar pacote</a>
      {canManage && <div className="flex flex-wrap gap-2">
        {selected.kind === 'skill' && <button className={button} disabled={busy || !!action} onClick={() => ask(selected.state === 'active' ? 'inactive' : 'active')}>{selected.state === 'active' ? 'Desativar Skill' : 'Revisar ativação da Skill'}</button>}
        {selected.kind === 'mcp' && selected.metadata.server_id === 'chrome-devtools' &&
          <button className={button} disabled={busy || !!action}
            onClick={() => ask(selected.state === 'active' ? 'inactive' : 'active')}>
            {selected.state === 'active' ? 'Desativar Chrome DevTools MCP' : 'Revisar ativação do Chrome DevTools MCP'}
          </button>}
        <button className={button} disabled={busy || !!action} onClick={() => ask('revoked')}>Revogar recurso</button>
        <button className={button} disabled={busy || !!action} onClick={() => ask('delete')}>Remover pacote da Central</button>
        {canShare && <><label>Compartilhamento <select className={input} value={org} disabled={busy || !!action} onChange={e => setOrg(e.target.value)}><option value="">Pessoal</option>{organizations.filter(o => o.role === 'admin' && !o.is_personal).map(o => <option value={o.id} key={o.id}>{o.name}</option>)}</select></label>
        <button className={button} disabled={busy || !!action} onClick={() => ask('share')}>Revisar compartilhamento</button></>}
      </div>}
      {canInstallVsix && <VscodeInstallControls selected={selected} targets={vscodeTargets} targetId={vscodeTarget}
        busy={busy || !!action} result={vscodeResult} onTarget={setVscodeTarget}
        onInstall={() => ask('vscode_install')} onUninstall={() => ask('vscode_uninstall')} />}
      {selected.kind === 'skill' && <div className="space-y-2 border-t border-white/15 pt-3">
        <h3>Minhas associações explícitas</h3>
        <p className="text-xs text-muted">Ordem: execução, projeto, agente; até 4 Skills. Trechos relevantes do SKILL.md entram no contexto, até 3.500 caracteres por Skill e 10.000 no total. Anexos e referências não importadas não são lidos pelo modelo.</p>
        <select aria-label="Tipo de associação" className={input} disabled={busy || !!action} value={targetKind} onChange={e => { setTargetKind(e.target.value); setTarget('') }}><option value="agent">Agente</option><option value="project">Projeto</option><option value="run">Execução</option></select>
        <select aria-label="Destino da Skill" className={input} disabled={busy || !!action} value={target} onChange={e => setTarget(e.target.value)}><option value="">Selecione o destino</option>{targets.map(t => <option key={t.id} value={t.id}>{t.name || t.prompt?.slice(0, 65) || t.id}</option>)}</select>
        <button className={button} disabled={busy || !!action || !target || !canBind} onClick={() => ask('bind')}>Revisar associação</button>
        {(selected.bindings || []).map(b => <div key={b.target_kind + b.target_id} className="text-xs">{b.target_kind}: {b.target_id} <button className={button} disabled={busy || !!action} onClick={() => ask('unbind', { binding: b })}>Desassociar</button></div>)}
      </div>}
      {action && <div role="group" aria-label="Confirmação separada" className="space-y-3 border-t border-white/15 pt-3"><p>{actionText}</p>
        <label className="block"><input type="checkbox" checked={consent} disabled={busy} onChange={e => setConsent(e.target.checked)} /> Confirmo esta ação separadamente.</label>
        <button className={button} disabled={busy || !consent} onClick={() => perform(executeAction)}>Confirmar ação</button>
        <button className={button} disabled={busy} onClick={() => { setAction(null); setConsent(false) }}>Cancelar ação</button>
      </div>}
    </section>}
  </div>
}
