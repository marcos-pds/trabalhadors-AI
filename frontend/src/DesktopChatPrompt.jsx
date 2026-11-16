import { useEffect, useRef, useState } from 'react'
import DesktopGlassSurface from './DesktopGlassSurface.jsx'

// Compact desktop-only composer. Reuses the same prompt, mode, attachments,
// and send actions as the full ChatPage; it does not create a second chat.
export default function DesktopChatPrompt({
  prompt, setPrompt, files, setFiles, mode, setMode, selectedAgent, setSelectedAgent, agents = [],
  onSend, onCommand, onError, onClose, onUpload, embedded = false,
}) {
  const fieldRef = useRef(null)
  const uploadRef = useRef(null)
  const sendLock = useRef(false)
  const recognitionRef = useRef(null)
  const modePickerRef = useRef(null)
  const [showModes, setShowModes] = useState(false)
  const [sending, setSending] = useState(false)
  const [listening, setListening] = useState(false)
  const recognitionAvailable = typeof window !== 'undefined' &&
    Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)

  // The automatic mode is the default, but its label and outline are not
  // rendered on the compact bar. A small settings icon opens other choices.
  useEffect(() => {
    if (!showModes) return undefined
    const closeOnOutside = event => {
      if (!modePickerRef.current?.contains(event.target)) setShowModes(false)
    }
    const closeOnEscape = event => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        setShowModes(false)
      }
    }
    document.addEventListener('pointerdown', closeOnOutside)
    document.addEventListener('keydown', closeOnEscape, true)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutside)
      document.removeEventListener('keydown', closeOnEscape, true)
    }
  }, [showModes])

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
    try {
      if (typeof onUpload !== 'function') throw new Error('Anexos indisponíveis nesta janela.')
      const uploaded = await onUpload(file)
      setFiles(old => [...old, uploaded])
    } catch (error) {
      onError(error.message || 'Falha ao anexar arquivo.')
    }
  }

  async function submit() {
    if (sendLock.current || !prompt.trim()) return
    if (mode === 'manual' && !selectedAgent) {
      onError('Selecione um trabalhador antes de enviar.')
      return
    }
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

  return <section className={'desktop-prompt-only' + (embedded ? ' is-embedded' : '')} aria-label="Nova mensagem para a Central">
    <div className="desktop-quick-composer">
      <DesktopGlassSurface className="desktop-quick-rdev-glass"/>
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
          placeholder={sending ? 'Enviando…' : embedded ? 'Escreva sua próxima mensagem…' : 'O que deseja fazer?'}
          onChange={e => setPrompt(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (showModes) setShowModes(false); else onClose?.(); return }
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}/>
        <div ref={modePickerRef} className="desktop-quick-mode-picker">
          <button type="button" className={'desktop-quick-mode-trigger' + (mode !== 'auto' ? ' has-selection' : '')}
            aria-label={mode === 'auto' ? 'Escolher modo de execução (automático)' : 'Modo de execução: ' + (mode === 'team' ? 'Equipe' : 'Individual')}
            title="Modo de execução"
            aria-expanded={showModes} aria-controls="desktop-quick-mode-options"
            disabled={sending} onClick={() => setShowModes(open => !open)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2.5" fill="currentColor" stroke="none"/>
              <circle cx="16" cy="17" r="2.5" fill="currentColor" stroke="none"/>
            </svg>
            {mode !== 'auto' && <span className="desktop-quick-mode-active">{mode === 'team' ? 'Equipe' : 'Individual'}</span>}
          </button>
          {showModes && <div id="desktop-quick-mode-options" className="desktop-quick-mode-options"
            role="group" aria-label="Escolher modo de execução">
            {[['auto','Auto'], ['team','Equipe'], ['manual','Individual']].map(([value,label]) =>
              <button key={value} type="button" aria-pressed={mode === value}
                onClick={() => { setMode(value); setShowModes(false); fieldRef.current?.focus() }}>
                {label}
              </button>)}
          </div>}
        </div>
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
    {mode === 'manual' && <label className="desktop-quick-worker">
      Trabalhador
      <select aria-label="Trabalhador preferido" value={selectedAgent || ''}
        onChange={e => setSelectedAgent(e.target.value)}>
        <option value="">Selecionar trabalhador</option>
        {agents.filter(agent => agent.enabled).map(agent =>
          <option key={agent.id} value={agent.id}>{agent.name}</option>)}
      </select>
    </label>}
    {files.length > 0 && <p className="desktop-quick-files" role="status">{files.length} arquivo(s) anexado(s)</p>}
  </section>
}
