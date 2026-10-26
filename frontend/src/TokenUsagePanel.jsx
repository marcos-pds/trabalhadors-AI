import { useEffect, useState } from 'react'

const number = value => Number(value || 0).toLocaleString('pt-BR')

export default function TokenUsagePanel({ api, onOpenRun }) {
  const [days, setDays] = useState(30)
  const [usage, setUsage] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setUsage(null)
    setError('')
    api(`/token-usage?days=${days}`)
      .then(result => { if (active) setUsage(result) })
      .catch(problem => { if (active) setError(problem.message) })
    return () => { active = false }
  }, [api, days])

  if (error) return <p role="alert" className="mx-auto max-w-4xl p-8 text-sm text-rose-200">{error}</p>
  if (!usage) return <div className="grid min-h-64 place-items-center text-sm text-muted">Carregando consumo…</div>

  const totals = usage.totals
  const maxDaily = Math.max(1, ...usage.daily.map(item => item.input_tokens + item.output_tokens))
  const cards = [
    ['Total de tokens', totals.total_tokens, 'Entradas + saídas'],
    ['Tokens informados', totals.actual_tokens, 'Métrica reportada pelo provedor'],
    ['Tokens estimados', totals.estimated_tokens, 'Estimativa quando não há telemetria'],
    ['Gerações', totals.generations, 'Chamadas concluídas ao modelo'],
  ]

  return <div className="mx-auto w-full max-w-[1440px] px-8 py-8 max-sm:px-4">
    <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div><p className="text-[10px] font-bold tracking-[.16em] text-lilac">CONSUMO DA IA</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Uso de tokens</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">Acompanhe entradas e respostas por período, provedor e execução. Valores reportados pelo provedor são separados das estimativas locais.</p>
      </div>
      <div className="flex gap-2" aria-label="Período do consumo">
        {[7, 30, 90].map(period => <button key={period} type="button" onClick={() => setDays(period)}
          aria-pressed={days === period}
          className={`rounded-xl border px-3 py-2 text-xs ${days === period ? 'border-lilac/40 bg-lilac/10 text-lilac' : 'border-white/10 text-muted hover:bg-white/[.05]'}`}>
          {period} dias
        </button>)}
      </div>
    </header>

    <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
      {cards.map(([label, value, caption]) => <article key={label} className="rounded-2xl border border-white/[.09] bg-panel p-5">
        <p className="text-xs text-muted">{label}</p>
        <p className="mt-3 text-2xl font-semibold tracking-tight">{number(value)}</p>
        <p className="mt-1 text-[10px] text-muted">{caption}</p>
      </article>)}
    </div>

    <div className="mb-5 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
      <section className="rounded-2xl border border-white/[.09] bg-panel p-5">
        <h2 className="text-sm font-semibold">Consumo diário</h2>
        {usage.daily.length ? <div className="mt-5 flex h-44 items-end gap-1 overflow-x-auto border-b border-white/10 pb-2">
          {usage.daily.map(item => {
            const total = item.input_tokens + item.output_tokens
            return <div key={item.date} title={`${item.date}: ${number(total)} tokens`}
              className="flex h-full min-w-2 flex-1 flex-col justify-end">
              <div className="w-full rounded-t bg-gradient-to-t from-violet-500 to-cyan-300"
                style={{ height: `${Math.max(3, total / maxDaily * 100)}%` }} />
            </div>
          })}
        </div> : <p className="py-12 text-center text-xs text-muted">Ainda não há medições neste período.</p>}
        <p className="mt-3 text-[10px] text-muted">Cada coluna representa um dia com uso registrado.</p>
      </section>
      <section className="rounded-2xl border border-white/[.09] bg-panel p-5">
        <h2 className="text-sm font-semibold">Por provedor e modelo</h2>
        {usage.providers.length ? <div className="mt-3 max-h-64 overflow-auto">
          {usage.providers.map(item => <div key={`${item.provider_name}-${item.model}`}
            className="border-t border-white/[.07] py-3 first:border-0">
            <div className="flex items-start justify-between gap-3">
              <span className="min-w-0"><strong className="block truncate text-xs">{item.provider_name}</strong>
                <small className="block truncate text-[10px] text-muted">{item.model}</small></span>
              <strong className="shrink-0 text-xs">{number(item.input_tokens + item.output_tokens)}</strong>
            </div>
            <p className="mt-1 text-[10px] text-muted">{number(item.input_tokens)} entrada · {number(item.output_tokens)} saída
              {' · '}{number(item.actual_tokens)} reportados · {number(item.estimated_tokens)} estimados</p>
          </div>)}
        </div> : <p className="py-12 text-center text-xs text-muted">Nenhum uso registrado.</p>}
      </section>
    </div>

    <section className="mb-5 overflow-hidden rounded-2xl border border-white/[.09] bg-panel">
      <div className="flex items-center justify-between px-5 py-4">
        <h2 className="text-sm font-semibold">Perguntas recentes</h2>
        <span className="text-[10px] text-muted">até 30 execuções · {days} dias</span>
      </div>
      {usage.recent_runs.length ? usage.recent_runs.map(run => <button key={run.run_id} type="button"
        onClick={() => onOpenRun(run.run_id)}
        className="flex w-full flex-wrap items-center justify-between gap-3 border-t border-white/[.07] px-5 py-3 text-left transition hover:bg-white/[.03]">
        <span className="min-w-0 flex-1"><strong className="block truncate text-xs">{run.prompt}</strong>
          <small className="mt-1 block text-[10px] text-muted">{new Date(run.created_at).toLocaleString('pt-BR')} · {run.status}</small></span>
        <span className="text-right text-xs font-semibold">{number(run.input_tokens + run.output_tokens)}
          <small className="mt-1 block text-[10px] font-normal text-muted">{number(run.actual_tokens)} reportados · {number(run.estimated_tokens)} estimados</small></span>
      </button>) : <p className="px-5 py-10 text-center text-xs text-muted">As próximas execuções aparecerão aqui.</p>}
    </section>

    <aside className="rounded-2xl border border-amber-300/15 bg-amber-300/[.04] p-4 text-xs leading-5 text-[#d8cba8]">
      {usage.balance_message} A Central registra o consumo das chamadas feitas por ela, mas não consegue inferir o saldo da sua conta, créditos, limites gratuitos ou tokens restantes. Verifique esses valores no painel do provedor.
    </aside>
  </div>
}
