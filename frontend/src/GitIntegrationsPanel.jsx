import { useEffect, useState } from 'react'
import GitDraftPanel from './GitDraftPanel'

const input = 'mt-1 w-full rounded-xl border border-white/15 bg-black/20 px-3 py-2 text-xs'
const button = 'rounded-xl border border-white/15 px-3 py-2 text-xs disabled:opacity-40'

export default function GitIntegrationsPanel({ api }) {
  const [connections, setConnections] = useState([])
  const [service, setService] = useState('github')
  const [repository, setRepository] = useState('')
  const [token, setToken] = useState('')
  const [result, setResult] = useState(null)
  const [draftConnection, setDraftConnection] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    api('/git/connections').then(rows => { if (active) setConnections(rows) })
      .catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [api])

  async function save(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      await api('/git/connections', 'POST', { service, repository: repository.trim(), token })
      setToken('')
      setConnections(await api('/git/connections'))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function inspect(id, number, page = 1) {
    setBusy(true); setError(''); setResult(null)
    try {
      const params = new URLSearchParams({ page: String(page) })
      if (number) params.set('number', String(number))
      const suffix = '?' + params.toString()
      setResult({ ...(await api('/git/connections/' + encodeURIComponent(id) + '/reviews' + suffix)), id, number })
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function remove(id) {
    setBusy(true); setError('')
    try {
      await api('/git/connections/' + encodeURIComponent(id), 'DELETE')
      setConnections(rows => rows.filter(row => row.id !== id)); setResult(null)
      if (draftConnection?.id === id) setDraftConnection(null)
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <details className="rounded-2xl border border-white/10 bg-panel p-4">
    <summary className="cursor-pointer text-xs font-semibold">Revisões no GitHub e GitLab</summary>
    <p className="mt-3 text-xs text-muted">Consulte revisões e alterações. Use um token de leitura para consultas; criar rascunhos exige permissão específica no serviço. A conexão é pessoal e a chave fica criptografada.</p>
    <form onSubmit={save} className="mt-3 grid gap-3 sm:grid-cols-2">
      <label className="text-xs">Serviço<select className={input} value={service} onChange={e => setService(e.target.value)}>
        <option value="github">GitHub.com</option><option value="gitlab">GitLab.com</option>
      </select></label>
      <label className="text-xs">Repositório<input required className={input} placeholder="conta/repositório" value={repository} onChange={e => setRepository(e.target.value)} /></label>
      <label className="text-xs">Token de acesso<input required type="password" autoComplete="off" className={input} value={token} onChange={e => setToken(e.target.value)} /></label>
      <button className={button + ' self-end'} disabled={busy}>Salvar conexão</button>
    </form>
    {error && <p role="alert" className="mt-3 text-xs text-rose-300">{error}</p>}
    <div className="mt-3 space-y-2">{connections.map(row => <div key={row.id} className="flex flex-wrap items-center gap-2 text-xs">
      <span className="mr-auto">{row.service} · {row.repository}</span>
      <button type="button" className={button} disabled={busy} onClick={() => inspect(row.id)}>Ver revisões</button>
      <button type="button" className={button} disabled={busy} onClick={() => setDraftConnection(row)}>Preparar rascunho</button>
      <button type="button" className={button} disabled={busy} onClick={() => remove(row.id)}>Desconectar</button>
    </div>)}</div>
    {draftConnection && <GitDraftPanel key={draftConnection.id} api={api} connection={draftConnection} onClose={() => setDraftConnection(null)} />}
    {result && <div className="mt-4 space-y-3 text-xs">
      <p className="text-muted">{result.pagination_notice}</p>
      <div className="flex gap-2">
        <button type="button" className={button} disabled={busy || !result.previous_page} onClick={() => inspect(result.id, result.number, result.previous_page)}>Anterior</button>
        <button type="button" className={button} disabled={busy || !result.next_page} onClick={() => inspect(result.id, result.number, result.next_page)}>Próxima</button>
      </div>
      {!result.items.length && <p>{result.number ? 'Nenhum arquivo nesta página.' : 'Nenhuma revisão aberta nesta página.'}</p>}
      {result.items.map((item, index) => result.number ? <details key={index}>
        <summary className="cursor-pointer">{item.path}{item.truncated ? ' · Diff truncado' : ''}</summary>
        <pre className="mt-2 max-h-80 overflow-auto rounded-xl bg-black/25 p-3 whitespace-pre-wrap">{item.patch || 'Diff não fornecido pelo serviço.'}</pre>
      </details> : <button type="button" key={item.number} disabled={busy} className={button + ' block'} onClick={() => inspect(result.id, item.number)}>
        #{item.number} · {item.title}
      </button>)}
    </div>}
  </details>
}
