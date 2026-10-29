import { useEffect, useMemo, useState } from 'react'

const btn = 'rounded-xl border border-white/15 px-3 py-2 text-xs text-copy transition hover:bg-white/[.08] disabled:opacity-40'
const input = 'w-full rounded-xl border border-white/15 bg-[#151519] px-3 py-2.5 text-xs text-copy outline-none focus:border-violet-400/60'

function eventLabel(item) {
  const kind = item.event
  if (kind === 'native_session_started') return 'Sessão Codex iniciada: ' + item.model
  if (kind === 'native_session_resumed') return 'Sessão Codex retomada: ' + item.model
  if (kind === 'native_turn_completed') return 'Resposta Codex recebida: ' + item.model
  if (kind === 'delivery_repair_queued') return 'Autocorreção da entrega: tentativa ' + item.attempt
  if (kind === 'agent_message_sent') return 'Mensagem entre trabalhadores: ' + item.message_type
  if (kind === 'agent_messages_delivered') return 'Mensagens recebidas pelo trabalhador: ' + item.count
  if (kind === 'worker_heartbeat') return 'IA ainda processando'
  if (kind === 'worker_phase') return item.stage || 'Trabalhador em ação'
  if (kind === 'model_selected') return 'Modelo selecionado: ' + (item.model || 'não informado')
  if (kind === 'skill_context_selected') {
    const selected = [...new Set((item.selected_skills || []).map(skill => skill.name))]
    const available = [...new Set(item.available_skills || [])]
    return selected.length
      ? 'Skills no contexto: ' + selected.join(', ')
      : item.available_count
        ? 'Skills ativas encontradas: ' + available.join(', ') +
          (item.inventory_truncated ? ' (lista parcial)' : '') +
          '; nenhuma foi relevante para este pedido'
        : 'Nenhuma Skill ativa vinculada ao projeto ou trabalhador desta execução'
  }
  if (kind === 'workspace_action_requested') return 'Iniciando: ' + (item.description || item.action || 'ferramenta')
  if (kind === 'workspace_action_result') return (item.success ? 'Concluído: ' : 'Falhou: ') + (item.description || item.action || 'ferramenta')
  if (kind === 'worker_message') {
    const action = item.action === 'reference_search' ? 'pesquisa de referências'
      : item.action === 'browser_tool' ? 'Chrome DevTools MCP'
        : item.action || 'ação'
    return (item.ok === false ? 'Falha da ferramenta: ' : 'Agente: ') + action +
      (item.command || item.path || item.tool
        ? ' · ' + (item.command || item.path || item.tool) : '')
  }
  if (kind === 'workspace_validation') return item.success === false ? 'Verificações falharam' : 'Validação executada'
  if (kind === 'workspace_approval_required') return 'Aguardando sua autorização'
  if (kind === 'workspace_feedback_received') return 'Ajuste recebido'
  if (kind === 'workspace_feedback_applied') return 'Ajuste recebido pelo trabalhador'
  if (kind === 'run_failed') return 'Tarefa falhou: ' + (item.error || 'verifique o chat')
  if (kind === 'run_completed') return 'Execução concluída'
  if (kind === 'run_paused_limit') return 'Limite de ciclos atingido: checkpoint salvo'
  if (kind === 'run_resumed') return 'Tarefa continuada a partir do checkpoint'
  if (kind === 'worker_checkpoint_restored') return 'Contexto anterior do trabalhador restaurado'
  if (kind === 'worker_budget_warning') return 'Limite próximo: ' + item.remaining_rounds + ' ciclo(s) restante(s); checkpoint automático disponível'
  if (kind === 'run_status') return 'Estado: ' + (item.status || 'alterado')
  if (kind === 'step_status') return 'Etapa: ' + (item.status || 'executando')
  if (kind === 'provider_error') return 'Provedor retornou erro: ' + (item.error || 'detalhe indisponível')
  return kind.replaceAll('_', ' ')
}

