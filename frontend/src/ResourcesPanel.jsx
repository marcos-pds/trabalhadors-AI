import { useEffect, useMemo, useState } from 'react'
import { createResourceClient, resourceKinds, searchMarketplace } from './resourceClient.mjs'

const button = 'rounded-xl border border-white/20 px-3 py-2 text-sm disabled:opacity-40'
const input = 'rounded-lg border border-white/20 bg-panel p-2 text-sm'
const statusLabel = { imported: 'Importado', validated: 'Validado', enabled: 'Habilitado',
  associated: 'Associado', disabled: 'Desabilitado', not_associated: 'Sem associação',
  requires_run_context: 'Disponibilidade depende da execução', not_connected: 'MCP não conectado',
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

export function ImportReview({ preview, consent, busy, onConsent, onConfirm, onCancel }) {
  return <section className="space-y-3 rounded-2xl border border-violet-400/30 p-4" aria-label="Revisão de importação">
    <h2 className="font-semibold">Prévia — ainda não importado</h2>
    <p>{resourceKinds[preview.kind].notice}</p>
    {preview.source && <p className="break-all text-xs">Origem Git revisada: {preview.source.provider}/{preview.source.repository} · {preview.source.ref} · commit {preview.source.commit}</p>}
    <p className="break-all text-xs">SHA-256: {preview.sha256}</p>
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(preview.metadata, null, 2)}</pre>
    <label className="block"><input type="checkbox" checked={consent} disabled={busy} onChange={e => onConsent(e.target.checked)} /> Revisei o conteúdo e autorizo salvar como recurso privado e inativo.</label>
    <div className="flex gap-2"><button className={button} disabled={busy || !consent} onClick={onConfirm}>Confirmar importação inativa</button><button className={button} disabled={busy} onClick={onCancel}>Cancelar prévia</button></div>
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
  const [gitUrl, setGitUrl] = useState('')
  const [marketplaceQuery, setMarketplaceQuery] = useState('')
  const [marketplaceConsent, setMarketplaceConsent] = useState(false)
  const [marketplaceItems, setMarketplaceItems] = useState([])
  const [action, setAction] = useState(null)
  const [org, setOrg] = useState('')
  const [targetKind, setTargetKind] = useState('agent')
  const [target, setTarget] = useState('')
  const refresh = async () => setItems(await api('/resources'))
  useEffect(() => {
    let current = true
    Promise.all([api('/resources'), api('/organizations'), api('/git/connections')]).then(([rows, orgs, connections]) => {
      if (current) { setItems(rows); setOrganizations(orgs); setGitConnections(connections) }
    }).catch(e => { if (current) setError(e.message) })
    return () => { current = false }
  }, [api])

  async function perform(fn) {
    if (busy) return
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(false) }
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
    else if (action.type === 'share') setSelected(await api(path + '/sharing', 'POST', { organization_id: org || null, confirmation: selected.sha256 }))
    else if (action.type === 'bind') setSelected(await api(path + '/bindings', 'POST', { target_kind: targetKind, target_id: target, enabled: true }))
    else if (action.type === 'unbind') setSelected(await api(path + '/bindings', 'POST', { ...action.binding, enabled: false }))
    else setSelected(await client.state(selected, action.type, consent))
    setAction(null); setConsent(false); await refresh()
  }
  const targets = targetKind === 'agent' ? data.agents : targetKind === 'project' ? data.projects : data.runs
  const canManage = selected && (selected.organization_id ? organizations.some(o => o.id === selected.organization_id && o.role === 'admin') : selected.owner_id === me.id)
  const canShare = canManage && selected.owner_id === me.id
  const canBind = selected && (!selected.organization_id || organizations.some(o => o.id === selected.organization_id && ['admin', 'operator'].includes(o.role)))
  const actionText = action?.type === 'share' ? 'Compartilhar o pacote e seu conteúdo na organização selecionada (ou voltar a pessoal). Isso desativa a Skill e remove associações existentes.'
    : action?.type === 'delete' ? 'Remover este pacote e suas associações da Central. Isso não desinstala extensões do VS Code nem altera servidores externos.'
    : action?.type === 'bind' ? 'Associar esta Skill ao destino selecionado para minhas execuções. Se ativa, seu contexto poderá ser enviado aos provedores de IA habilitados.'
    : action?.type === 'active' ? 'Ativar esta Skill como contexto não confiável. Ela só será usada após uma associação explícita. Conteúdo selecionado pode ser enviado aos provedores de IA habilitados.'
    : 'Confirmar a alteração selecionada. Revogar remove as associações; desativar interrompe a injeção nas próximas chamadas ao modelo.'

  return <div className="mx-auto max-w-5xl space-y-5 p-6">
    <h1 className="text-2xl font-semibold">Skills, VS Code e MCP</h1>
    <p className="text-sm text-muted">Recursos distintos. Importação privada, revisão antes de salvar e nenhuma execução automática.</p>
    <label className="block">Tipo de recurso <select aria-label="Tipo de recurso" className={input} value={kind} disabled={busy || !!preview || !!action}
      onChange={e => { setKind(e.target.value); setSelected(null); setError('') }}>
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
      {kind === 'skill' && <div className="space-y-2 border-t border-white/15 pt-3">
        <h3>Importar Skill de repositório Git conectado</h3>
        <p className="text-xs text-muted">A Central lê somente o repositório associado à sua conexão Git. A leitura é limitada, não faz checkout e não executa arquivos. Será exibida uma prévia antes de salvar.</p>
        <label className="block">Conexão Git <select aria-label="Conexão Git para importar Skill" className={input} value={gitConnection} disabled={busy} onChange={e => setGitConnection(e.target.value)}><option value="">Selecione uma conexão</option>{gitConnections.map(c => <option key={c.id} value={c.id}>{c.service}: {c.repository}</option>)}</select></label>
        <label className="block">Link do repositório ou da pasta da Skill <input className={input + ' w-full'} value={gitUrl} disabled={busy} placeholder="https://github.com/organizacao/repositorio" onChange={e => setGitUrl(e.target.value)} /></label>
        <button className={button} disabled={busy || !gitConnection || !gitUrl || !!action} onClick={() => perform(async () => {
          setPreview(await api('/resources/preview-git', 'POST', { connection_id: gitConnection, repository_url: gitUrl })); setConsent(false); setSelected(null)
        })}>Buscar Skill e mostrar prévia</button>
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
      {kind === 'mcp' && <p className="text-xs text-muted">Formato declarativo da Central: name, version, transport, endpoint (HTTP), tools e permissions. Não inclua credenciais, headers, command, args ou env. Ferramentas declaradas não foram descobertas no servidor.</p>}
    </section>}
    {error && <p role="alert" className="text-rose-300">{error}</p>}
    {preview && <ImportReview preview={preview} consent={consent} busy={busy} onConsent={setConsent} onConfirm={() => perform(async () => {
        setSelected(await client.confirm(preview, consent)); setPreview(null); setConsent(false); await refresh()
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
        <button className={button} disabled={busy || !!action} onClick={() => ask('revoked')}>Revogar recurso</button>
        <button className={button} disabled={busy || !!action} onClick={() => ask('delete')}>Remover pacote da Central</button>
        {canShare && <><label>Compartilhamento <select className={input} value={org} disabled={busy || !!action} onChange={e => setOrg(e.target.value)}><option value="">Pessoal</option>{organizations.filter(o => o.role === 'admin' && !o.is_personal).map(o => <option value={o.id} key={o.id}>{o.name}</option>)}</select></label>
        <button className={button} disabled={busy || !!action} onClick={() => ask('share')}>Revisar compartilhamento</button></>}
      </div>}
      {selected.kind === 'skill' && <div className="space-y-2 border-t border-white/15 pt-3">
        <h3>Minhas associações explícitas</h3>
        <p className="text-xs text-muted">Ordem: execução, projeto, agente; até 4 Skills. Só SKILL.md entra no contexto, até 3.500 caracteres por Skill e 12.000 no total. Anexos não são lidos pelo modelo.</p>
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
