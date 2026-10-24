import { useEffect, useState } from 'react'
import GitIntegrationsPanel from './GitIntegrationsPanel'

const status = {
  run_created: 'Tarefa iniciada',
  run_resumed: 'Tarefa retomada',
  run_cancel_requested: 'Parada solicitada',
  workspace_policy_changed: 'Permissão de pasta alterada',
}

export default function OperationalOverview({ api }) {
  const [info, setInfo] = useState(null)
  const [audits, setAudits] = useState([])
  const [comparison, setComparison] = useState([])
  const [error, setError] = useState('')
  const [updated, setUpdated] = useState(null)

  useEffect(() => {
    let alive = true
    async function reload() {
      try {
        const [metrics, journal, providers] = await Promise.all([
          api('/operations/overview'), api('/operations/audit?limit=12'), api('/providers/comparison'),
        ])
        if (!alive) return
        setInfo(metrics)
        setAudits(journal)
        setComparison(providers)
        setUpdated(new Date())
        setError('')
      } catch (err) { if (alive) setError(err.message) }
    }
    reload()
    const interval = setInterval(reload, 15000)
    return () => { alive = false; clearInterval(interval) }
  }, [api])

  const recent = info?.last_24h || {}
  const tiles = [
    ['Execuções (24h)', recent.total],
    ['Falhas (24h)', recent.failed],
    ['Pausadas (24h)', recent.paused],
    ['Custo estimado (24h)', recent.estimated_cost_usd == null ?
      '—' : 'US$ ' + Number(recent.estimated_cost_usd).toFixed(4)],
    ['Duração média terminal', recent.mean_terminal_duration_ms == null ?
      '—' : (recent.mean_terminal_duration_ms / 1000).toFixed(1) + ' s'],
    ['Tentativas de etapas', recent.step_attempts],
  ]

  return <section className="mt-5 space-y-4" aria-label="Métricas operacionais locais">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-sm font-semibold">Operação e auditoria · dados reais</h2>
      <p className="text-[11px] text-muted">Janela de 24 horas · atualização a cada 15 s
        {updated ? ' · ' + updated.toLocaleTimeString('pt-BR') : ''}
      </p>
    </div>
    {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
    {!info ? <p className="py-5 text-xs text-muted">Carregando métricas…</p> : <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {tiles.map(([label, value]) => <article key={label}
          className="rounded-2xl border border-white/10 bg-panel p-4">
          <p className="text-[11px] text-muted">{label}</p>
          <strong className="mt-2 block text-xl font-semibold">{value ?? '—'}</strong>
        </article>)}
      </div>
      <section className="rounded-2xl border border-white/10 bg-panel p-4">
        <h3 className="text-xs font-semibold">Cotas operacionais da conta</h3>
        <div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
          <p>Execuções nas últimas 24h: <strong>{info.quotas?.usage?.runs_last_24h ?? '—'} / {info.quotas?.limits?.runs_per_24h ?? '—'}</strong></p>
          <p>Em fila ou execução: <strong>{info.quotas?.usage?.active_runs ?? '—'} / {info.quotas?.limits?.active_runs ?? '—'}</strong></p>
        </div>
        <p className="mt-2 text-[10px] text-muted">Limites definidos no servidor. Não equivalem ao saldo ou à cobrança real dos provedores.</p>
      </section>
      <section className="rounded-2xl border border-white/10 bg-panel p-4">
        <h3 className="text-xs font-semibold">Executor de comandos</h3>
        <p className="mt-2 text-xs">{info.command_executor?.backend === 'docker'
          ? 'Docker isolado (opt-in)' : 'Windows / Linux local (host)'}</p>
        {info.command_executor?.backend === 'docker' && <p className="mt-1 text-[11px] text-muted">
          Docker {info.command_executor.docker_installed ? 'disponível no PATH' : 'não encontrado no PATH'}
          {' · '}Rede: desativada · CPU: {info.command_executor.cpu_limit} · Memória: {info.command_executor.memory_limit_mb} MB
          {' · '}Máx. processos: {info.command_executor.pids_limit}
          {' · '}Prévia por proxy local; instalações exigem aprovação. Rede de instalação: {info.command_executor.dependency_network || 'none'}.
        </p>}
        <p className="mt-2 text-[11px] text-muted">{info.command_executor?.note || 'Executor não identificado.'}</p>
      </section>
      <section className="rounded-2xl border border-white/10 bg-panel p-4">
        <h3 className="text-xs font-semibold">Fila persistente local</h3>
        <p className="mt-1 text-[11px] text-muted">Backend: SQLite · execuções com lease renovável. Para processos separados, inicie o worker dedicado.</p>
        <div className="mt-3 flex flex-wrap gap-3 text-xs">
          {Object.entries(info.job_queue?.states || {}).map(([state,total]) =>
            <span key={state} className="rounded-lg border border-white/10 px-3 py-2">{state}: {total}</span>)}
          {!Object.keys(info.job_queue?.states || {}).length && <span className="text-muted">Nenhuma tarefa enfileirada.</span>}
        </div>
        <p className="mt-2 text-xs">Workers ativos: <strong>{info.job_queue?.workers?.active_workers ?? '—'}</strong>
          {' · '}Jobs em workers: <strong>{info.job_queue?.workers?.active_jobs_reported ?? '—'}</strong>
          {' · '}Workers sem sinal recente: <strong>{info.job_queue?.workers?.stale_workers ?? '—'}</strong>
        </p>
        <p className="mt-2 text-[10px] text-muted">Maior número de reservas por job: {info.job_queue?.max_attempts ?? 0}.
          {' '}Heartbeats válidos por {info.job_queue?.workers?.liveness_window_seconds ?? 20} segundos.
          {' '}Comandos usam leases e no máximo {info.job_queue?.recovery_limit ?? 5} tentativas antes de exigir retomada manual.
          {' '}Não é uma fila distribuída entre servidores.</p>
      </section>
      {info.alerts?.length > 0 && <div className="rounded-2xl border border-amber-300/20 bg-amber-300/[.04] p-4">
        <h3 className="mb-3 text-xs font-semibold text-amber-200">Atenção operacional</h3>
        {info.alerts.map((a, i) => <p key={a.code + '-' + (a.provider_id || i)}
          className="mb-2 text-[11px] leading-5 text-copy">
          {a.message}{a.provider_name ? ' · ' + a.provider_name : ''}
          {a.count ? ' · ' + a.count + ' ocorrência(s)' : ''}
        </p>)}
      </div>}
      <div className="overflow-x-auto rounded-2xl border border-white/10 bg-panel">
        <h3 className="px-4 py-4 text-xs font-semibold">Tentativas reais por provedor · 24h</h3>
        <table className="w-full min-w-[620px] text-left text-xs">
          <thead className="border-y border-white/10 text-[10px] uppercase tracking-wide text-muted">
            <tr>{['Provedor', 'Tentativas', 'Sucesso', 'Latência média', 'Entrada / saída (US$/1M)'].map(x =>
              <th key={x} className="px-4 py-3">{x}</th>)}</tr>
          </thead>
          <tbody>{info.providers?.map(p => <tr key={p.provider_id} className="border-t border-white/[.06]">
            <td className="px-4 py-3">{p.name}<small className="block text-muted">{p.model}</small></td>
            <td className="px-4 py-3">{p.attempts}</td>
            <td className="px-4 py-3">{p.success_rate == null ? '—' : p.success_rate + '%'}</td>
            <td className="px-4 py-3">{p.avg_latency_ms == null ? '—' : p.avg_latency_ms + ' ms'}</td>
          </tr>)}</tbody>
        </table>
        {!info.providers?.length && <p className="p-4 text-xs text-muted">Nenhuma conexão cadastrada.</p>}
      </div>
      <div className="overflow-hidden rounded-2xl border border-white/10 bg-panel">
        <h3 className="px-4 py-4 text-xs font-semibold">Auditoria das suas ações recentes</h3>
        {audits.length ? audits.map(row => <div key={row.id}
          className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[.07] px-4 py-3 text-xs">
          <span>{status[row.action] || row.action}<small className="ml-2 text-muted">{row.outcome}</small></span>
          <time className="text-[10px] text-muted" dateTime={row.created_at}>
            {new Date(row.created_at).toLocaleString('pt-BR')}
          </time>
        </div>) : <p className="px-4 pb-4 text-xs text-muted">Nenhum evento auditável registrado.</p>}
      </div>
      <GitIntegrationsPanel api={api} />
      <p className="text-[11px] text-muted">{info.cost_notice}
        {' '}Esse painel monitora o processo local; ainda não existe uma fila de jobs distribuída.
      </p>
    </>}
  </section>
}
