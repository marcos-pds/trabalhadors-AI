import { useState } from 'react'

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

  function update(setter, value) { setter(value); setPlan(null); setError('') }

  async function prepare(event) {
    event.preventDefault(); setBusy(true); setError(''); setPlan(null)
    try {
      setPlan(await api('/git/connections/' + encodeURIComponent(connection.id) + '/draft-plans',
        'POST', { head, base, title, body }))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function approve() {
    if (!plan || busy || plan.state !== 'pending') return
    setBusy(true); setError('')
    try {
      const result = await api('/git/draft-plans/' + encodeURIComponent(plan.id) + '/approve',
        'POST', { confirmation: plan.confirmation })
      setPlan(current => ({ ...current, ...result }))
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
    {plan && <div className="mt-4 space-y-2 rounded-xl border border-white/15 p-3 text-xs">
      <h5 className="font-semibold">Plano de publicação · {plan.repository}</h5>
      <p>{plan.head} → {plan.base}</p>
      <p className="break-all font-mono text-muted">Origem: {plan.head_sha}<br />Destino: {plan.base_sha}</p>
      <p className="font-semibold">{plan.title}</p>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap">{plan.body || '(Sem descrição)'}</pre>
      <p className="text-muted">Aprovação válida até {new Date(plan.expires_at).toLocaleTimeString('pt-BR')}.</p>
      {plan.state === 'pending' && <button type="button" className={button} disabled={busy} onClick={approve}>Aprovar plano e criar rascunho</button>}
      {plan.state === 'completed' && <p>Revisão criada: <a className="underline" href={plan.result.url} target="_blank" rel="noopener noreferrer">#{plan.result.number}</a>
        {plan.result.requires_review && ' · Confira os commits e o estado no serviço: a resposta não confirmou todo o plano.'}</p>}
      {['uncertain', 'executing'].includes(plan.state) && <p role="status">O resultado remoto precisa ser conferido no serviço antes de criar outro plano. Esta operação não será repetida automaticamente.</p>}
      {['failed', 'expired'].includes(plan.state) && <p role="status">Plano encerrado. Revise as informações e prepare um novo plano.</p>}
    </div>}
  </section>
}
