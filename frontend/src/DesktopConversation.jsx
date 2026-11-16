import { useEffect, useRef } from 'react'
import DesktopChatPrompt from './DesktopChatPrompt.jsx'

// The native conversation is its own screen, not the legacy web ChatPage.
// This avoids rendering the white orbit, old toolbar, dual composer, and
// automatically visible execution preview inside the Electron window.
export default function DesktopConversation({
  title = 'Conversa', messages = [], steps = [], running = false,
  files, setFiles, prompt, setPrompt, mode, setMode, agents, selectedAgent, setSelectedAgent,
  onSend, onCommand, onError, onUpload, onCollapse, onNewChat, onTogglePreview,
  previewOpen, onCancel, onApproval, workspaceApprovals = [], onWorkspaceApproval,
  renderAnswer,
}) {
  const transcriptRef = useRef(null)
  const followRef = useRef(true)
  useEffect(() => {
    const viewport = transcriptRef.current
    if (viewport && followRef.current) viewport.scrollTop = viewport.scrollHeight
  }, [messages, steps, running])
  useEffect(() => {
    if (!previewOpen) return undefined
    const closeOnEscape = event => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onTogglePreview()
      }
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [previewOpen, onTogglePreview])
  const pending = steps.filter(step => step.status === 'awaiting_approval')
  return <section className="desktop-conversation" aria-label="Conversa da Central">
    <header className="desktop-conversation-header">
      <div className="desktop-conversation-title">
        <span className={'desktop-conversation-presence' + (running ? ' is-running' : '')} aria-hidden="true"/>
        <div className="desktop-conversation-heading">
          <strong>{title || 'Conversa'}</strong>
          <span>{running ? 'Processando seu pedido…' : 'Conversa com a Central'}</span>
        </div>
      </div>
      <div className="desktop-conversation-actions">
        <button type="button" onClick={onNewChat} title="Nova conversa" aria-label="Nova conversa">
          <span aria-hidden="true">＋</span><span className="desktop-conversation-action-text">Nova</span>
        </button>
        <button type="button" onClick={onTogglePreview} aria-expanded={previewOpen}
          aria-controls="desktop-preview-sheet" title="Abrir prévia somente quando solicitado"
          aria-label="Abrir prévia e execução">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
            <rect x="3" y="4" width="18" height="16" rx="3"/><path d="M13 4v16"/>
          </svg>
          <span className="desktop-conversation-action-text">Prévia</span>
        </button>
        {running && <button className="is-danger" type="button" onClick={onCancel} aria-label="Parar tarefa">Parar</button>}
        <button type="button" onClick={onCollapse} title="Recolher conversa" aria-label="Recolher conversa">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
            <path d="M6 9l6 6 6-6"/>
          </svg>
        </button>
      </div>
    </header>
    <div className="desktop-conversation-scroll" ref={transcriptRef} role="log"
      aria-label="Mensagens da conversa" aria-live="polite" aria-relevant="additions text"
      onScroll={event => {
        const element = event.currentTarget
        followRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80
      }}>
      <div className="desktop-conversation-stream">
        {!messages.length && <div className="desktop-conversation-empty">
          <span className="desktop-conversation-empty-mark" aria-hidden="true">✦</span>
          <strong>Conversa pronta</strong>
          <p>Envie uma mensagem para começar.</p>
        </div>}
        {messages.map((message, index) => {
          if (message.type === 'token_usage') return <div key={'tokens-' + index} className="desktop-conversation-usage">
            Uso de tokens: {Number(message.total_tokens || 0).toLocaleString('pt-BR')}
          </div>
          if (message.type === 'event') return <p key={'event-' + index} className="desktop-conversation-event">{message.content}</p>
          const user = message.role === 'user'
          return <article key={message.stepId || index}
            className={'desktop-message ' + (user ? 'is-user' : 'is-agent')}>
            {!user && <span className="desktop-message-avatar" aria-hidden="true">✦</span>}
            <div className="desktop-message-main">
              <span className="desktop-message-byline">{user ? 'Você' : message.agent || 'Central'}</span>
              <div className="desktop-message-bubble">
                {user ? <p className="whitespace-pre-wrap break-words">{message.content}</p>
                  : renderAnswer(message.content)}
              </div>
            </div>
          </article>
        })}
        {running && <div className="desktop-conversation-working" role="status">
          <span className="desktop-conversation-working-dot" aria-hidden="true"/> A Central está trabalhando…
        </div>}
        {steps.length > 0 && <details className="desktop-conversation-steps" open={pending.length > 0}>
          <summary>Etapas da execução · {steps.filter(item => item.status === 'completed').length}/{steps.length}</summary>
          <div className="desktop-conversation-steps-body">
            {steps.map(step => <div className="desktop-conversation-step" key={step.id}>
              <span>{step.name}</span><small>{step.status}</small>
              {step.status === 'awaiting_approval' && <div className="desktop-conversation-approval">
                <p>O trabalhador solicita sua autorização para continuar esta etapa.</p>
                <button type="button" onClick={() => onApproval(step.id, false)}>Negar</button>
                <button type="button" onClick={() => onApproval(step.id, true)}>Aprovar</button>
              </div>}
            </div>)}
          </div>
        </details>}
        {workspaceApprovals.map(item => <section key={item.approval_id} className="desktop-conversation-workspace-approval">
          <strong>Permissão necessária</strong>
          <p>{item.summary?.description || 'Um trabalhador deseja executar uma ação no computador.'}</p>
          <button type="button" onClick={() => onWorkspaceApproval(item.approval_id, false)}>Negar</button>
          <button type="button" onClick={() => onWorkspaceApproval(item.approval_id, true)}>Permitir esta operação</button>
        </section>)}
      </div>
    </div>
    <div className="desktop-conversation-composer">
      <DesktopChatPrompt embedded prompt={prompt} setPrompt={setPrompt}
        files={files} setFiles={setFiles} mode={mode} setMode={setMode}
        agents={agents} selectedAgent={selectedAgent} setSelectedAgent={setSelectedAgent}
        onSend={onSend} onCommand={onCommand} onError={onError}
        onUpload={onUpload} onClose={previewOpen ? onTogglePreview : onCollapse}/>
      <p className="desktop-conversation-hint">Enter para enviar · Shift + Enter para quebra de linha</p>
    </div>
  </section>
}
