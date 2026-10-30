import { useEffect, useRef, useState } from 'react'
import { matchingResources, resourceName, setChatResourceState } from './chatResources.mjs'

const button = 'rounded-lg border border-white/15 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-40'

export default function ChatResourcesPanel({ api, command, scopes, onClose, onResult, onManage }) {
  const [items, setItems] = useState([])
  const [scopeId, setScopeId] = useState(scopes[0]?.key || '')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const lock = useRef(false)
  const scope = scopes.find(item => item.key === scopeId)
  const refresh = async () => setItems(await api('/resources'))
  useEffect(() => {
    let mounted = true
    api('/resources').then(rows => { if (mounted) setItems(rows) })
      .catch(e => { if (mounted) setError(e.message) })
      .finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [api])
  useEffect(() => {
    const escape = event => { if (event.key === 'Escape' && !busy) onClose() }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [busy, onClose])
  async function change(item, enabled) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try { onResult(await setChatResourceState(api, item, enabled, scope)); await refresh() }
    catch (e) { setError(e.message); await refresh().catch(() => {}) }
    finally { lock.current = false; setBusy(false) }
  }
  const visible = matchingResources(items, command)
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={e => { if (e.target === e.currentTarget && !busy) onClose() }}>
    <section role="dialog" aria-modal="true" aria-label="Skills e plugins no chat" className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-2xl border border-white/15 bg-[#202024] p-5 shadow-2xl">
      <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">{command.kind === 'skill' ? 'Skills deste chat' : 'Plugins e integrações'}</h2><button autoFocus className={button} disabled={busy} onClick={onClose} aria-label="Fechar skills e plugins">✕</button></div>
      <p className="mt-2 text-xs leading-5 text-muted">Use /skill ativar nome ou /plugin ativar nome. Skills fornecem contexto aos trabalhadores; plugins MCP fornecem ferramentas quando suportados pela Central.</p>
      {command.kind === 'skill' && <label className="mt-3 text-xs">Usar em<select aria-label="Destino da skill no chat" disabled={busy} value={scopeId} onChange={e => setScopeId(e.target.value)} className="mt-1 w-full rounded-lg border border-white/15 bg-[#151519] p-2"><option value="">Selecione um destino</option>{scopes.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>}
      <div className="mt-4 min-h-0 space-y-2 overflow-y-auto">
        {loading ? <p role="status" className="text-xs">Carregando recursos…</p> : !visible.length ? <p className="text-sm text-muted">Nenhum recurso importado encontrado. Importe em Skills e integrações.</p> : visible.map(item => <div key={item.id} className="rounded-xl border border-white/10 p-3">
          <div className="flex items-center justify-between gap-2"><strong className="text-sm">{resourceName(item)} <small className="font-normal text-muted">{item.metadata?.version || item.id.slice(0,8)}</small></strong><span className="text-[10px] text-muted">{item.kind.toUpperCase()} · {item.state === 'active' ? 'Ativo no catálogo' : item.state === 'revoked' ? 'Revogado' : 'Inativo'}</span></div>
          <p className="mt-1 text-xs text-muted">{item.metadata?.description || (item.kind === 'vsix' ? 'Extensão do VS Code: instalação pela área de integrações.' : 'Integração local importada.')}</p>
          <div className="mt-3 flex gap-2">{item.kind === 'vsix' ? <button className={button} onClick={onManage}>Gerenciar instalação</button> : <><button className={button + ' text-emerald-200'} disabled={busy || item.state === 'revoked' || (item.kind === 'skill' && !scope)} onClick={() => change(item, true)}>{item.kind === 'skill' ? 'Ativar e usar neste destino' : 'Ativar plugin'}</button><button className={button} disabled={busy || (item.kind === 'skill' && !scope)} onClick={() => change(item, false)}>{item.kind === 'skill' ? 'Remover deste destino' : 'Desativar plugin'}</button></>}</div>
        </div>)}
      </div>
      {error && <p role="alert" className="mt-3 text-xs text-rose-200">{error}</p>}
      <button className={button + ' mt-4 self-start'} disabled={busy} onClick={onManage}>Gerenciar integrações</button>
    </section>
  </div>
}
