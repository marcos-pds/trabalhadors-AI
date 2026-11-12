import { useEffect, useState } from 'react'

function gib(value) {
  if (!Number.isFinite(value) || value < 0) return '—'
  return (value / 1024).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' GB'
}

function Meter({ title, detail, available, total }) {
  const known = Number.isFinite(available) && Number.isFinite(total) && total > 0
  const used = known ? Math.min(100, Math.max(0, ((total - available) / total) * 100)) : 0
  return <article className="rounded-xl border border-white/10 p-3" aria-label={title}>
    <p className="text-xs font-semibold">{title}</p>
    <p className="mt-1 text-[11px] text-muted">{detail}</p>
    <p className="mt-3 text-sm">{known ? `${gib(available)} livres de ${gib(total)}` : 'Medição indisponível'}</p>
    <div role="progressbar" aria-label={`Uso de ${title}`}
      aria-valuenow={known ? Math.round(used) : undefined} aria-valuemin={0} aria-valuemax={100}
      className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
      {known && <div className="h-full rounded-full bg-violet-400" style={{ width: `${used}%` }}/>}
    </div>
  </article>
}

export default function ResourceMonitorPanel({ api }) {
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const result = await api('/system/resources')
        if (active) { setSnapshot(result); setError('') }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : 'Falha ao consultar recursos.')
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load()
    }, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [api, refresh])

  const devices = snapshot?.gpu?.status === 'available' ? snapshot.gpu.devices : []
  const reserved = snapshot?.reservations
  return <section className="mx-auto w-full max-w-[1440px] px-8 pb-8 max-sm:px-4" aria-label="Recursos locais da IA">
    <div className="rounded-2xl border border-white/10 bg-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Recursos locais · RAM, VRAM e SSD</h2>
          <p className="mt-1 text-xs text-muted">Leitura do computador que executa a Central, não do navegador.</p>
        </div>
        <button type="button" disabled={loading} onClick={() => { setLoading(true); setRefresh(value => value + 1) }}
          className="rounded-lg border border-white/15 px-3 py-2 text-xs disabled:opacity-50">Atualizar medições</button>
      </div>
      {error && <p role="alert" className="mt-3 text-xs text-rose-300">Não foi possível atualizar: {error}</p>}
      {loading && !snapshot && <p role="status" className="mt-3 text-xs text-muted">Consultando sensores locais…</p>}
      {snapshot && <>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <Meter title="RAM" detail="Memória física disponível"
            available={snapshot.ram?.available_mib} total={snapshot.ram?.total_mib}/>
          <Meter title="SSD / volume de dados" detail="Espaço livre na unidade que guarda os dados da Central"
            available={snapshot.disk?.available_mib} total={snapshot.disk?.total_mib}/>
          {devices.length ? devices.map(device => <Meter key={device.index}
            title={`GPU ${device.index}: ${device.name}`} detail="VRAM reportada pelo driver NVIDIA"
            available={device.free_mib} total={device.total_mib}/>) :
            <Meter title="GPU / VRAM" detail="NVIDIA-SMI indisponível; não significa VRAM zero."
              available={undefined} total={undefined}/>}
        </div>
        <p className="mt-3 text-[11px] text-muted">
          {reserved ? `Reserva cooperativa no processo: ${reserved.reserved.gpu_slots} de ${reserved.limits.gpu_slots} slot(s) de GPU; ${reserved.waiting} pedido(s) aguardando.` : 'Reservas indisponíveis.'}
          {' '}As reservas são estimativas internas; a medição de VRAM também inclui outros programas.
        </p>
        <p className="mt-1 text-[10px] text-muted">
          Medição: {new Date(snapshot.sampled_at).toLocaleString('pt-BR')}. Não há descarregamento automático de modelos nem controle de processos externos.
        </p>
      </>}
    </div>
  </section>
}
