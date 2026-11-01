import { useEffect, useState } from 'react'

const labels = { claude: 'Claude Code', gemini: 'Gemini CLI', opencode: 'OpenCode', acp: 'ACP · Gemini' }
const compatible = { claude: ['anthropic'], gemini: ['gemini'], acp: ['gemini'], opencode: ['groq', 'gemini', 'anthropic', 'openai', 'openrouter'] }

export default function ExternalRuntimesPanel({ api, onConnected }) {
  const [inventory, setInventory] = useState(null)
  const [sources, setSources] = useState([])
  const [runtime, setRuntime] = useState('gemini')
  const [source, setSource] = useState('')
  const [key, setKey] = useState('')
  const [model, setModel] = useState('')
  const [models, setModels] = useState([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelError, setModelError] = useState('')
  const [vendor, setVendor] = useState('gemini')
  const [refresh, setRefresh] = useState(0)
  const [manual, setManual] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => {
    let cancelled = false
    setModels([]); setModelError(''); setLoadingModels(false)
    if (!inventory || (!source && !key.trim())) return
    setLoadingModels(true)
    const timer = setTimeout(async () => {
      try {
        const result = await api(`/runtimes/external/${runtime}/models`, 'POST', {
          source_provider_id: source || null, api_key: source ? '' : key.trim(), provider_kind: vendor,
        })
        if (!cancelled) {
          setModels(result.models)
          setModel(previous => result.models.some(item => item.id === previous) ? previous : '')
          if (!result.models.length) setModelError('Nenhum modelo de texto foi encontrado para esta credencial.')
        }
      } catch (e) { if (!cancelled) { setModelError(e.message); setModel('') } }
      finally { if (!cancelled) setLoadingModels(false) }
    }, source ? 0 : 1000)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [api, inventory, runtime, source, key, vendor, refresh])
  async function inspect() {
    setBusy(true); setError('')
    try {
      const [found, providers] = await Promise.all([api('/runtimes/execution'), api('/providers')])
      setInventory(found); setSources(providers.filter(p => p.enabled && p.has_key))
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  function chooseSource(id) {
    setSource(id); setKey('')
    const selected = sources.find(p => p.id === id)
    if (selected) setModel(runtime === 'opencode'
      ? `${selected.kind === 'gemini' ? 'google' : selected.kind}/${selected.model}` : selected.model)
  }
  async function connect() {
    setBusy(true); setError(''); setMessage('')
    try {
      await api(`/runtimes/external/${runtime}/connect`, 'POST', {
        model, source_provider_id: source || null, api_key: source ? '' : key, create_worker: true,
      })
      setKey(''); await onConnected?.()
      setMessage(`${labels[runtime]} conectado com implementador e revisor. Credencial e acesso ao modelo serão verificados na execução; nenhuma inferência foi feita ao conectar.`)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <section aria-label="Runtimes externos" className="mb-5 rounded-2xl border border-white/10 bg-panel p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-sm font-semibold">Claude Code, Gemini CLI, OpenCode e ACP</h2>
        <p className="mt-1 text-xs text-muted">Planejadores locais; as ações passam pelas permissões da Central.</p></div>
      <button disabled={busy} onClick={inspect} className="rounded-xl border border-white/20 px-3 py-2 text-xs disabled:opacity-40">Verificar runtimes externos</button>
    </div>
    {inventory && <div className="mt-4 space-y-3 text-xs">
      <div className="grid gap-2 sm:grid-cols-2">{Object.entries(labels).map(([id, name]) => <p key={id} className="rounded-xl border border-white/10 p-3">
        <strong>{name}</strong><span className="ml-2 text-muted">{inventory[id]?.status === 'configured' ? `Perfil configurado · ${inventory[id].version}` : inventory[id]?.status || 'Não verificado'}</span>
      </p>)}</div>
      <label className="block">Runtime<select aria-label="Runtime externo" value={runtime} onChange={e => { setRuntime(e.target.value); setSource(''); setModel(''); setKey(''); setManual(false) }} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2">
        {Object.entries(labels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <label className="block">Credencial<select aria-label="Credencial do runtime" value={source} onChange={e => chooseSource(e.target.value)} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2">
        <option value="">Informar uma chave API</option>{sources.filter(p => compatible[runtime].includes(p.kind)).map(p => <option key={p.id} value={p.id}>{p.name} · {p.model}</option>)}</select></label>
      {!source && <label className="block">Chave API<input aria-label="Chave API do runtime" type="password" autoComplete="off" value={key} onChange={e => { setKey(e.target.value); setModel('') }} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2"/></label>}
      {runtime === 'opencode' && !source && <label className="block">Provedor da chave<select aria-label="Provedor da chave do runtime" value={vendor} onChange={e => { setVendor(e.target.value); setModel('') }} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2">
        {['gemini','groq','anthropic','openai','openrouter'].map(kind => <option key={kind} value={kind}>{kind}</option>)}
      </select></label>}
      <label className="block">Modelo{manual ? <input aria-label="Modelo do runtime externo" value={model} onChange={e => setModel(e.target.value)} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2"/> :
        <select aria-label="Modelo do runtime externo" value={model} disabled={loadingModels} onChange={e => setModel(e.target.value)} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2">
          <option value="">{loadingModels ? 'Buscando modelos...' : 'Selecione um modelo'}</option>
          {models.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
        </select>}</label>
      <div className="flex flex-wrap gap-3"><button disabled={loadingModels || (!source && !key.trim())} onClick={() => setRefresh(value => value + 1)} className="underline disabled:opacity-40">Atualizar modelos</button>
        <button onClick={() => { setManual(value => !value); setModel('') }} className="underline">{manual ? 'Usar lista de modelos' : 'Informar modelo manualmente'}</button></div>
      {loadingModels && <p role="status">Buscando modelos no provedor...</p>}
      {modelError && <p role="alert" className="text-rose-200">{modelError}</p>}
      <p className="text-muted">A consulta lista modelos sem gerar respostas. Disponibilidade, cotas e acesso efetivo serao confirmados na execucao.</p>
      <button disabled={busy || loadingModels || !model || (!source && !key) || inventory[runtime]?.status !== 'configured'} onClick={connect} className="rounded-xl border border-lilac/30 px-3 py-2 disabled:opacity-40">Conectar runtime · sem inferência</button>
    </div>}
    <p className="mt-3 text-[11px] text-muted">Requer ferramentas opcionais instaladas pelo operador. Esta integração usa chaves API e suas cotas; não reutiliza login ou assinatura dos CLIs. ACP usa o backend Gemini configurado. As ferramentas nativas ficam negadas; o processo não é um sandbox de sistema operacional.</p>
    {message && <p role="status" className="mt-3 text-xs text-emerald-200">{message}</p>}
    {error && <p role="alert" className="mt-3 text-xs text-rose-200">{error}</p>}
  </section>
}
