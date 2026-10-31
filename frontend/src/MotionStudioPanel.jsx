import { useEffect, useState } from 'react'
import { loadMotionCapabilities } from './motionStudio.mjs'

export default function MotionStudioPanel({ api }) {
  const [rows, setRows] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [updated, setUpdated] = useState(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    setRows(null)
    setUpdated(null)
    loadMotionCapabilities(api).then(result => {
      if (!active) return
      setRows(result)
      setUpdated(new Date())
    }).catch(err => {
      if (active) setError(err instanceof Error ? err.message : 'Não foi possível consultar o inventário Motion.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [api, reload])

  return <section data-testid="motion-studio-panel" aria-label="AI Motion Studio" aria-busy={loading}
    className="rounded-2xl border border-white/10 bg-panel p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 className="text-sm font-semibold">AI Motion Studio</h3>
        <p className="mt-1 text-xs text-muted">Diagnóstico das ferramentas de vídeo e áudio</p>
      </div>
      <button type="button" disabled={loading} onClick={() => setReload(value => value + 1)}
        className="rounded-xl border border-white/15 px-3 py-2 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-lilac disabled:opacity-40">
        {loading ? 'Consultando…' : 'Recarregar diagnóstico'}
      </button>
    </div>
    <p className="mt-3 text-xs leading-5 text-muted">
      A detecção confirma presença no servidor. A verificação de funcionamento e os serviços de renderização estão pendentes.
      Esta consulta não gera mídia nem instala ferramentas.
    </p>
    <div role="status" aria-live="polite" className="mt-3 text-[11px] text-muted">
      {loading ? 'Consultando capacidades locais…' : updated
        ? <>Última consulta: <time dateTime={updated.toISOString()}>{updated.toLocaleString('pt-BR')}</time></>
        : 'Inventário indisponível. Nenhuma capacidade foi confirmada nesta consulta.'}
    </div>
    {error && <div role="alert" className="mt-3 rounded-xl border border-rose-300/20 p-3 text-xs text-rose-200">
      <p className="break-words">{error}</p>
      <p className="mt-2">Confira sua sessão e a conexão com a Central local, depois recarregue o diagnóstico. A consulta está disponível apenas no modo local.</p>
    </div>}
    {rows && <div className="mt-4 grid min-w-0 gap-3 md:grid-cols-2">
      {rows.map(row => <article key={row.id} aria-label={row.name}
        className="min-w-0 rounded-xl border border-white/10 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-semibold">{row.name}</h4>
          <span className={`rounded-lg border px-2 py-1 text-[10px] ${row.installed
            ? 'border-sky-300/20 text-sky-200' : 'border-white/10 text-muted'}`}>{row.installation}</span>
        </div>
        <p className="mt-1 text-[11px] text-muted">{row.purpose}</p>
        <dl className="mt-3 space-y-2 text-[11px]">
          {[
            ['Contrato', row.contract], ['Funcionamento', row.verification],
            ['Renderização', row.rendering], ['Execução', row.execution], ['Versão', row.version],
          ].map(([label, value]) => <div key={label} className="flex flex-wrap justify-between gap-x-3 gap-y-1">
            <dt className="text-muted">{label}</dt><dd className="min-w-0 break-words">{value}</dd>
          </div>)}
        </dl>
        <p className="mt-2 text-[10px] text-muted">{row.versionSource}</p>
        {row.endpoint && <p className="mt-2 text-[11px] text-muted">{row.endpoint}</p>}
        <details className="mt-3 border-t border-white/10 pt-2">
          <summary className="cursor-pointer text-[11px]">O que conferir</summary>
          <p className="mt-2 text-[11px] leading-5 text-muted">{row.diagnostic}</p>
        </details>
      </article>)}
    </div>}
  </section>
}
