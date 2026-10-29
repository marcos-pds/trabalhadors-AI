import { useEffect, useState } from 'react'

const action = 'rounded-lg border border-white/15 px-2.5 py-1.5 text-[11px] text-copy hover:bg-white/10 disabled:opacity-40'

export default function WorktreeReviewPanel({ api, runId, steps = [], active }) {
  const [data, setData] = useState(null)
  const [stepId, setStepId] = useState('')
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let mounted = true
    setData(null); setPlan(null); setStepId(''); setError(''); setNotice('')
    if (runId) api('/runs/' + encodeURIComponent(runId) + '/worktrees')
      .then(value => { if (mounted) setData(value) })
      .catch(err => { if (mounted) setError(err.message) })
    return () => { mounted = false }
  }, [api, runId])

  if (!runId || (!data?.enabled && !error)) return null
  const available = steps.filter(step => step.kind === 'agent')
  const selected = stepId || available[0]?.id || ''
  const registered = (data?.worktrees || []).find(item => item.step_id === selected)

  async function operation(name) {
    if (!selected || busy) return
    if (name === 'apply' && (!plan?.confirmation || !window.confirm(
      'Aplicar os arquivos revisados ao projeto principal? Isso altera os arquivos reais. Depois será obrigatório executar os testes novamente.'
    ))) return
    setBusy(true); setError(''); setNotice('')
    const root = '/runs/' + encodeURIComponent(runId)
    try {
      if (name === 'prepare') {
        await api(root + '/steps/' + encodeURIComponent(selected) + '/worktree', 'POST', {})
        setPlan(null)
        setNotice('Cópia Git preparada. Edite essa cópia no VS Code e depois gere a revisão.')
      } else if (name === 'review') {
        const proposed = await api(root + '/steps/' + encodeURIComponent(selected) + '/worktree-review', 'POST', {})
        setPlan(proposed)
      } else if (name === 'apply') {
        const result = await api(root + '/worktree-reviews/' + encodeURIComponent(plan.plan_id) + '/apply',
          'POST', { confirmation: plan.confirmation })
        setPlan(null)
        setNotice('Arquivos integrados: ' + result.files.join(', ') +
          '. Entrega ainda NÃO validada: execute build, testes e QA novamente.')
      }
      setData(await api(root + '/worktrees'))
    } catch (err) {
      setError(err.message)
      if (name === 'apply') setPlan(null) // A lost response might mean approval was already used.
    } finally { setBusy(false) }
  }

  return <section aria-label="Revisão de worktrees" className="mt-3 rounded-xl border border-violet-400/20 p-3 text-xs">
    <h3 className="font-semibold text-violet-200">Worktrees Git · revisão assistida</h3>
    <p className="mt-1 leading-5 text-muted">Modo experimental. A Central não direciona os agentes automaticamente a esses checkouts. O operador controla a integração.</p>
    <label className="mt-3 block text-[11px] text-muted">Etapa
      <select className="mt-1 w-full rounded-lg border border-white/15 bg-[#151519] px-2 py-2 text-copy"
        value={selected} onChange={e => { setStepId(e.target.value); setPlan(null); setError(''); setNotice('') }}>
        {available.map(step => <option key={step.id} value={step.id}>{step.name} · {step.status}</option>)}
      </select>
    </label>
    {registered?.path && <p className="mt-2 break-all font-mono text-[10px] text-muted" title="Local do checkout">{registered.path}</p>}
    {registered?.blocked && <p className="mt-2 text-amber-200">Worktree não está acessível com as permissões atuais.</p>}
    {registered?.changes?.length > 0 && <p className="mt-2 break-words text-muted">Alterações: {registered.changes.join(' · ')}</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" className={action} disabled={!selected || active || busy}
        onClick={() => operation('prepare')}>Preparar cópia</button>
      <button type="button" className={action} disabled={!registered?.path || active || busy || !!registered?.blocked}
        onClick={() => operation('review')}>Revisar diferenças</button>
    </div>
    {plan && <section className="mt-3 space-y-2 rounded-lg border border-white/15 bg-black/15 p-3">
      <p className="font-semibold">Arquivos para integrar ({plan.files.length})</p>
      {plan.files.map(item => <details key={item.path} className="border-t border-white/10 pt-2">
        <summary className="cursor-pointer break-all font-mono text-[11px]">{item.path} · {item.bytes} bytes</summary>
        <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-all text-[10px] text-muted">{item.diff_preview}</pre>
        {item.diff_truncated && <p className="text-amber-200">Diferença truncada: revise também no VS Code.</p>}
      </details>)}
      <p className="text-amber-200">Confira todos os diffs. A aprovação é de uso único e não faz commit ou push.</p>
      <button type="button" className={action} disabled={busy || active}
        onClick={() => operation('apply')}>Aprovar e integrar arquivos</button>
    </section>}
    {notice && <p role="status" className="mt-3 break-words text-emerald-200">{notice}</p>}
    {error && <p role="alert" className="mt-3 break-words text-rose-200">{error}</p>}
  </section>
}