export default function ExecutionPanel({ api, runId, active, onStop, onClose, onFeedback, onResume, width }) {
  const [tab, setTab] = useState('preview')
  const [activity, setActivity] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [preview, setPreview] = useState({ status: 'stopped' })
  const [projects, setProjects] = useState([])
  const [cwd, setCwd] = useState('')
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [frameKey, setFrameKey] = useState(0)
  const [frameState, setFrameState] = useState('idle')
  const [urlInput, setUrlInput] = useState('')

  useEffect(() => {
    let mounted = true
    const poll = async () => {
      if (!runId) return
      try {
        const response = await api('/runs/' + encodeURIComponent(runId) + '/activity')
        if (mounted) { setActivity(response); setError('') }
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
      activity?.status === 'completed' ? (activity?.delivery_verified ? 'Concluído com testes' : 'Concluído') :
      activity?.status === 'cancelled' ? 'Parado' :
      activity?.status === 'paused_limit' ? 'Pausado por limite · progresso salvo' :
      activity?.status === 'failed' ? 'Falhou por erro' : 'Sem tarefa ativa'
  const canContinue = !isRunning && ['paused_limit', 'failed', 'cancelled'].includes(activity?.status)
  const checkpoints = activity?.checkpoints || []
  const log = useMemo(() => (activity?.events || []).filter(event =>
    !['worker_heartbeat'].includes(event.event)).slice().reverse(), [activity])

  async function control(action, payload) {
    setError(''); setLoading(action)
    try {
      if (action === 'start') {
        if (!window.confirm('Iniciar o servidor npm dev deste projeto? O script executa código real no seu Windows, com os privilégios da sua conta.')) return
        const result = await api('/preview/start', 'POST', { cwd })
        setPreview(result); setUrlInput(result.url || ''); setFrameState('loading'); setFrameKey(n => n + 1)
      } else {
        const result = await api('/preview/stop', 'POST', {})
        setPreview(result)
      }
    } catch (e) { setError(e.message) }
    finally { setLoading('') }
  }

  async function send(e) {
    e.preventDefault()
    if (!(active || canContinue) || !note.trim() || loading) return
    setLoading('note'); setError('')
    try {
      await onFeedback(note.trim())
      setNote('')
    } catch (e) { setError(e.message) }
    finally { setLoading('') }
  }

  const requestedPreview = urlInput || preview.url || ''
  const safePreview = /^https?:\/\/(?:127\.0\.0\.1|localhost):\d{1,5}(?:\/|$)/.test(requestedPreview)
    ? requestedPreview : null
  return <aside aria-label="Painel da execução e prévia" style={{'--execution-panel-width': `${width || 50}%`}} className="flex h-full min-h-0 w-full flex-col border-t border-white/10 bg-[#17171b] lg:w-[var(--execution-panel-width)] lg:border-l lg:border-t-0">
    {tab !== 'preview' && <div className="shrink-0 border-b border-white/10 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <strong className="text-sm">Central de execução</strong>
        <div className="flex items-center gap-2">
          {isRunning && <button type="button" onClick={onStop} className={btn + ' border-rose-300/30 text-rose-200'}>■ Parar tarefa</button>}
          {canContinue && <button type="button" onClick={onResume} className={btn + ' border-violet-400/40 text-violet-200'}>↻ Continuar execução</button>}
          {runId && <a href={'/api/runs/' + encodeURIComponent(runId) + '/export?format=md'}
            download className={btn}>Exportar relatório</a>}
          <button type="button" aria-label="Fechar painel" onClick={onClose} className={btn}>✕</button>
        </div>
      </div>
      <p role="status" className={'mt-2 text-xs ' + tone}>{isRunning ? '● ' : ''}{state}</p>
      {activity?.error && <p role="alert" className="mt-2 break-words rounded-lg bg-amber-300/[.06] p-2 text-[11px] text-amber-200">{activity.error}</p>}
      <p className="mt-1 text-[10px] text-muted">{last ? 'Último evento: ' + Math.max(0, idle) + ' s atrás' : 'Nenhum evento recebido.'} · Sem atividade não significa necessariamente travamento.</p>
      {(activity?.workspace_binding || checkpoints.length > 0) && <details className="mt-2 rounded-xl border border-white/10 px-3 py-2 text-[10px] leading-5 text-muted">
        <summary className="cursor-pointer font-semibold text-violet-200">Detalhes técnicos da execução</summary>
        {activity?.workspace_binding && <div className="mt-2"><p className="break-all font-mono">{activity.workspace_binding.folder}</p><p>Permissão inicial: {activity.workspace_binding.initial_mode} · Executor: {activity.workspace_binding.command_runner === 'docker' ? 'Docker isolado' : 'Host local'}</p></div>}
        {checkpoints.length > 0 && <div className="mt-2 space-y-1 border-t border-white/10 pt-2">
        <strong className="block text-[11px] text-violet-200">Checkpoint</strong>
        {checkpoints.map(cp => <div key={cp.step_id} className="text-[11px] leading-5 text-muted">
          <p>{cp.state==='paused_limit' ? 'Pausado e salvo' : cp.state==='blocked' ? 'Interrompido após ação repetida sem sucesso' : cp.state==='completed' ? 'Etapa concluída' : 'Em execução'} · {cp.rounds_total} ciclos · {cp.actions_total} ações · {cp.resumes} retomada(s)</p>
          <p>Última ação: <span className="break-all text-copy">{cp.last_action || 'Ainda não registrada'}</span></p>
          {cp.last_result && <p className="break-words">Resultado: {cp.last_result.slice(0,220)}</p>}
          {cp.changed_files?.length > 0 && <p className="break-words">Arquivos alterados: {cp.changed_files.join(', ')}</p>}
          {cp.last_validation && <details><summary className="cursor-pointer text-violet-200">Última validação</summary><pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap text-[10px]">{cp.last_validation}</pre></details>}
        </div>)}
        </div>}</details>}
      {activity?.steps?.length > 0 && !isRunning && <p className="mt-2 text-[10px] text-muted">Etapas: {activity.steps.map(x => x.name + ' (' + (x.status==='paused_limit'?'pausado':x.status) + ')').join(' → ')}</p>}
      <div className="mt-3 flex gap-2">
        <button type="button" aria-pressed={tab==='activity'} onClick={() => setTab('activity')} className={btn + (tab==='activity' ? ' border-violet-400 text-violet-200' : '')}>Logs</button>
        <button type="button" aria-pressed={tab==='preview'} onClick={() => setTab('preview')} className={btn + (tab==='preview' ? ' border-violet-400 text-violet-200' : '')}>Navegador</button>
      </div>
    </div>}

    {tab === 'activity' ? <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
      <section aria-label="Equipe em execução" className="rounded-xl border border-white/10 p-3 text-xs">
        <h3 className="font-semibold">Trabalhadores e comunicação</h3>
        <div className="mt-2 space-y-1">{(activity?.steps || []).map(step =>
          <p key={step.id} className="break-words text-muted">{step.name} · {step.status}</p>)}</div>
        {(activity?.agent_messages || []).map(message => <details key={message.id} className="mt-2 border-t border-white/10 pt-2">
          <summary className="cursor-pointer break-words">{message.sender_name} → {message.recipient_name} · {message.message_type} · {message.state === 'delivered' ? 'Recebida' : 'Aguardando leitura'}</summary>
          <p className="mt-2 whitespace-pre-wrap break-words text-muted">{message.content}</p>
        </details>)}
      </section>
      {log.length ? log.map(item => <div key={item.seq} className="rounded-xl border border-white/[.08] bg-white/[.025] p-3">
        <div className="flex items-start justify-between gap-2">
          <span className="break-words text-xs text-copy">{eventLabel(item)}</span>
          <time className="shrink-0 text-[10px] text-muted" dateTime={item.created_at}>
            {new Date(item.created_at).toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit',second:'2-digit'})}
          </time>
        </div>
        {item.path && <p className="mt-1 break-all font-mono text-[10px] text-muted">{item.path}</p>}
        {item.detail && <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-rose-400/[.04] p-2 font-mono text-[10px] text-rose-200">{item.detail}</pre>}
        {item.error && <p className="mt-2 break-words text-[11px] text-rose-200">{item.error}</p>}
      </div>) : <p className="p-4 text-xs text-muted">Os eventos de ferramentas, modelos e validações aparecerão aqui.</p>}
    </div> : <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-0">
      {preview.status !== 'running' && <p className="p-3 text-[11px] leading-5 text-muted">Escolha o aplicativo da pasta autorizada. A prévia inicia um servidor npm dev apenas em 127.0.0.1.</p>}
      {preview.status !== 'running' && <div className="flex flex-wrap gap-2 px-3">
        <select value={cwd} onChange={e => setCwd(e.target.value)} aria-label="Aplicativo para prévia"
          className={input + ' min-w-0 flex-1'}>
          {!projects.length && <option value="">Nenhum projeto npm dev encontrado</option>}
          {projects.map(item => <option key={item.cwd} value={item.cwd}>{item.name} · {item.cwd || 'raiz'}</option>)}
        </select>
        <button type="button" className={btn} disabled={!projects.length || !!loading} onClick={() => control('start')}>▶ Iniciar prévia</button>
      </div>}
      <form className="flex shrink-0 items-center gap-2 border-b border-white/10 bg-[#17171b] px-3 py-2" onSubmit={event => { event.preventDefault(); setFrameState('loading'); setFrameKey(n => n + 1) }}>
        <span aria-hidden="true" className="text-xs text-emerald-300">●</span>
        <input aria-label="Endereço da prévia local" value={requestedPreview} onChange={event => setUrlInput(event.target.value)}
          placeholder="http://127.0.0.1:porta/" className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-copy outline-none placeholder:text-muted" />
        <button type="submit" className={btn} title="Atualizar página">↻</button>
        {safePreview && <a href={safePreview} target="_blank" rel="noopener noreferrer" className={btn} title="Abrir em nova janela">↗</a>}
      </form>
      {requestedPreview && !safePreview && <p role="alert" className="px-3 py-2 text-[11px] text-amber-200">Use apenas uma URL local, como http://127.0.0.1:5173/.</p>}
      {safePreview ? <div className="relative flex min-h-[330px] flex-1 overflow-hidden bg-white">
        {frameState === 'loading' && <div className="absolute inset-0 z-10 grid place-items-center bg-white text-xs text-slate-600">Carregando a página local…</div>}
        <iframe key={frameKey} title="Navegador embutido: prévia local do aplicativo" src={safePreview}
          sandbox="allow-scripts allow-forms allow-modals allow-popups allow-same-origin" referrerPolicy="no-referrer" onLoad={() => setFrameState('loaded')}
          className="min-h-[330px] w-full flex-1 border-0 bg-white" />
      </div> :
        <div className="grid min-h-[260px] flex-1 place-items-center rounded-xl border border-dashed border-white/15 text-center text-xs text-muted">Inicie a prévia para visualizar o site aqui.</div>}
    </div>}

    {tab !== 'preview' && (active || canContinue) && <form onSubmit={send} className="shrink-0 border-t border-white/10 p-3">
      <label className="block text-xs font-semibold">Conversar durante a execução</label>
      <p className="mt-1 text-[10px] text-muted">{canContinue ? 'A execução não terminou. Confira o motivo e o último resultado acima; corrija arquivos/permissões ou envie um ajuste, depois clique em Continuar execução.' : 'O próximo ciclo do trabalhador receberá seu ajuste. Isso não interrompe a operação já iniciada.'}</p>
      <textarea value={note} onChange={e=>setNote(e.target.value)} maxLength={1800} rows={2}
        placeholder="Ex.: Deixe o título maior e troque a cor do botão..." className={input + ' mt-2 resize-y'}/>
      <button type="submit" disabled={!note.trim() || !!loading} className={btn + ' mt-2 border-violet-400/40'}>Enviar ajuste aos trabalhadores</button>
    </form>}
    {tab !== 'preview' && error && <p role="alert" className="shrink-0 border-t border-rose-300/15 px-4 py-2 text-xs text-rose-200">{error}</p>}
  </aside>
}
