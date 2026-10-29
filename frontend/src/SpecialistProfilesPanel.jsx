import { useEffect, useState } from 'react'

export default function SpecialistProfilesPanel({ api, onChanged }) {
  const [profiles, setProfiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    let active = true
    api('/agents/specialist-pack').then(result => {
      if (active) setProfiles(result.profiles)
    }).catch(error => { if (active) setMessage(error.message) })
    return () => { active = false }
  }, [api])
  async function install() {
    setBusy(true); setMessage('')
    try {
      const result = await api('/agents/specialist-pack', 'POST', {})
      await onChanged?.()
      setProfiles((await api('/agents/specialist-pack')).profiles)
      setMessage(result.created_ids.length + ' especialistas adicionados.')
    } catch (error) { setMessage(error.message) }
    finally { setBusy(false) }
  }
  return <section aria-label="Especialistas adicionais" className="mb-5 rounded-2xl border border-white/10 bg-panel p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-sm font-semibold">Especialistas adicionais</h2>
        <p className="mt-1 text-xs text-muted">{profiles.length ? profiles.map(profile => profile.name).join(' · ') : 'Todos os perfis deste pacote já estão disponíveis.'}</p></div>
      <button type="button" disabled={busy || !profiles.length} onClick={install} className="rounded-xl border border-lilac/30 px-4 py-2 text-xs disabled:opacity-40">{busy ? 'Adicionando…' : 'Adicionar especialistas'}</button>
    </div>
    <p className="mt-2 text-[11px] text-muted">Os novos perfis herdam a seleção de modelos e as permissões da Central. Agentes existentes são mantidos.</p>
    {message && <p role="status" className="mt-2 text-xs">{message}</p>}
  </section>
}
