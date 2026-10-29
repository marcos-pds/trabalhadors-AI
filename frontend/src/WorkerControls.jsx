import { useEffect, useRef, useState } from 'react'

const button = 'rounded-lg border border-white/15 px-2.5 py-1.5 text-xs text-copy hover:bg-white/10 disabled:opacity-40'
const terminal = new Set(['completed', 'failed', 'cancelled', 'skipped'])

export default function WorkerControls({ api, runId, steps = [], onChanged, notify }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const currentRun = useRef(runId)
  currentRun.current = runId
  useEffect(() => {
    let mounted = true
    setData(null); setError(''); setBusy(false)
    if (!runId || !api) return
    const poll = async () => {
      try {
        const result = await api('/runs/' + encodeURIComponent(runId) + '/worker-controls')
        if (mounted) { setData(result); setError('') }
      } catch (err) { if (mounted) setError(err.message) }
    }
    poll()
    const timer = setInterval(poll, 3000)
    return () => { mounted = false; clearInterval(timer) }
  }, [api, runId])

  async function request(step, operation) {
    if (!runId || !api || busy) return
    const requestedRun = runId
    setBusy(true); setError('')
    try {
      const root = '/runs/' + encodeURIComponent(requestedRun)
      await api(root + '/steps/' + encodeURIComponent(step.id) + '/control', 'POST', { operation })
      const updated = await api(root + '/worker-controls')
      if (currentRun.current !== requestedRun) return
      setData(updated)
      notify?.(operation === 'resume' ? 'Retomada solicitada.' : 'Controle solicitado; aguardando limite seguro entre ações.')
      onChanged?.(updated)
    } catch (err) { if (currentRun.current === requestedRun) setError(err.message) }
    finally { if (currentRun.current === requestedRun) setBusy(false) }
  }

  const workers = data?.steps || steps.filter(step => !step.kind || step.kind === 'agent')
  return <section aria-label="Controles dos trabalhadores" className="mt-3 rounded-xl border border-white/15 p-3 text-xs">
    <h3 className="font-semibold text-copy">Trabalhadores</h3>
    <p className="mt-1 text-muted">Pausa e cancelamento aguardam a ação atual terminar. Retomar exige sua ação.</p>
    {!workers.length && <p className="mt-2 text-muted">Nenhum trabalhador disponível.</p>}
    {workers.map(step => {
      const control = step.control
      const paused = control?.state === 'paused' || step.status === 'paused_operator'
      const stopped = terminal.has(step.status) || control?.state === 'cancelled'
      const disabled = !runId || !api || !data || busy || stopped
      return <article key={step.id} className="mt-3 border-t border-white/10 pt-3">
        <p className="font-medium text-copy">{step.name || step.id} · {step.status}</p>
        {control && <p className="mt-1 text-muted">Controle: {control.operation}{control.pending ? ' · aguardando limite seguro' : ' · observado'}</p>}
        {!!step.deps?.length && <p className="mt-1 break-words text-muted">Dependências: {Array.isArray(step.deps) ? step.deps.join(', ') : step.deps}</p>}
        {!!step.blockers?.length && <p className="mt-1 text-amber-200">Aguardando: {step.blockers.map(item => `${item.name} (${item.status})`).join(', ')}</p>}
        {step.error && <p className="mt-1 break-words text-red-200">{step.error}</p>}
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" className={button} disabled={disabled || paused} onClick={() => request(step, 'pause')}>Pausar</button>
          <button type="button" className={button} disabled={disabled || !paused} onClick={() => request(step, 'resume')}>Retomar</button>
          <button type="button" className={button} disabled={disabled} onClick={() => request(step, 'cancel')}>Cancelar trabalhador</button>
        </div>
      </article>
    })}
    {error && <p role="alert" className="mt-3 text-red-200">{error}</p>}
  </section>
}
