import './desktop-liquid-glass.css'
import { CommandIcon, LiquidGlassUnderlay } from './LiquidGlassUI.jsx'
import DesktopSlime from './DesktopSlime.jsx'
import DesktopUpdateControl from './DesktopUpdateControl.jsx'

const tools = [
  ['dashboard', 'layout', 'Visão geral'],
  ['agents', 'users', 'Trabalhadores'],
  ['workflows', 'git', 'Fluxos'],
  ['projects', 'folder', 'Projetos'],
  ['history', 'clock', 'Histórico'],
  ['monitoring', 'activity', 'Monitoramento'],
  ['tokens', 'chart', 'Consumo de tokens'],
  ['providers', 'sparkles', 'Provedores de IA'],
  ['resources', 'puzzle', 'Skills e integrações'],
  ['git', 'git', 'GitHub'],
  ['settings', 'settings', 'Configurações'],
]

// Always visible even while the conversation is collapsed. The avatar alone
// toggles CHAT; tool icons open their own workspace, never the chat.
export default function DesktopDock({ active = false, page = 'chat', running = false,
  typing = false, failed = false,
  onToggleChat, onNavigate, onClosePanel, onOpenMenu, onOpenMemory, onOpenComputer }) {
  return <header className="desktop-dock" aria-label="Barra de ferramentas desktop da Central IA">
    <LiquidGlassUnderlay className="desktop-dock-refraction" strength={0.09}
      radius={28} glow={0.2} edgeHighlight={0.4}/>
    <div className="desktop-dock-content">
      <button type="button" className={'desktop-slime-button' + (active && page === 'chat' ? ' is-active' : '')}
        onClick={event => {
          if (event.currentTarget.dataset.slimeDrag === 'true') {
            event.currentTarget.dataset.slimeDrag = 'false'
            return
          }
          onToggleChat()
        }} aria-label={active && page === 'chat' ? 'Recolher conversa ou campo de mensagem' : 'Mostrar campo de mensagem'}
        title={active && page === 'chat' ? 'Recolher chat' : 'Clique no avatar para digitar seu pedido'}
        aria-expanded={active && page === 'chat'} aria-controls="desktop-central-panel">
        <DesktopSlime active={active && page === 'chat'} running={running} typing={typing} failed={failed}/>
      </button>
      <span className="desktop-dock-separator" aria-hidden="true"/>
      <nav aria-label="Funções da IA" className="desktop-dock-actions">
        {tools.map(([id, icon, label]) => <button key={id} type="button"
          aria-label={label} title={label} onClick={() => onNavigate(id)}
          aria-current={active && page === id ? 'page' : undefined}
          className={'desktop-dock-icon' + (active && page === id ? ' is-current' : '')}>
          <CommandIcon name={icon}/>
        </button>)}
      </nav>
      <span className="desktop-dock-separator" aria-hidden="true"/>
      <button type="button" onClick={onOpenMemory} aria-label="Memória da Central"
        title="Memória" className="desktop-dock-icon"><CommandIcon name="brain"/></button>
      <button type="button" onClick={onOpenComputer} aria-label="Acesso ao computador"
        title="Acesso ao computador" className="desktop-dock-icon"><CommandIcon name="monitor"/></button>
      <DesktopUpdateControl workspaceOpen={active}/>
      <button type="button" onClick={onOpenMenu} aria-label="Menu de conversas"
        title="Histórico de conversas" className="desktop-dock-icon">
        <CommandIcon name="menu"/>
      </button>
      {running && <span className="desktop-dock-status" role="status" title="Agente executando" aria-label="Agente executando"/>}
      {active && <button type="button" onClick={onClosePanel} aria-label="Recolher painel"
        title="Recolher painel" className="desktop-dock-icon desktop-dock-close">
        <CommandIcon name="x"/>
      </button>}
    </div>
  </header>
}
