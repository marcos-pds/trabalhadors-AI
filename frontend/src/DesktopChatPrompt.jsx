import { useEffect, useRef, useState } from 'react'
import { LiquidGlassUnderlay } from './LiquidGlassUI.jsx'
import DesktopGlassSurface from './DesktopGlassSurface.jsx'

// Compact desktop-only composer. Reuses the same prompt, mode, attachments,
// and send actions as the full ChatPage; it does not create a second chat.
export default function DesktopChatPrompt({
  prompt, setPrompt, files, setFiles, mode, setMode, onSend, onCommand, onError,
}) {
  const fieldRef = useRef(null)
  const uploadRef = useRef(null)
  const sendLock = useRef(false)
  const recognitionRef = useRef(null)
  const [sending, setSending] = useState(false)
  const [listening, setListening] = useState(false)
  const recognitionAvailable = typeof window !== 'undefined' &&
    Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)

  useEffect(() => {
    fieldRef.current?.focus()
    return () => {
      recognitionRef.current?.stop()
      recognitionRef.current = null
    }
  }, [])

  async function attach(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    try {
      const response = await fetch('/api/uploads/text', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'x-central-request': '1' }, body: form,
      })
      if (!response.ok) throw new Error('Não foi possível anexar o arquivo.')
      const uploaded = await response.json()
      setFiles(old => [...old, uploaded])
    } catch (error) {
      onError(error.message || 'Falha ao anexar arquivo.')
    }
  }

  async function submit() {
    if (sendLock.current || !prompt.trim()) return
    sendLock.current = true
    setSending(true)
    try {
      if (prompt.trim().startsWith('/')) await onCommand(prompt.trim())
      else await onSend()
    } catch (error) {
      onError(error.message || 'Falha ao enviar a mensagem.')
    } finally {
      sendLock.current = false
      setSending(false)
      fieldRef.current?.focus()
    }
  }

  function dictate() {
    if (listening) {
      recognitionRef.current?.stop()
      return
    }
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!Recognition) return
    const recognition = new Recognition()
    recognitionRef.current = recognition
    recognition.lang = 'pt-BR'
    recognition.interimResults = false
    recognition.continuous = false
    recognition.onresult = event => {
      const said = [...event.results].map(item => item[0]?.transcript || '').join(' ').trim()
      if (said) setPrompt(previous => [previous.trim(), said].filter(Boolean).join(' '))
    }
    recognition.onerror = event => {
      if (event.error !== 'aborted') onError('Ditado indisponível. Verifique a permissão do microfone.')
      setListening(false)
    }
    recognition.onend = () => { setListening(false); recognitionRef.current = null }
    try { recognition.start(); setListening(true) }
    catch { onError('Não foi possível iniciar o microfone.') }
  }

  return <section className="desktop-prompt-only" aria-label="Nova mensagem para a Central">
    <div className="desktop-quick-composer">
      <DesktopGlassSurface className="desktop-quick-rdev-glass"/>
      <LiquidGlassUnderlay className="desktop-quick-refraction" radius={30}
        strength={0.09} depth={10} edgeHighlight={0.38} glow={0.16}/>
      <form className="desktop-quick-input-row" onSubmit={event => { event.preventDefault(); submit() }}>
        <input ref={uploadRef} type="file" className="hidden"
          accept=".txt,.md,.csv,.json,.py,.ts,.tsx,.jsx,.js,.html,.css,.sql,.yaml,.yml,.xml"
          onChange={attach}/>
        <button type="button" className="desktop-quick-attach" onClick={() => uploadRef.current?.click()}
          disabled={sending} title="Anexar arquivo" aria-label="Anexar arquivo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
        </button>
        <textarea ref={fieldRef} value={prompt} rows={1} disabled={sending}
          className="desktop-quick-field" aria-label="Digite seu pedido"
          placeholder={sending ? 'Enviando…' : 'Pergunte à Central'}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}/>
        <label className="desktop-quick-mode-label" title="Modo de execução">
          <span className="sr-only">Modo de execução</span>
          <select aria-label="Modo de execução" value={mode}
            onChange={e => setMode(e.target.value)} disabled={sending}>
            <option value="auto">Auto</option>
            <option value="team">Equipe</option>
            <option value="manual">Individual</option>
          </select>
        </label>
        <button type="button" className={'desktop-quick-microphone' + (listening ? ' is-listening' : '')}
          onClick={dictate} disabled={!recognitionAvailable || sending}
          title={recognitionAvailable ? 'Ditar mensagem' : 'Ditado não disponível nesta instalação'}
          aria-label={listening ? 'Parar ditado' : 'Ditar mensagem'}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="3" width="6" height="12" rx="3"/><path d="M6 11a6 6 0 0 0 12 0M12 17v4m-4 0h8"/>
          </svg>
        </button>
        <button type="submit" className="desktop-quick-send" disabled={!prompt.trim() || sending}
          title="Enviar mensagem" aria-label="Enviar mensagem">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round">
            <path d="M4 12l15-7-4 14-3.5-6.5L4 12Z"/><path d="m11.5 12.5 7.5-7.5"/>
          </svg>
        </button>
      </form>
    </div>
    {files.length > 0 && <p className="desktop-quick-files" role="status">{files.length} arquivo(s) anexado(s)</p>}
  </section>
}
