import { useEffect, useRef, useState } from 'react'
import { pauseLimitKey } from './pauseLimit.mjs'

export default function PauseLimitPrompt({ api, runId, onResume }) {
  const [pause, setPause] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const seen = useRef(null)
  const lock = useRef(false)
  const dialog = useRef(null)
  useEffect(() => {
    let mounted = true, inFlight = false, timer
    const poll = async () => {
      if (inFlight) return
      inFlight = true
      try {
        const result = await api('/runs/' + encodeURIComponent(runId) + '/activity')
        if (!mounted) return
        const key = pauseLimitKey(result)
        if (key && key !== seen.current) {
          seen.current = key
          setPause(result); setError(''); setOpen(true)
        } else if (!key) {
          setPause(null); setOpen(false)
        }
        if (['completed','cancelled','failed'].includes(result.status)) clearInterval(timer)
      } catch { /* Activity errors do not imply a checkpoint pause. */ }
      finally { inFlight = false }
    }
    timer = setInterval(poll, 3000)
    poll()
    return () => { mounted = false; clearInterval(timer) }
  }, [api, runId])
  useEffect(() => { if (open) dialog.current?.focus() }, [open])
  async function resume() {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try { await onResume(runId); setOpen(false); setPause(null) }
    catch (e) { setError(e.message) }
    finally { lock.current = false; setBusy(false) }
  }
  if (!pause) return null
  if (!open) return <button type="button" onClick={() => setOpen(true)} className="fixed bottom-5 right-5 z-40 rounded-xl border border-violet-300/25 bg-[#252132] px-4 py-2 text-xs text-violet-100 shadow-lg">↻ Continuar execução pausada</button>
  const worker = pause.steps?.find(step => step.status === 'paused_limit')
  return <div className="fixed inset-0 z-[70] grid place-items-center bg-black/65 p-4 backdrop-blur-sm">
    <section ref={dialog} tabIndex={-1} role="alertdialog" aria-modal="true" aria-labelledby="pause-limit-title" aria-describedby="pause-limit-description" className="w-full max-w-md rounded-2xl border border-violet-300/20 bg-[#202024] p-6 text-copy shadow-2xl outline-none"
      onKeyDown={event => {
        if (event.key === 'Escape' && !busy) { event.preventDefault(); setOpen(false) }
        if (event.key === 'Tab') {
          const buttons = [...event.currentTarget.querySelectorAll('button:not(:disabled)')]
          if (!buttons.length) { event.preventDefault(); return }
          const first = buttons[0], last = buttons.at(-1)
          if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus() }
          else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { event.preventDefault(); first.focus() }
        }
      }}>
      <span aria-hidden="true" className="text-2xl text-violet-300">↻</span>
      <h2 id="pause-limit-title" className="mt-3 text-lg font-semibold">Continuar a execução?</h2>
      <p id="pause-limit-description" className="mt-2 text-sm leading-6 text-muted">O trabalhador atingiu o limite de ciclos desta rodada. Seu progresso foi salvo. Você pode continuar do checkpoint, preservando as etapas já concluídas.</p>
      {worker && <p className="mt-3 rounded-lg bg-white/[.035] px-3 py-2 text-xs text-violet-200">{worker.name} · pausado por limite</p>}
      {error && <p role="alert" className="mt-3 text-xs text-amber-200">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" disabled={busy} onClick={() => setOpen(false)} className="rounded-xl border border-white/15 px-4 py-2.5 text-xs text-muted hover:bg-white/5 disabled:opacity-50">Agora não</button>
        <button type="button" disabled={busy} onClick={resume} className="rounded-xl bg-violet-500 px-4 py-2.5 text-xs font-semibold text-white hover:bg-violet-400 disabled:opacity-50">{busy ? 'Retomando…' : 'Continuar execução'}</button>
      </div>
    </section>
  </div>
}
