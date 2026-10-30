import { useEffect, useState } from 'react'
import GitDraftPanel from './GitDraftPanel'

const input = 'mt-1 w-full rounded-xl border border-white/15 bg-black/20 px-3 py-2 text-xs'
const button = 'rounded-xl border border-white/15 px-3 py-2 text-xs disabled:opacity-40'

export default function GitIntegrationsPanel({ api, initiallyOpen = false }) {
  const [connections, setConnections] = useState([])
  const [service, setService] = useState('github')
  const [repository, setRepository] = useState('')
  const [allRepositories, setAllRepositories] = useState(false)
  const [repositoryLists, setRepositoryLists] = useState({})
  const [selectedRepositories, setSelectedRepositories] = useState({})
  const [token, setToken] = useState('')
  const [result, setResult] = useState(null)
  const [draftConnection, setDraftConnection] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(initiallyOpen)
  const tokenUrl = service === 'github'
    ? 'https://github.com/settings/personal-access-tokens/new'
    : 'https://gitlab.com/-/user_settings/personal_access_tokens'

  useEffect(() => {
    let active = true
    api('/git/connections').then(rows => { if (active) setConnections(rows) })
      .catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [api])

  async function save(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      await api('/git/connections', 'POST', { service, repository: service === 'github' && allRepositories ? '*' : repository.trim(), token })
      setToken(''); setRepository(''); setAllRepositories(false)
      setConnections(await api('/git/connections'))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function loadRepositories(id) {
    setBusy(true); setError('')
    try {
      const data = await api('/git/connections/' + encodeURIComponent(id) + '/repositories')
      setRepositoryLists(old => ({ ...old, [id]: data }))
      if (data.repositories?.length) setSelectedRepositories(old => ({ ...old, [id]: old[id] || data.repositories[0].repository }))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function inspect(id, number, page = 1, repository = null) {
    setBusy(true); setError(''); setResult(null)
    try {
      const params = new URLSearchParams({ page: String(page) })
      if (number) params.set('number', String(number))
      if (repository) params.set('repository', repository)
      const suffix = '?' + params.toString()
      setResult({ ...(await api('/git/connections/' + encodeURIComponent(id) + '/reviews' + suffix)), id, number, repository })
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

  return <details open={expanded} onToggle={event => setExpanded(event.currentTarget.open)} className="rounded-2xl border border-white/10 bg-panel p-4">
    <summary className="cursor-pointer text-xs font-semibold">Conectar e gerenciar GitHub / GitLab</summary>
    <p className="mt-3 text-xs text-muted">Consulte revisões e alterações. Use um token de leitura para consultas; criar rascunhos exige permissão específica no serviço. A conexão é pessoal e a chave fica criptografada.</p>
    <form onSubmit={save} className="mt-3 grid gap-3 sm:grid-cols-2">
      <label className="text-xs">Serviço<select className={input} value={service} onChange={e => setService(e.target.value)}>
        <option value="github">GitHub.com</option><option value="gitlab">GitLab.com</option>
      </select></label>
      {service === 'github' ? <label className="flex items-start gap-2 rounded-xl border border-white/10 p-3 text-xs sm:col-span-2"><input type="checkbox" checked={allRepositories} onChange={e => setAllRepositories(e.target.checked)} className="mt-0.5 accent-violet-400" /><span>Conectar todos os repositórios acessíveis pelo token<small className="mt-1 block text-[10px] leading-4 text-muted">Ao criar o token fino no GitHub, selecione os repositórios que quer autorizar. A Central respeita esse limite; a opção não amplia as permissões do token.</small></span></label> : <label className="text-xs">Repositório<input required className={input} placeholder="proprietário/repositório" value={repository} onChange={e => setRepository(e.target.value)} /><small className="mt-1 block text-[10px] text-muted">Exemplo: grupo/projeto. Não use o e-mail da conta.</small></label>}
      <label className="text-xs"><span className="mb-1 flex items-center justify-between gap-2">Token de acesso<a className={button + ' inline-flex items-center gap-1 text-lilac hover:border-lilac/40'} href={tokenUrl} target="_blank" rel="noopener noreferrer">Pegar token <span aria-hidden="true">↗</span></a></span><input required type="password" autoComplete="off" className={input} value={token} onChange={e => setToken(e.target.value)} /></label>
      <button className={button + ' self-end'} disabled={busy || (service === 'github' ? (!allRepositories && !repository.trim()) : !repository.trim())}>Salvar conexão</button>
    </form>
    {error && <p role="alert" className="mt-3 text-xs text-rose-300">{error}</p>}
    <div className="mt-3 space-y-3">{connections.map(row => <div key={row.id} className="space-y-2 rounded-xl border border-white/10 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2"><span className="mr-auto">{row.service} · {row.repository === '*' ? 'Todos os repositórios permitidos pelo token' : row.repository}</span>
        {row.repository === '*' ? <button type="button" className={button} disabled={busy} onClick={() => loadRepositories(row.id)}>Listar repositórios</button> : <><button type="button" className={button} disabled={busy} onClick={() => inspect(row.id)}>Ver revisões</button><button type="button" className={button} disabled={busy} onClick={() => setDraftConnection(row)}>Preparar rascunho</button></>}
        <button type="button" className={button} disabled={busy} onClick={() => remove(row.id)}>Desconectar</button>
      </div>
      {row.repository === '*' && repositoryLists[row.id] && <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-56 flex-1">Repositório<select className={input} value={selectedRepositories[row.id] || ''} disabled={busy || !repositoryLists[row.id].repositories.length} onChange={e => setSelectedRepositories(old => ({ ...old, [row.id]: e.target.value }))}><option value="">Selecione um repositório</option>{repositoryLists[row.id].repositories.map(item => <option key={item.repository} value={item.repository}>{item.repository}</option>)}</select></label>
        <button type="button" className={button} disabled={busy || !selectedRepositories[row.id]} onClick={() => inspect(row.id, null, 1, selectedRepositories[row.id])}>Ver revisões</button>
        <button type="button" className={button} disabled={busy || !selectedRepositories[row.id]} onClick={() => setDraftConnection({ ...row, repository: selectedRepositories[row.id] })}>Preparar rascunho</button>
        {repositoryLists[row.id].truncated && <p className="w-full text-[10px] text-muted">A lista atingiu o limite de 1.000 repositórios; os demais não aparecem aqui.</p>}
        {!repositoryLists[row.id].repositories.length && <p className="w-full text-[10px] text-muted">Nenhum repositório foi listado. Confira se o token autoriza os repositórios desejados.</p>}
      </div>}
    </div>)}</div>
    {draftConnection && <GitDraftPanel key={draftConnection.id} api={api} connection={draftConnection} onClose={() => setDraftConnection(null)} />}
    {result && <div className="mt-4 space-y-3 text-xs">
      <p className="text-muted">{result.pagination_notice}</p>
      <div className="flex gap-2">
        <button type="button" className={button} disabled={busy || !result.previous_page} onClick={() => inspect(result.id, result.number, result.previous_page, result.repository)}>Anterior</button>
        <button type="button" className={button} disabled={busy || !result.next_page} onClick={() => inspect(result.id, result.number, result.next_page, result.repository)}>Próxima</button>
      </div>
      {!result.items.length && <p>{result.number ? 'Nenhum arquivo nesta página.' : 'Nenhuma revisão aberta nesta página.'}</p>}
      {result.items.map((item, index) => result.number ? <details key={index}>
        <summary className="cursor-pointer">{item.path}{item.truncated ? ' · Diff truncado' : ''}</summary>
        <pre className="mt-2 max-h-80 overflow-auto rounded-xl bg-black/25 p-3 whitespace-pre-wrap">{item.patch || 'Diff não fornecido pelo serviço.'}</pre>
      </details> : <button type="button" key={item.number} disabled={busy} className={button + ' block'} onClick={() => inspect(result.id, item.number, 1, result.repository)}>
        #{item.number} · {item.title}
      </button>)}
    </div>}
  </details>
}
