import { useEffect, useState } from 'react'

const input = 'mt-1 w-full rounded-xl border border-white/15 bg-black/20 px-3 py-2 text-xs'
const button = 'rounded-xl border border-white/15 px-3 py-2 text-xs disabled:opacity-40'

export default function GitDraftPanel({ api, connection, onClose }) {
  const [head, setHead] = useState('')
  const [base, setBase] = useState('main')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [history, setHistory] = useState([])
  const [notice, setNotice] = useState('')

  async function refreshHistory() {
    const items = await api('/git/connections/' + encodeURIComponent(connection.id) + '/draft-plans')
    setHistory(items)
  }
  useEffect(() => {
    let active = true
    api('/git/connections/' + encodeURIComponent(connection.id) + '/draft-plans')
      .then(items => { if (active) setHistory(items) })
      .catch(() => { /* The main form remains usable without history. */ })
    return () => { active = false }
  }, [connection.id])

  function update(setter, value) { setter(value); setPlan(null); setError('') }

  async function prepare(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice(''); setPlan(null)
    try {
      setPlan(await api('/git/connections/' + encodeURIComponent(connection.id) + '/draft-plans',
        'POST', { head, base, title, body }))
      await refreshHistory()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function approve() {
    if (!plan || busy || plan.state !== 'pending') return
    setBusy(true); setError('')
    try {
      const result = await api('/git/draft-plans/' + encodeURIComponent(plan.id) + '/approve',
        'POST', { confirmation: plan.confirmation })
      setPlan(current => ({ ...current, ...result }))
      await refreshHistory()
    } catch (err) {
      setError(err.message)
      try {
        const status = await api('/git/draft-plans/' + encodeURIComponent(plan.id))
        setPlan(current => ({ ...current, ...status }))
      } catch {
        // A lost response may follow an accepted write. Never offer a blind retry.
        setPlan(current => ({ ...current, state: 'uncertain' }))
      }
    } finally { setBusy(false) }
  }

  async function reconcile(planId) {
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api('/git/draft-plans/' + encodeURIComponent(planId) + '/reconcile',
        'POST', {})
      setPlan(current => current?.id === planId ? ({ ...current, ...result }) : current)
      if (result.reconciliation === 'unique_remote_match') {
        setNotice('Revisão identificada no provedor. Confira o estado e os commits.')
      } else if (result.reconciliation !== 'already_confirmed') {
        setNotice(result.notice || 'Conferência inconclusiva; a operação não foi repetida.')
      }
      await refreshHistory()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  return <section className="mt-4 rounded-2xl border border-violet-400/25 p-4">
    <div className="flex items-center justify-between gap-3">
      <h4 className="text-sm font-semibold">Preparar PR/MR em rascunho</h4>
      <button type="button" className={button} onClick={onClose}>Fechar</button>
    </div>
    <p className="mt-2 text-xs text-muted">{connection.service} · {connection.repository}. As branches precisam existir. Preparar consulta os commits atuais; a publicação acontece após você revisar e aprovar o plano. O token precisa permitir criar revisões.</p>
    <form onSubmit={prepare} className="mt-3 grid gap-3 sm:grid-cols-2">
      <label className="text-xs">Branch de origem<input required className={input} maxLength={200} value={head} onChange={e => update(setHead, e.target.value)} /></label>
      <label className="text-xs">Branch de destino<input required className={input} maxLength={200} value={base} onChange={e => update(setBase, e.target.value)} /></label>
      <label className="text-xs sm:col-span-2">Título<input required className={input} maxLength={200} value={title} onChange={e => update(setTitle, e.target.value)} /></label>
      <label className="text-xs sm:col-span-2">Descrição<textarea className={input} rows={4} maxLength={10000} value={body} onChange={e => update(setBody, e.target.value)} /></label>
      <button className={button} disabled={busy}>Preparar plano para revisão</button>
    </form>
    {error && <p role="alert" className="mt-3 text-xs text-rose-300">{error}</p>}
    {notice && <p role="status" className="mt-3 text-xs text-muted">{notice}</p>}
    {plan && <div className="mt-4 space-y-2 rounded-xl border border-white/15 p-3 text-xs">
      <h5 className="font-semibold">Plano de publicação · {plan.repository}</h5>
      <p>{plan.head} → {plan.base}</p>
      <p className="break-all font-mono text-muted">Origem: {plan.head_sha}<br />Destino: {plan.base_sha}</p>
      <p className="font-semibold">{plan.title}</p>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap">{plan.body || '(Sem descrição)'}</pre>
      <p className="text-muted">Aprovação válida até {new Date(plan.expires_at).toLocaleTimeString('pt-BR')}.</p>
      {plan.state === 'pending' && plan.confirmation && <button type="button" className={button} disabled={busy} onClick={approve}>Aprovar plano e criar rascunho</button>}
      {plan.state === 'pending' && !plan.confirmation && <p>Por segurança, planos recuperados do histórico não podem ser aprovados sem a confirmação original. Prepare outro plano se necessário.</p>}
      {plan.state === 'completed' && <p>Revisão criada: <a className="underline" href={plan.result.url} target="_blank" rel="noopener noreferrer">#{plan.result.number}</a>
        {plan.result.requires_review && ' · Confira os commits e o estado no serviço: a resposta não confirmou todo o plano.'}</p>}
      {['uncertain', 'executing'].includes(plan.state) && <div className="space-y-2">
        <p role="status">Resultado remoto incerto. Consulte o serviço antes de criar outro plano; nenhuma escrita será repetida.</p>
        <button type="button" className={button} disabled={busy} onClick={() => reconcile(plan.id)}>Procurar revisão no GitHub/GitLab (somente leitura)</button>
      </div>}
      {['failed', 'expired'].includes(plan.state) && <p role="status">Plano encerrado. Revise as informações e prepare um novo plano.</p>}
    </div>}
    <section className="mt-4 border-t border-white/10 pt-3" aria-label="Histórico de planos Git">
      <div className="flex items-center justify-between gap-2">
        <h5 className="text-xs font-semibold">Planos recentes</h5>
        <button type="button" className={button} disabled={busy}
          onClick={() => refreshHistory().catch(err => setError(err.message))}>Atualizar</button>
      </div>
      {history.length === 0 && <p className="mt-2 text-xs text-muted">Nenhum plano anterior.</p>}
      {history.map(item => <div key={item.id}
        className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 p-2 text-xs">
        <span className="min-w-0 break-words">{item.title} · {item.head} → {item.base}
          <span className="ml-2 text-muted">({item.state})</span>
        </span>
        <div className="flex gap-2">
          <button type="button" className={button} disabled={busy}
            onClick={() => { setPlan(item); setError(''); setNotice('') }}>Detalhes</button>
          {['uncertain','executing'].includes(item.state) &&
            <button type="button" className={button} disabled={busy}
              onClick={() => reconcile(item.id)}>Verificar remoto</button>}
        </div>
      </div>)}
    </section>
  </section>
}
