import { useEffect, useRef, useState } from 'react'

const SAMPLE = 'Eram exatamente três e dezessete da madrugada. Quando ouvi alguém bater na porta. Três batidas. Lentas. Pesadas. Mas havia um problema.'
const PRESETS = [
  { id: 'original', name: 'Natural', instructions: '' },
  { id: 'suspense', name: 'Suspense', instructions: 'Speak with a mysterious, intimate storytelling delivery.' },
  { id: 'warm', name: 'Acolhedora', instructions: 'Speak in a warm, gentle and reassuring tone.' },
]

export default function VoiceStudioPanel() {
  const [status, setStatus] = useState(null)
  const [voices, setVoices] = useState([{ id: 'default', name: 'Padrão' }])
  const [voice, setVoice] = useState('default')
  const [script, setScript] = useState(SAMPLE)
  const [style, setStyle] = useState('original')
  const [instructions, setInstructions] = useState('')
  const [speed, setSpeed] = useState(1)
  const [steps, setSteps] = useState(32)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [takes, setTakes] = useState([])
  const objectURLs = useRef([])
  const abortRef = useRef(null)

  useEffect(() => {
    let mounted = true
    Promise.allSettled([
      fetch('/api/voice-studio/status', { credentials: 'same-origin' }).then(r => r.json()),
      fetch('/api/voice-studio/voices', { credentials: 'same-origin' }).then(r => r.ok ? r.json() : { voices: [] }),
    ]).then(([a, b]) => {
      if (!mounted) return
      setStatus(a.status === 'fulfilled' ? a.value : { ready: false })
      if (b.status === 'fulfilled' && b.value.voices?.length) setVoices(b.value.voices)
    })
    return () => {
      mounted = false
      abortRef.current?.abort()
      objectURLs.current.forEach(url => URL.revokeObjectURL(url))
      objectURLs.current = []
    }
  }, [])

  async function generate() {
    if (!script.trim() || busy) return
    setBusy(true)
    setError('')
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const response = await fetch('/api/voice-studio/speech', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Central-Request': '1' },
        credentials: 'same-origin',
        signal: controller.signal,
        body: JSON.stringify({
          text: script.trim(), model: 'omnivoice', voice, language: 'pt', speed,
          steps, instructions: (instructions.trim() || PRESETS.find(p => p.id === style)?.instructions || ''),
        }),
      })
      if (!response.ok) {
        let details = {}
        try { details = await response.json() } catch {}
        throw new Error(details.detail || 'Falha ao gerar áudio.')
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      objectURLs.current.push(url)
      setTakes(old => [{
        id: Date.now() + '-' + Math.random().toString(36).slice(2),
        url, voice, speed, steps, style,
        name: 'Amostra ' + (old.length + 1), created: new Date().toLocaleTimeString('pt-BR'),
      }, ...old])
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
    } finally {
      abortRef.current = null
      setBusy(false)
    }
  }

  return <div className="mx-auto w-full max-w-5xl px-4 py-8 text-copy sm:px-8">
    <p className="mb-2 text-xs font-bold uppercase tracking-[.2em] text-lilac">Laboratório de voz</p>
    <h1 className="text-3xl font-semibold">Voice Studio</h1>
    <p className="mt-2 text-sm text-muted">Gere e compare narrações em português brasileiro usando o VoiceStudio local.</p>
    <div className="mt-5 flex flex-wrap items-center gap-3 text-sm">
      <span className={status?.ready ? 'text-emerald-300' : 'text-amber-300'}>
        ● {status === null ? 'Consultando motor...' : status.ready ? 'Motor conectado' : 'Motor desconectado'}
      </span>
      <a href="https://github.com/debpalash/VoiceStudio" target="_blank" rel="noopener noreferrer" className="text-lilac underline">Documentação do motor</a>
    </div>
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(250px,1fr)]">
      <section className="rounded-2xl border border-white/10 bg-panel p-5">
        <label htmlFor="voice-script" className="mb-2 block text-sm font-medium">Texto da narração</label>
        <textarea id="voice-script" rows={12} maxLength={4096} value={script} onChange={e => setScript(e.target.value)}
          className="w-full resize-y rounded-xl border border-white/10 bg-black/10 p-4 text-sm leading-7 text-copy outline-none focus:border-lilac" />
        <p className="mt-2 text-right text-xs text-muted">{script.length} / 4096 caracteres</p>
        {error && <p role="alert" className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/5 p-3 text-sm text-rose-300">{error}</p>}
        <button type="button" disabled={busy || !script.trim() || !status?.ready} onClick={generate}
          className="mt-4 w-full rounded-xl bg-violet-500 px-5 py-3 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">
          {busy ? 'Gerando áudio...' : 'Gerar amostra de voz'}
        </button>
        {busy && <button type="button" onClick={() => abortRef.current?.abort()} className="mt-2 text-xs text-muted underline">Cancelar espera</button>}
      </section>
      <section className="space-y-5 rounded-2xl border border-white/10 bg-panel p-5">
        <h2 className="text-lg font-semibold">Configurações</h2>
        <div><label htmlFor="voice-choice" className="mb-2 block text-sm">Perfil de voz</label>
          <select id="voice-choice" value={voice} onChange={e => setVoice(e.target.value)} className="w-full rounded-lg border border-white/10 bg-panel p-3 text-sm">
            {voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select></div>
        <div><label htmlFor="voice-style" className="mb-2 block text-sm">Estilo</label>
          <select id="voice-style" value={style} onChange={e => setStyle(e.target.value)} className="w-full rounded-lg border border-white/10 bg-panel p-3 text-sm">
            {PRESETS.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></div>
        <div><label htmlFor="voice-instructions" className="mb-2 block text-sm">Instruções opcionais de interpretação</label>
          <textarea id="voice-instructions" rows={3} maxLength={700} value={instructions} onChange={e => setInstructions(e.target.value)}
            placeholder="Ex.: narração íntima, pausas dramáticas..." className="w-full rounded-lg border border-white/10 bg-black/10 p-3 text-sm" />
          <p className="mt-1 text-xs text-muted">A interpretação depende das capacidades do motor escolhido.</p></div>
        <div><label htmlFor="voice-speed" className="mb-2 block text-sm">Velocidade: {speed.toFixed(2)}×</label>
          <input id="voice-speed" type="range" min=".7" max="1.3" step=".05" value={speed} onChange={e => setSpeed(Number(e.target.value))} className="w-full accent-violet-400" /></div>
        <div><label htmlFor="voice-steps" className="mb-2 block text-sm">Refinamento: {steps} passos</label>
          <input id="voice-steps" type="range" min="8" max="64" step="8" value={steps} onChange={e => setSteps(Number(e.target.value))} className="w-full accent-violet-400" />
          <p className="mt-1 text-xs text-muted">32 passos é um bom ponto inicial; mais passos podem aumentar o tempo de geração.</p></div>
      </section>
    </div>
    <section className="mt-6 rounded-2xl border border-white/10 bg-panel p-5">
      <h2 className="text-lg font-semibold">Comparação de amostras</h2>
      <p className="mt-1 text-xs text-muted">As amostras são temporárias nesta sessão. Salve o WAV para conservar cada versão.</p>
      {!takes.length ? <p className="mt-5 text-sm text-muted">Gere a primeira amostra para começar a comparar.</p> : <div className="mt-4 grid gap-4">
        {takes.map(t => <article key={t.id} className="rounded-xl border border-white/10 p-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><b className="text-sm">{t.name}</b><small className="text-muted">{t.created} · {t.speed}× · {t.steps} passos · {t.voice}</small></div>
          <audio controls preload="metadata" src={t.url} className="w-full" />
          <a href={t.url} download={'central-voice-' + t.id + '.wav'} className="mt-2 inline-block text-sm text-lilac underline">Salvar WAV</a>
        </article>)}
      </div>}
    </section>
  </div>
}
