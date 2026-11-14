import { useEffect, useRef, useState } from 'react'

const NATURAL = 'Eram exatamente três e dezessete da madrugada. Quando ouvi alguém bater na porta. Três batidas. Lentas. Pesadas. Mas havia um problema.'
const SUSPENSE = 'Eram exatamente três e dezessete da madrugada... [pause 700ms] Quando ouvi alguém bater na porta. [pause 500ms] Três batidas. [pause 650ms] Lentas. Pesadas. [pause 900ms] Mas havia um problema.'
const LONG = [
  'Eram exatamente três e dezessete da madrugada quando ouvi alguém bater na porta. Três batidas. Lentas. Pesadas. [pause 700ms] Mas havia um problema: eu morava sozinho, no último apartamento de um prédio quase vazio. E ninguém sabia que eu estava ali.',
  'A princípio, pensei que fosse o vento. Então ouvi um sussurro vindo do corredor. Era uma voz baixa, quase familiar, repetindo meu nome. [pause 500ms] Encostei o ouvido na madeira e perguntei quem estava do outro lado. Nenhuma resposta. Apenas o som de alguém respirando muito perto da fechadura.',
  'Olhei pelo olho mágico. O corredor estava completamente escuro. A lâmpada de emergência, que nunca apagava, havia desaparecido na sombra. Quando me afastei, escutei passos do outro lado. Eles não se afastavam. Pareciam caminhar em círculos, bem diante da porta.',
  'Peguei o celular para ligar para a portaria. Não havia sinal. A tela mostrava uma notificação de mensagem recebida, mas não havia número nem nome. A mensagem dizia: Não abra. [pause 800ms] Eu estava prestes a responder quando percebi outro detalhe. O celular continuava no modo avião desde a noite anterior.',
  'As três batidas recomeçaram, desta vez mais fortes. Meu coração disparou. Corri para a janela e olhei para a rua. Lá embaixo, o porteiro estava parado, imóvel, olhando diretamente para o meu andar. Então levantou a mão e apontou para trás de mim.',
  'Foi nesse instante que ouvi a mesma voz outra vez. Mas agora ela não vinha do corredor. [pause 1s] Ela vinha de dentro do apartamento. Bem atrás da minha cabeça. E sussurrou apenas duas palavras: Estou aqui.',
].join('\n\n')
const PRESETS = [
  { id: 'natural', name: 'Natural', instructions: '' },
  { id: 'suspense', name: 'Suspense (pontuação e pausas)', instructions: '' },
  { id: 'whisper', name: 'Sussurrada (experimental)', instructions: 'whisper' },
]
const cleanTranscript = text => text.replace(/\[pause(?:\s+\d+(?:\.\d+)?(?:ms|s))?\]/gi, ' ').replace(/\s+/g, ' ').trim()
const wordCount = text => cleanTranscript(text).split(/\s+/).filter(Boolean).length

