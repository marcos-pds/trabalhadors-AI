import { useEffect, useMemo, useState } from 'react'

const btn = 'rounded-xl border border-white/15 px-3 py-2 text-xs text-copy transition hover:bg-white/[.08] disabled:opacity-40'
const input = 'w-full rounded-xl border border-white/15 bg-[#151519] px-3 py-2.5 text-xs text-copy outline-none focus:border-violet-400/60'

function eventLabel(item) {
  const kind = item.event
  if (kind === 'worker_heartbeat') return 'IA ainda processando'
  if (kind === 'worker_phase') return item.stage || 'Trabalhador em ação'
  if (kind === 'model_selected') return 'Modelo selecionado: ' + (item.model || 'não informado')
  if (kind === 'workspace_action_requested') return 'Iniciando: ' + (item.description || item.action || 'ferramenta')
  if (kind === 'workspace_action_result') return (item.success ? 'Concluído: ' : 'Falhou: ') + (item.description || item.action || 'ferramenta')
  if (kind === 'worker_message') return 'Agente: ' + (item.action || 'ação') + (item.command || item.path ? ' · ' + (item.command || item.path) : '')
  if (kind === 'workspace_validation') return item.success === false ? 'Verificações falharam' : 'Validação executada'
  if (kind === 'workspace_approval_required') return 'Aguardando sua autorização'
  if (kind === 'workspace_feedback_received') return 'Ajuste recebido'
  if (kind === 'workspace_feedback_applied') return 'Ajuste recebido pelo trabalhador'
  if (kind === 'run_failed') return 'Tarefa falhou: ' + (item.error || 'verifique o chat')
  if (kind === 'run_completed') return 'Execução concluída'
  if (kind === 'run_status') return 'Estado: ' + (item.status || 'alterado')
  if (kind === 'step_status') return 'Etapa: ' + (item.status || 'executando')
  if (kind === 'provider_error') return 'Provedor retornou erro'
  return kind.replaceAll('_', ' ')
}

