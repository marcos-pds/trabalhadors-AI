import { useState } from 'react'

const labels = { claude: 'Claude Code', gemini: 'Gemini CLI', opencode: 'OpenCode', acp: 'ACP · Gemini' }
const compatible = { claude: ['anthropic'], gemini: ['gemini'], acp: ['gemini'], opencode: ['groq', 'gemini', 'anthropic', 'openai', 'openrouter'] }

export default function ExternalRuntimesPanel({ api, onConnected }) {
  const [inventory, setInventory] = useState(null)
  const [sources, setSources] = useState([])
  const [runtime, setRuntime] = useState('gemini')
  const [source, setSource] = useState('')
  const [key, setKey] = useState('')
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
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
      <label className="block">Runtime<select aria-label="Runtime externo" value={runtime} onChange={e => { setRuntime(e.target.value); setSource(''); setModel(''); setKey('') }} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2">
        {Object.entries(labels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <label className="block">Credencial<select aria-label="Credencial do runtime" value={source} onChange={e => chooseSource(e.target.value)} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2">
        <option value="">Informar uma chave API</option>{sources.filter(p => compatible[runtime].includes(p.kind)).map(p => <option key={p.id} value={p.id}>{p.name} · {p.model}</option>)}</select></label>
      {!source && <label className="block">Chave API<input aria-label="Chave API do runtime" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2"/></label>}
      <label className="block">Modelo<input aria-label="Modelo do runtime externo" value={model} onChange={e => setModel(e.target.value)} placeholder={runtime === 'opencode' ? 'groq/ID_DO_MODELO' : 'ID do modelo na sua conta'} className="mt-1 w-full rounded-xl border border-white/15 bg-panel p-2"/></label>
      <button disabled={busy || !model || (!source && !key) || inventory[runtime]?.status !== 'configured'} onClick={connect} className="rounded-xl border border-lilac/30 px-3 py-2 disabled:opacity-40">Conectar runtime · sem inferência</button>
    </div>}
    <p className="mt-3 text-[11px] text-muted">Requer ferramentas opcionais instaladas pelo operador. Esta integração usa chaves API e suas cotas; não reutiliza login ou assinatura dos CLIs. ACP usa o backend Gemini configurado. As ferramentas nativas ficam negadas; o processo não é um sandbox de sistema operacional.</p>
    {message && <p role="status" className="mt-3 text-xs text-emerald-200">{message}</p>}
    {error && <p role="alert" className="mt-3 text-xs text-rose-200">{error}</p>}
  </section>
}
