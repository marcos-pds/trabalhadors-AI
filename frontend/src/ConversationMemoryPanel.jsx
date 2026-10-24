import { useEffect, useState } from 'react'

const field = 'min-h-10 w-full rounded-xl border border-white/10 bg-[#191919] px-3 py-2 text-xs text-copy outline-none focus:border-lilac/60'
const action = 'rounded-xl border border-white/15 px-3 py-2 text-xs font-semibold transition hover:bg-white/10 disabled:opacity-40'

export default function ConversationMemoryPanel({
  api, projects, conversation, initialProjectId, onMove, onSelectNewProject,
  onRefresh, onOpenConversation, onClose, projectOnly = false,
}) {
  const currentProjectId = projectOnly ? initialProjectId : conversation?.project_id || initialProjectId || ''
  const [projectId, setProjectId] = useState(currentProjectId || '')
  const [notes, setNotes] = useState('')
  const [retrieval, setRetrieval] = useState(null)
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState('project')
  const [results, setResults] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const activeProject = projects.find(p => p.id === projectId)

  useEffect(() => {
    setNotes(activeProject?.memory_notes || '')
  }, [projectId, activeProject?.memory_notes])

  useEffect(() => {
    let active = true
    setRetrieval(null)
    if (projectId) api('/projects/' + encodeURIComponent(projectId) + '/retrieval')
      .then(value => { if (active) setRetrieval(value) })
      .catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [projectId, api])

  async function toggleRetrieval() {
    setBusy('retrieval'); setError('')
    try {
      setRetrieval(await api('/projects/' + encodeURIComponent(projectId) + '/retrieval',
        'PUT', { enabled: !retrieval?.enabled }))
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  async function saveNotes() {
    if (!activeProject) return
    setBusy('notes'); setError('')
    try {
      await api('/projects/' + encodeURIComponent(activeProject.id) + '/memory', 'PUT', { notes })
      await onRefresh()
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }

  async function saveScope() {
    setBusy('scope'); setError('')
    try {
      if (conversation) {
        if (!window.confirm('Mover esta conversa altera quais memórias do projeto os agentes poderão usar. Confirmar?')) return
        await onMove(conversation.id, projectId || null)
      } else {
        onSelectNewProject(projectId || null)
      }
      onClose()
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }

  async function search(e) {
    e.preventDefault()
    if (query.trim().length < 3) return
    setBusy('search'); setError(''); setResults(null)
    try {
      const params = new URLSearchParams({ q: query.trim(), scope })
      if (scope === 'project' && projectId) params.set('project_id', projectId)
      setResults(await api('/conversations/search?' + params.toString()))
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }

  return <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" onKeyDown={e => { if (e.key === 'Escape') onClose() }}>
    <section role="dialog" aria-modal="true" aria-labelledby="memory-panel-title" className="my-auto max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-white/10 bg-[#202023] p-5 shadow-2xl sm:p-7">
      <div className="flex items-start justify-between gap-4">
        <div><h2 id="memory-panel-title" className="text-xl font-semibold">Memória e histórico</h2>
          <p className="mt-2 text-xs leading-5 text-muted">Agentes lembram do contexto recente e, em projetos, recuperam trechos relacionados de outras conversas desse mesmo projeto.</p>
        </div>
        <button type="button" className={action} onClick={onClose} aria-label="Fechar memória">✕</button>
      </div>

      <section className="mt-5 rounded-2xl border border-white/10 bg-black/10 p-4">
        <h3 className="text-sm font-semibold">Contexto da conversa</h3>
        {!projectOnly && <>
          <label className="mt-3 block text-xs text-muted">Projeto associado
            <select value={projectId} onChange={e => { setProjectId(e.target.value); setResults(null) }} className={field + ' mt-2'}>
              <option value="">Sem projeto (memória curta)</option>
              {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <button type="button" onClick={saveScope} disabled={!!busy || projectId === currentProjectId} className={action + ' mt-3'}>
            {conversation ? 'Mover conversa para este escopo' : 'Usar este escopo na próxima conversa'}
          </button>
        </>}
        <p className="mt-3 text-xs leading-5 text-muted">
          {projectId ? 'Projeto: até 32 mensagens recentes (15 mil caracteres), notas fixadas e até 6 trechos relacionados de outras conversas deste projeto.' :
            'Avulsa: até 6 mensagens recentes (2.600 caracteres), sem recuperar outras conversas.'}
          {' '}Esses limites são do contexto enviado à IA; suas mensagens não são excluídas.
        </p>
      </section>

      {activeProject && <section className="mt-4 rounded-2xl border border-white/10 p-4">
        <h3 className="text-sm font-semibold">Busca semântica local</h3>
        <p className="mt-2 text-xs leading-5 text-muted">Com sua autorização, trechos deste projeto são enviados ao Ollama local para buscar por significado. A busca mantém suas conversas privadas. Se o serviço estiver indisponível, a busca por palavras continua funcionando.</p>
        <button type="button" onClick={toggleRetrieval} disabled={!!busy || !retrieval} className={action + ' mt-3'}>
          {retrieval?.enabled ? 'Desativar busca semântica' : 'Ativar busca semântica local'}
        </button>
      </section>}

      {activeProject && <section className="mt-4 rounded-2xl border border-white/10 p-4">
        <h3 className="text-sm font-semibold">Notas permanentes do projeto</h3>
        <p className="mt-2 text-xs leading-5 text-muted">Fixe decisões, tecnologias, requisitos e pendências importantes. Os agentes recebem essas notas nas conversas deste projeto. Edite quando algo mudar.</p>
        <textarea aria-label="Notas do projeto" maxLength={8000} rows={5} value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="Ex.: API FastAPI, frontend React; decisão: autenticação local; pendente: auditoria de permissões..."
          className={field + ' mt-3 resize-y'}/>
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="text-[10px] text-muted">{notes.length}/8000 caracteres</span>
          <button type="button" className={action} onClick={saveNotes} disabled={!!busy || notes === (activeProject.memory_notes || '')}>{busy === 'notes' ? 'Salvando...' : 'Salvar notas'}</button>
        </div>
      </section>}

      <section className="mt-4 rounded-2xl border border-white/10 p-4">
        <h3 className="text-sm font-semibold">Buscar em conversas antigas</h3>
        <p className="mt-2 text-xs leading-5 text-muted">Por padrão, busca somente {projectId ? 'neste projeto' : 'nas conversas avulsas'}. Buscar em tudo é manual e não mistura resultados com a memória dos agentes.</p>
        <form onSubmit={search} className="mt-3 space-y-3">
          <input aria-label="Pesquisar histórico" placeholder="Busque uma decisão, recurso, erro, tecnologia..." value={query} maxLength={140} onChange={e => setQuery(e.target.value)} className={field}/>
          <div className="flex flex-wrap items-center gap-3">
            <select aria-label="Escopo da busca" value={scope} onChange={e => { setScope(e.target.value); setResults(null) }} className={field + ' flex-1'}>
              <option value="project">{projectId ? 'Somente este projeto' : 'Somente conversas avulsas'}</option>
              <option value="all">Todas as minhas conversas (busca manual)</option>
            </select>
            <button type="submit" className={action} disabled={!!busy || query.trim().length < 3}>{busy === 'search' ? 'Buscando...' : 'Buscar'}</button>
          </div>
        </form>
        {results !== null && <div aria-live="polite" className="mt-4 max-h-60 space-y-2 overflow-y-auto">
          {!results.length && <p className="text-xs text-muted">Nenhuma conversa relevante encontrada neste escopo.</p>}
          {results.map((item, index) => <button type="button" key={item.conversation_id + ':' + index}
            onClick={() => { onClose(); onOpenConversation(item.conversation_id) }}
            className="w-full rounded-xl border border-white/10 bg-white/[.025] p-3 text-left hover:border-lilac/40">
            <strong className="block truncate text-xs">{item.title}</strong>
            <small className="mt-1 block text-[10px] text-muted">{item.project_name || 'Sem projeto'} · {item.role === 'user' ? 'Você' : 'Central IA'}</small>
            <p className="mt-2 line-clamp-3 break-words text-xs text-muted">{item.snippet}</p>
          </button>)}
        </div>}
      </section>
      {error && <p role="alert" className="mt-4 text-xs text-rose-300">{error}</p>}
    </section>
  </div>
}