export default function VoiceStudioPanel() {
  const [status, setStatus] = useState(null)
  const [voices, setVoices] = useState([{ id: 'default', name: 'Padrão' }])
  const [voice, setVoice] = useState('default')
  const [script, setScript] = useState(NATURAL)
  const [style, setStyle] = useState('natural')
  const [instructions, setInstructions] = useState('')
  const [speed, setSpeed] = useState(1)
  const [steps, setSteps] = useState(32)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [takes, setTakes] = useState([])
  const [referenceTake, setReferenceTake] = useState('')
  const [referenceFile, setReferenceFile] = useState(null)
  const [profileName, setProfileName] = useState('Narrador principal')
  const [referenceText, setReferenceText] = useState(cleanTranscript(NATURAL))
  const [saving, setSaving] = useState(false)
  const [profileNotice, setProfileNotice] = useState('')
  const objectURLs = useRef([])
  const abortRef = useRef(null)
  const profileSection = useRef(null)

  async function refreshVoices() {
    const response = await fetch('/api/voice-studio/voices', { credentials: 'same-origin' })
    if (!response.ok) throw new Error('Não foi possível carregar os perfis.')
    const data = await response.json()
    if (data.voices?.length) setVoices(data.voices)
    return data.voices || []
  }

  useEffect(() => {
    let mounted = true
    fetch('/api/voice-studio/status', { credentials: 'same-origin' })
      .then(r => r.json())
      .then(data => { if (mounted) setStatus(data) })
      .catch(() => { if (mounted) setStatus({ ready: false }) })
    refreshVoices().catch(() => {})
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
    const began = performance.now()
    try {
      const response = await fetch('/api/voice-studio/speech', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Central-Request': '1' },
        credentials: 'same-origin',
        signal: controller.signal,
        body: JSON.stringify({
          text: script.trim(), model: 'omnivoice', voice, language: 'pt', speed,
          steps, seed: 42,
          instructions: instructions.trim() || PRESETS.find(p => p.id === style)?.instructions || '',
        }),
      })
      if (!response.ok) {
        let details = {}
        try { details = await response.json() } catch {}
        throw new Error(typeof details.detail === 'string' ? details.detail : 'Falha ao gerar áudio.')
      }
      const blob = await response.blob()
      if (!blob.size) throw new Error('O motor retornou um arquivo vazio.')
      const url = URL.createObjectURL(blob)
      objectURLs.current.push(url)
      setTakes(old => [{
        id: Date.now() + '-' + Math.random().toString(36).slice(2),
        blob, url, text: script.trim(), voice, speed, steps, style, duration: null,
        secondsToRender: Math.round((performance.now() - began) / 100) / 10,
        score: null, created: new Date().toLocaleTimeString('pt-BR'),
      }, ...old])
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
    } finally {
      abortRef.current = null
      setBusy(false)
    }
  }

  function selectReference(take) {
    setReferenceTake(take.id)
    setReferenceFile(null)
    setReferenceText(cleanTranscript(take.text))
    setProfileNotice('')
    profileSection.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  async function saveProfile() {
    const take = takes.find(item => item.id === referenceTake)
    const audio = referenceFile || (take ? new File([take.blob], 'referencia.wav', { type: 'audio/wav' }) : null)
    if (!audio) {
      setProfileNotice('Selecione uma amostra gerada ou importe um WAV com 3 a 20 segundos.')
      return
    }
    if (!referenceText.trim() || !profileName.trim()) {
      setProfileNotice('Informe o nome do perfil e a transcrição exata da amostra.')
      return
    }
    setSaving(true)
    setProfileNotice('')
    try {
      const form = new FormData()
      form.append('name', profileName.trim())
      form.append('ref_text', referenceText.trim())
      form.append('ref_audio', audio, 'referencia.wav')
      const response = await fetch('/api/voice-studio/profiles', {
        method: 'POST', headers: { 'X-Central-Request': '1' },
        credentials: 'same-origin', body: form,
      })
      if (!response.ok) {
        let details = {}
        try { details = await response.json() } catch {}
        throw new Error(typeof details.detail === 'string' ? details.detail : 'Falha ao salvar o perfil.')
      }
      const created = await response.json()
      await refreshVoices()
      setVoice(created.id)
      setProfileNotice('Perfil "' + created.name + '" salvo no VoiceStudio e selecionado para as próximas narrações.')
    } catch (e) {
      setProfileNotice(e.message)
    } finally {
      setSaving(false)
    }
  }

  return <div className="mx-auto w-full max-w-5xl px-4 py-8 text-copy sm:px-8">
    <p className="mb-2 text-xs font-bold uppercase tracking-[.2em] text-lilac">Laboratório de voz · Português brasileiro</p>
    <h1 className="text-3xl font-semibold">Voice Studio</h1>
    <p className="mt-2 text-sm text-muted">Compare suspense e ritmo, teste textos longos e preserve a identidade vocal com um perfil de referência.</p>
    <div className="mt-5 flex flex-wrap items-center gap-3 text-sm">
      <span className={status?.ready ? 'text-emerald-300' : 'text-amber-300'}>
        ● {status === null ? 'Consultando motor...' : status.ready ? 'Motor conectado' : 'Motor desconectado'}
      </span>
      <a href="https://github.com/debpalash/VoiceStudio" target="_blank" rel="noopener noreferrer" className="text-lilac underline">VoiceStudio oficial</a>
    </div>
    <section className="mt-6 rounded-2xl border border-white/10 bg-panel p-5">
      <h2 className="mb-2 text-lg font-semibold">1. Expressividade e consistência</h2>
      <p className="mb-3 text-xs text-muted">Use o mesmo perfil em todas as amostras. A versão de suspense adiciona pausas explícitas, e o roteiro longo verifica a estabilidade da narração.</p>
      <div className="mb-4 flex flex-wrap gap-2">
        <button type="button" onClick={() => { setScript(NATURAL); setStyle('natural') }} className="rounded-lg border border-white/15 px-3 py-2 text-xs hover:bg-white/5">Trecho natural</button>
        <button type="button" onClick={() => { setScript(SUSPENSE); setStyle('suspense') }} className="rounded-lg border border-white/15 px-3 py-2 text-xs hover:bg-white/5">Trecho com pausas</button>
        <button type="button" onClick={() => { setScript(LONG); setStyle('suspense') }} className="rounded-lg border border-white/15 px-3 py-2 text-xs hover:bg-white/5">Roteiro longo (1–2 min)</button>
      </div>
      <label htmlFor="voice-script" className="mb-2 block text-sm font-medium">Roteiro</label>
      <textarea id="voice-script" rows={11} maxLength={4096} value={script} onChange={e => setScript(e.target.value)}
        className="w-full resize-y rounded-xl border border-white/10 bg-black/10 p-4 text-sm leading-7 text-copy outline-none focus:border-lilac" />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span>{wordCount(script)} palavras · estimativa {Math.max(1, Math.round(wordCount(script) / 140 * 60))} s (varia com pausas e velocidade)</span>
        <span>{script.length} / 4096 caracteres</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={() => setScript(s => s + ' [pause 500ms] ')} className="rounded-lg border border-white/15 px-3 py-2 text-xs">Inserir pausa 500 ms</button>
        <button type="button" onClick={() => setScript(s => s + ' [pause 1s] ')} className="rounded-lg border border-white/15 px-3 py-2 text-xs">Inserir pausa 1 segundo</button>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <div><label htmlFor="voice-choice" className="mb-2 block text-xs">Perfil de voz</label>
          <select id="voice-choice" value={voice} onChange={e => setVoice(e.target.value)} className="w-full rounded-lg border border-white/10 bg-panel p-3 text-sm">
            {voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select></div>
        <div><label htmlFor="voice-style" className="mb-2 block text-xs">Estilo</label>
          <select id="voice-style" value={style} onChange={e => setStyle(e.target.value)} className="w-full rounded-lg border border-white/10 bg-panel p-3 text-sm">
            {PRESETS.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></div>
        <div><label htmlFor="voice-instructions" className="mb-2 block text-xs">Instrução opcional (OmniVoice aceita tags específicas)</label>
          <input id="voice-instructions" maxLength={700} value={instructions} onChange={e => setInstructions(e.target.value)}
            placeholder="Ex.: whisper" className="w-full rounded-lg border border-white/10 bg-panel p-3 text-sm" />
        </div>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div><label htmlFor="voice-speed" className="mb-2 block text-sm">Velocidade: {speed.toFixed(2)}×</label>
          <input id="voice-speed" type="range" min=".7" max="1.3" step=".05" value={speed} onChange={e => setSpeed(Number(e.target.value))} className="w-full accent-violet-400" /></div>
        <div><label htmlFor="voice-steps" className="mb-2 block text-sm">Refinamento: {steps} passos</label>
          <input id="voice-steps" type="range" min="8" max="64" step="8" value={steps} onChange={e => setSteps(Number(e.target.value))} className="w-full accent-violet-400" /></div>
      </div>
      {error && <p role="alert" className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/5 p-3 text-sm text-rose-300">{error}</p>}
      <button type="button" disabled={busy || !script.trim() || !status?.ready} onClick={generate}
        className="mt-4 w-full rounded-xl bg-violet-500 px-5 py-3 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">
        {busy ? 'Gerando áudio — o texto longo pode demorar...' : 'Gerar e comparar amostra'}
      </button>
      {busy && <button type="button" onClick={() => abortRef.current?.abort()} className="mt-2 text-xs text-muted underline">Cancelar espera (não interrompe necessariamente a GPU)</button>}
      <p className="mt-2 text-xs text-muted">OmniVoice não tem controle gradual de emoção. Pausas e pontuação são os controles mais previsíveis; teste o sussurro separadamente.</p>
    </section>
    <section className="mt-5 rounded-2xl border border-white/10 bg-panel p-5">
      <h2 className="text-lg font-semibold">2. Compare as amostras</h2>
      <p className="mt-1 text-xs text-muted">Atribua uma nota à naturalidade (1 a 5) e compare duração, tempo de geração e ritmo. Os resultados desta lista duram apenas nesta aba.</p>
      {!takes.length ? <p className="mt-5 text-sm text-muted">Gere o primeiro trecho para começar.</p> :
        <div className="mt-4 grid gap-4">
          {takes.map((t, index) => <article key={t.id} className="rounded-xl border border-white/10 p-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><b className="text-sm">Amostra {takes.length - index}</b><small className="text-muted">{t.created} · {t.speed.toFixed(2)}× · {t.steps} passos · voz: {t.voice}</small></div>
            <audio controls preload="metadata" src={t.url} className="w-full" onLoadedMetadata={e => {
              const duration = e.currentTarget.duration
              if (Number.isFinite(duration)) setTakes(old => old.map(item => item.id === t.id ? { ...item, duration } : item))
            }}/>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
              <span>Render: {t.secondsToRender}s</span>
              {t.duration !== null && <span>Áudio: {t.duration.toFixed(1)}s</span>}
              <label>Naturalidade
                <select aria-label="Nota de naturalidade" value={t.score ?? ''} onChange={e => setTakes(old => old.map(item => item.id === t.id ? { ...item, score: Number(e.target.value) } : item))}
                  className="ml-2 rounded-md border border-white/15 bg-panel p-1 text-xs">
                  <option value="" disabled>Avaliar</option>
                  {[1, 2, 3, 4, 5].map(v => <option key={v} value={v}>{v}/5</option>)}
                </select>
              </label>
              <a href={t.url} download={'central-voice-' + t.id + '.wav'} className="text-lilac underline">Salvar WAV</a>
              <button type="button" onClick={() => selectReference(t)} className="text-lilac underline">Usar como referência de voz</button>
            </div>
          </article>)}
        </div>}
    </section>
    <section ref={profileSection} className="mt-5 rounded-2xl border border-white/10 bg-panel p-5">
      <h2 className="text-lg font-semibold">3. Salvar identidade vocal</h2>
      <p className="mt-1 text-sm text-muted">Escolha uma amostra curta com 3 a 20 segundos de fala clara, ou importe o WAV que já aprovou. O VoiceStudio salva a gravação como referência permanente; a Central passa a listar esse perfil de voz.</p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div><label htmlFor="profile-name" className="mb-2 block text-xs">Nome do perfil</label>
          <input id="profile-name" value={profileName} maxLength={80} onChange={e => setProfileName(e.target.value)}
            className="w-full rounded-lg border border-white/10 bg-panel p-3 text-sm" /></div>
        <div><label htmlFor="profile-ref" className="mb-2 block text-xs">Amostra de referência gerada</label>
          <select id="profile-ref" value={referenceTake} onChange={e => {
            const t = takes.find(item => item.id === e.target.value)
            setReferenceTake(e.target.value)
            if (t) { setReferenceText(cleanTranscript(t.text)); setReferenceFile(null) }
          }} className="w-full rounded-lg border border-white/10 bg-panel p-3 text-sm">
            <option value="">Importar WAV, ou escolher uma amostra abaixo</option>
            {takes.map((t, index) => <option key={t.id} value={t.id}>{'Amostra ' + (takes.length - index) + (t.duration !== null ? ' (' + t.duration.toFixed(1) + 's)' : '')}</option>)}
          </select></div>
      </div>
      <div className="mt-3"><label htmlFor="profile-file" className="mb-2 block text-xs">Ou importar um WAV existente (substitui a amostra selecionada)</label>
        <input id="profile-file" type="file" accept=".wav,audio/wav" onChange={e => { setReferenceFile(e.target.files?.[0] || null); setProfileNotice('') }}
          className="block w-full text-sm text-muted" /></div>
      <div className="mt-3"><label htmlFor="profile-transcript" className="mb-2 block text-xs">Transcrição exata do que é falado na referência</label>
        <textarea id="profile-transcript" rows={3} maxLength={1000} value={referenceText} onChange={e => setReferenceText(e.target.value)}
          className="w-full rounded-lg border border-white/10 bg-black/10 p-3 text-sm" /></div>
      {profileNotice && <p role="status" className="mt-3 rounded-lg border border-white/10 p-3 text-sm">{profileNotice}</p>}
      <button type="button" disabled={saving || !status?.ready} onClick={saveProfile}
        className="mt-4 rounded-xl bg-violet-500 px-5 py-3 text-sm font-semibold text-white disabled:opacity-40">
        {saving ? 'Salvando perfil...' : 'Salvar perfil no VoiceStudio'}
      </button>
      <p className="mt-3 text-xs text-muted">Use somente uma voz que você tem direito de reproduzir. O perfil fica armazenado no VoiceStudio local, não no repositório público ou no banco da Central. A mesma instância do VoiceStudio pode compartilhar os perfis entre usuários da Central.</p>
    </section>
  </div>
}
