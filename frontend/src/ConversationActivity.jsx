import { useEffect, useState } from 'react'
import { activityLabel, compactActivityEvents, mergeActivityEvents } from './conversationActivity.mjs'

export default function ConversationActivity({ api, runId, active }) {
  const [activity, setActivity] = useState(null)
  const [events, setEvents] = useState([])
  const [error, setError] = useState('')
  useEffect(() => {
    let mounted = true, inFlight = false, timer
    const poll = async () => {
      if (inFlight) return
      inFlight = true
      try {
        const result = await api('/runs/' + encodeURIComponent(runId) + '/activity')
        if (!mounted) return
        setActivity(result); setError('')
        setEvents(previous => mergeActivityEvents(previous, result.events || []))
        if (['completed','failed','cancelled','paused_limit'].includes(result.status)) clearInterval(timer)
      } catch (e) { if (mounted) setError(e.message) }
      finally { inFlight = false }
    }
    timer = setInterval(poll, 3000)
    poll()
    return () => { mounted = false; clearInterval(timer) }
  }, [api, runId, active])
  const log = compactActivityEvents(events)
  const last = log.at(-1)
  const status = {running:'em andamento',queued:'na fila',awaiting_approval:'aguardando aprovação',completed:'concluída',failed:'com erro',cancelled:'parada',paused_limit:'pausada'}[activity?.status] || 'carregando'
  const warning = error || ['failed','paused_limit'].includes(activity?.status)
  return <details className="mx-auto mb-4 max-w-3xl rounded-lg border border-white/[.07] bg-white/[.015] text-[11px] text-muted">
    <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 hover:bg-white/[.025] focus-visible:outline focus-visible:outline-violet-400" aria-label="Logs da execução: expandir ou recolher">
      <span aria-hidden="true" className={warning ? 'text-amber-300' : 'text-emerald-300'}>◦</span>
      <span className="shrink-0 font-medium text-copy/75">Atividade</span>
      <span className="min-w-0 flex-1 truncate">{error ? 'Não foi possível atualizar os logs' : last ? activityLabel(last) : 'Aguardando atividade dos trabalhadores'}</span>
      <span className="shrink-0 text-[10px]">{status} · {log.length} eventos ⌄</span>
    </summary>
    <div className="max-h-52 overflow-y-auto border-t border-white/[.06] px-3 py-2" role="log" aria-label="Logs dos trabalhadores" aria-live="off">
      {error && <p className="mb-2 text-amber-200">{error}</p>}
      {!log.length && <p className="py-1">Os registros aparecerão aqui durante a execução.</p>}
      {log.slice().reverse().map(item => <div key={item.seq} className="border-b border-white/[.035] py-1.5 last:border-0">
        <div className="flex items-start gap-2"><time className="shrink-0 pt-px font-mono text-[9px] opacity-70">{new Date(item.created_at).toLocaleTimeString('pt-BR')}</time><span className={'min-w-0 break-words ' + (item.success === false || item.event === 'provider_error' ? 'text-amber-200' : '')}>{activity?.steps?.find(s => s.id === item.step_id)?.name && <span className="mr-1 text-copy/60">{activity.steps.find(s => s.id === item.step_id).name} ·</span>}{activityLabel(item)}</span></div>
        {(item.detail || item.error) && <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-words pl-12 text-[10px] text-amber-200/80">{item.detail || item.error}</pre>}
      </div>)}
    </div>
  </details>
}
