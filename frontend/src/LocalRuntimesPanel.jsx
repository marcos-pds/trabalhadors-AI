import { useState } from 'react'

export default function LocalRuntimesPanel({ api, onConnected }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [model, setModel] = useState('')
  const [createWorker, setCreateWorker] = useState(true)
  const [connected, setConnected] = useState('')
  async function inspect() {
    setBusy(true); setError('')
    try {
      const found = await api('/runtimes/codex/probe', 'POST')
      setResult(found)
      setModel(current => found.models.some(item => item.id === current) ? current : found.models[0]?.id || '')
    }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  async function connect() {
    setBusy(true); setError(''); setConnected('')
    try {
      const saved = await api('/runtimes/codex/connect', 'POST', { model, create_worker: createWorker })
      await onConnected?.()
      setConnected(saved.agent_id ? 'Codex conectado. Selecione o trabalhador no chat para usá-lo.' : 'Provedor Codex conectado. Associe-o a um trabalhador em Configurar.')
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return <section aria-label="Codex local" className="mb-5 rounded-2xl border border-white/10 bg-panel p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-sm font-semibold">Codex neste computador</h2>
        <p className="mt-1 text-xs text-muted">Confira o CLI e os modelos disponíveis na conta conectada.</p></div>
      <button type="button" disabled={busy} onClick={inspect} className="rounded-xl border border-lilac/30 px-4 py-2 text-xs disabled:opacity-50">
        {busy ? 'Verificando…' : 'Verificar Codex local'}
      </button>
    </div>
    {result && <div role="status" className="mt-3 text-xs">
      {result.status === 'ok'
        ? <><p>{result.authenticated ? 'Conta conectada' : 'Faça login pelo Codex CLI'} · {result.version || 'Versão não informada'}</p>
          <p className="mt-2 text-muted">{result.models.map(model => model.name).join(' · ') || 'Nenhum modelo retornado'}</p></>
        : <p>Verificação indisponível: {result.status}</p>}
    </div>}
    {result?.status === 'ok' && result.auth_type === 'chatgpt' && result.models.length > 0 && <div className="mt-4 space-y-3 border-t border-white/10 pt-3">
      <label className="block text-xs">Modelo Codex
        <select aria-label="Modelo Codex local" value={model} onChange={e => setModel(e.target.value)} className="mt-2 w-full rounded-xl border border-white/15 bg-panel px-3 py-2">
          {result.models.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={createWorker} onChange={e => setCreateWorker(e.target.checked)}/>Criar trabalhador Codex e revisor</label>
      <button type="button" onClick={connect} disabled={busy || !model} className="rounded-xl border border-lilac/30 px-4 py-2 text-xs disabled:opacity-50">Conectar Codex à Central</button>
    </div>}
    <p className="mt-3 text-[11px] text-muted">O CLI gerencia seu login ChatGPT e suas cotas. O catálogo não comprova acesso a cada modelo; isso é verificado na tarefa. Arquivos e comandos passam pelas permissões da Central.</p>
    {connected && <p role="status" className="mt-2 text-xs text-emerald-200">{connected}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-rose-200">{error}</p>}
  </section>
}