export default function ExecutionPanel({ api, runId, active, onStop, onClose, onFeedback }) {
  const [tab, setTab] = useState('activity')
  const [activity, setActivity] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [preview, setPreview] = useState({ status: 'stopped' })
  const [projects, setProjects] = useState([])
  const [cwd, setCwd] = useState('')
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [frameKey, setFrameKey] = useState(0)

  useEffect(() => {
    let mounted = true
    const poll = async () => {
      if (!runId) return
      try {
        const response = await api('/runs/' + encodeURIComponent(runId) + '/activity')
        if (mounted) setActivity(response)
      } catch (e) { if (mounted) setError(e.message) }
    }
    poll()
    const id = setInterval(() => { setNow(Date.now()); poll() }, 3000)
    return () => { mounted = false; clearInterval(id) }
  }, [api, runId])

  useEffect(() => {
    let mounted = true
    const poll = async () => {
      try {
        const result = await api('/preview/status')
        if (mounted) setPreview(result)
      } catch { /* Preview runs only on the local computer. */ }
    }
    poll()
    const id = setInterval(poll, 6000)
    return () => { mounted = false; clearInterval(id) }
  }, [api])

  useEffect(() => {
    if (tab !== 'preview') return
    let mounted = true
    api('/preview/projects').then(result => {
      if (!mounted) return
      setProjects(result.projects || [])
      setCwd(selected => (result.projects || []).some(p => p.cwd === selected)
        ? selected : (result.projects?.[0]?.cwd || ''))
    }).catch(e => { if (mounted) setError(e.message) })
    return () => { mounted = false }
  }, [api, tab])

  const last = activity?.last_activity_at
  const idle = last ? Math.max(0, Math.floor((now - new Date(last).getTime()) / 1000)) : null
  const isRunning = active && ['queued', 'running', 'awaiting_approval'].includes(activity?.status || 'running')
  const tone = isRunning && idle !== null && idle > 45 ? 'text-amber-200' :
    isRunning ? 'text-emerald-200' : 'text-muted'
  const state = isRunning && idle !== null && idle > 45
    ? 'Sem atividade recente — verifique o log'
    : activity?.status === 'awaiting_approval' ? 'Aguardando sua aprovação'
    : isRunning ? 'Trabalhadores em atividade' :
      activity?.status === 'completed' ? 'Concluído' :
      activity?.status === 'cancelled' ? 'Parado' :
      activity?.status === 'failed' ? 'Falhou' : 'Sem tarefa ativa'
  const log = useMemo(() => (activity?.events || []).filter(event =>
    !['worker_heartbeat'].includes(event.event)).slice().reverse(), [activity])

  async function control(action, payload) {
    setError(''); setLoading(action)
    try {
      if (action === 'start') {
        if (!window.confirm('Iniciar o servidor npm dev deste projeto? O script executa código real no seu Windows, com os privilégios da sua conta.')) return
        const result = await api('/preview/start', 'POST', { cwd })
        setPreview(result); setFrameKey(n => n + 1)
      } else {
        const result = await api('/preview/stop', 'POST', {})
        setPreview(result)
      }
    } catch (e) { setError(e.message) }
    finally { setLoading('') }
  }

  async function send(e) {
    e.preventDefault()
    if (!active || !note.trim() || loading) return
    setLoading('note'); setError('')
    try {
      await onFeedback(note.trim())
      setNote('')
    } catch (e) { setError(e.message) }
    finally { setLoading('') }
  }

  const safePreview = preview.url?.startsWith('http://127.0.0.1:') ? preview.url : null
  return <aside aria-label="Painel da execução e prévia" className="flex h-full min-h-0 w-full flex-col border-t border-white/10 bg-[#17171b] lg:w-[48%] lg:border-l lg:border-t-0">
    <div className="shrink-0 border-b border-white/10 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <strong className="text-sm">Central de execução</strong>
        <div className="flex items-center gap-2">
          {isRunning && <button type="button" onClick={onStop} className={btn + ' border-rose-300/30 text-rose-200'}>■ Parar tarefa</button>}
          <button type="button" aria-label="Fechar painel" onClick={onClose} className={btn}>✕</button>
        </div>
      </div>
      <p role="status" className={'mt-2 text-xs ' + tone}>{isRunning ? '● ' : ''}{state}</p>
      <p className="mt-1 text-[10px] text-muted">{last ? 'Último evento: ' + Math.max(0, idle) + ' s atrás' : 'Nenhum evento recebido.'} · Sem atividade não significa necessariamente travamento.</p>
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={() => setTab('activity')} className={btn + (tab==='activity' ? ' border-violet-400 text-violet-200' : '')}>Atividade e logs</button>
        <button type="button" onClick={() => setTab('preview')} className={btn + (tab==='preview' ? ' border-violet-400 text-violet-200' : '')}>Prévia ao vivo</button>
      </div>
    </div>

    {tab === 'activity' ? <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
      {log.length ? log.map(item => <div key={item.seq} className="rounded-xl border border-white/[.08] bg-white/[.025] p-3">
        <div className="flex items-start justify-between gap-2">
          <span className="break-words text-xs text-copy">{eventLabel(item)}</span>
          <time className="shrink-0 text-[10px] text-muted" dateTime={item.created_at}>
            {new Date(item.created_at).toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit',second:'2-digit'})}
          </time>
        </div>
        {item.path && <p className="mt-1 break-all font-mono text-[10px] text-muted">{item.path}</p>}
      </div>) : <p className="p-4 text-xs text-muted">Os eventos de ferramentas, modelos e validações aparecerão aqui.</p>}
    </div> : <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
      <p className="text-[11px] leading-5 text-muted">Escolha o aplicativo da pasta autorizada. A prévia inicia um servidor npm dev apenas em 127.0.0.1. Mudanças podem aparecer via atualização automática do framework.</p>
      {preview.status !== 'running' && <div className="flex flex-wrap gap-2">
        <select value={cwd} onChange={e => setCwd(e.target.value)} aria-label="Aplicativo para prévia"
          className={input + ' min-w-0 flex-1'}>
          {!projects.length && <option value="">Nenhum projeto npm dev encontrado</option>}
          {projects.map(item => <option key={item.cwd} value={item.cwd}>{item.name} · {item.cwd || 'raiz'}</option>)}
        </select>
        <button type="button" className={btn} disabled={!projects.length || !!loading} onClick={() => control('start')}>▶ Iniciar prévia</button>
      </div>}
      {preview.status === 'running' && <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted">{preview.cwd || 'raiz'} · {safePreview}</span>
        <button type="button" onClick={() => setFrameKey(n=>n+1)} className={btn}>↻ Atualizar</button>
        {safePreview && <a href={safePreview} target="_blank" rel="noopener noreferrer" className={btn}>Abrir janela ↗</a>}
        <button type="button" disabled={!!loading} onClick={() => control('stop')} className={btn}>Parar prévia</button>
      </div>}
      {safePreview ? <iframe key={frameKey} title="Prévia local do aplicativo" src={safePreview}
        sandbox="allow-scripts allow-forms" referrerPolicy="no-referrer"
        className="min-h-[330px] w-full flex-1 rounded-xl border border-white/20 bg-white" /> :
        <div className="grid min-h-[260px] flex-1 place-items-center rounded-xl border border-dashed border-white/15 text-center text-xs text-muted">Inicie a prévia para visualizar o site aqui.</div>}
    </div>}

    {active && <form onSubmit={send} className="shrink-0 border-t border-white/10 p-3">
      <label className="block text-xs font-semibold">Conversar durante a execução</label>
      <p className="mt-1 text-[10px] text-muted">O próximo ciclo do trabalhador receberá seu ajuste. Isso não interrompe a operação já iniciada.</p>
      <textarea value={note} onChange={e=>setNote(e.target.value)} maxLength={1800} rows={2}
        placeholder="Ex.: Deixe o título maior e troque a cor do botão..." className={input + ' mt-2 resize-y'}/>
      <button type="submit" disabled={!note.trim() || !!loading} className={btn + ' mt-2 border-violet-400/40'}>Enviar ajuste aos trabalhadores</button>
    </form>}
    {error && <p role="alert" className="shrink-0 border-t border-rose-300/15 px-4 py-2 text-xs text-rose-200">{error}</p>}
  </aside>
}
