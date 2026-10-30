import { useEffect, useState } from 'react'

const input = 'mt-1 w-full rounded-xl border border-white/15 bg-black/20 px-3 py-2 text-xs'
const button = 'rounded-xl border border-white/15 px-3 py-2 text-xs disabled:opacity-40'

export default function KnowledgePanel({ api, projectId }) {
  const [documents, setDocuments] = useState([])
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [visibility, setVisibility] = useState('private')
  const [retention, setRetention] = useState('90')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endpoint = '/projects/' + encodeURIComponent(projectId) + '/knowledge'

  useEffect(() => {
    let active = true
    setDocuments([]); setContent(''); setTitle(''); setError('')
    api(endpoint).then(rows => { if (active) setDocuments(rows) })
      .catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [api, endpoint])

  async function readFile(event) {
    const file = event.target.files?.[0]
    if (!file) return
    if (file.size > 128000) { setError('O documento deve ter até 128 KB.'); return }
    try {
      setContent(await file.text()); setTitle(file.name.slice(0, 140)); setError('')
    } catch { setError('Não foi possível ler o documento. Use texto UTF-8.'); }
  }

  async function save(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      await api(endpoint, 'POST', { title, content, visibility,
        retention_days: retention === 'permanent' ? null : Number(retention) })
      setDocuments(await api(endpoint)); setTitle(''); setContent('')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function remove(id) {
    setBusy(true); setError('')
    try {
      await api(endpoint + '/' + encodeURIComponent(id), 'DELETE')
      setDocuments(rows => rows.filter(row => row.id !== id))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <section className="mt-4 rounded-2xl border border-white/10 p-4">
    <h3 className="text-sm font-semibold">Documentos de referência</h3>
    <p className="mt-2 text-xs leading-5 text-muted">Adicione requisitos, decisões ou manuais em texto. Os agentes recuperam trechos relevantes com a fonte identificada. Documentos privados ficam disponíveis apenas para você; documentos do projeto podem ser usados pelos membros autorizados.</p>
    <form onSubmit={save} className="mt-3 space-y-3">
      <label className="block text-xs">Arquivo de texto (opcional, até 128 KB)
        <input type="file" accept=".txt,.md,.markdown" onChange={readFile} className={input} /></label>
      <label className="block text-xs">Título<input required maxLength={140} className={input} value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label className="block text-xs">Conteúdo<textarea required rows={4} maxLength={128000} className={input} value={content} onChange={e => setContent(e.target.value)} /></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs">Quem pode usar<select className={input} value={visibility} onChange={e => setVisibility(e.target.value)}>
          <option value="private">Somente eu</option><option value="project">Membros deste projeto</option>
        </select></label>
        <label className="text-xs">Prazo de retenção<select className={input} value={retention} onChange={e => setRetention(e.target.value)}>
          <option value="30">30 dias</option><option value="90">90 dias</option>
          <option value="365">1 ano</option><option value="permanent">Até eu excluir</option>
        </select></label>
      </div>
      <button className={button} disabled={busy}>Adicionar referência</button>
    </form>
    {error && <p role="alert" className="mt-3 text-xs text-rose-300">{error}</p>}
    <ul className="mt-4 space-y-3">{documents.map(doc => <li key={doc.id} className="flex items-start justify-between gap-3 text-xs">
      <div><strong>{doc.title}</strong><p className="mt-1 text-muted">
        {doc.visibility === 'private' ? 'Privado' : 'Compartilhado no projeto'}
        {' · '}{doc.expires_at ? 'Expira em ' + new Date(doc.expires_at).toLocaleDateString('pt-BR') : 'Até exclusão manual'}
      </p></div>
      {!!doc.owned && <button type="button" disabled={busy} className={button} onClick={() => remove(doc.id)}>Excluir</button>}
    </li>)}</ul>
  </section>
}
