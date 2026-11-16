import { useEffect, useState } from 'react'

const INITIAL = { phase: 'idle', version: null, progress: 0, message: '' }

export default function DesktopUpdateControl({ workspaceOpen = false }) {
  const [opened, setOpened] = useState(false)
  const [state, setState] = useState(INITIAL)
  const [error, setError] = useState('')
  const bridge = window.centralDesktop

  useEffect(() => {
    if (!bridge?.getUpdateState || !bridge?.onUpdateState) return undefined
    let alive = true
    bridge.getUpdateState().then(s => { if (alive && s) setState(s) }).catch(() => {})
    const dispose = bridge.onUpdateState(next => { if (alive && next) setState(next) })
    return () => { alive = false; dispose?.() }
  }, [bridge])

  useEffect(() => {
    if (workspaceOpen) setOpened(false)
  }, [workspaceOpen])

  function toggle() {
    if (opened) {
      setOpened(false)
      if (!workspaceOpen) bridge.setExpanded(false)
    } else {
      bridge.setExpanded(true)
      setOpened(true)
    }
  }
  async function action(kind) {
    setError('')
    try { await bridge.updateAction(kind) }
    catch (e) { setError(e?.message || 'Não foi possível executar esta operação.') }
  }
  const available = ['available', 'ready'].includes(state.phase)
  const working = ['checking', 'downloading', 'checking-tasks', 'backing-up', 'installing'].includes(state.phase)
  return <>
    <button type="button" onClick={toggle}
      className={'desktop-dock-icon desktop-update-trigger' + (available ? ' has-update' : '')}
      aria-label={available ? 'Nova versão da Central disponível' : 'Verificar atualizações'}
      title="Atualizações da Central" aria-expanded={opened} aria-controls="desktop-update-panel">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" width="16" height="16">
        <path d="M20 11a8 8 0 0 0-14-5L4 8m0-5v5h5M4 13a8 8 0 0 0 14 5l2-2m0 5v-5h-5"/>
      </svg>
      {available && <span className="desktop-update-dot" aria-hidden="true"/>}
    </button>
    {opened && <aside id="desktop-update-panel" className="desktop-update-popover" aria-label="Atualizações">
      <div className="desktop-update-header">
        <strong>Atualizações</strong>
        <button type="button" aria-label="Fechar atualizações" onClick={toggle}>×</button>
      </div>
      <p className="desktop-update-version">Central {state.currentVersion || 'Desktop'}{state.version ? ' · Nova versão ' + state.version : ''}</p>
      <p role="status" aria-live="polite" className="desktop-update-message">{error || state.message || 'Verifique se há uma nova versão estável no GitHub.'}</p>
      {state.phase === 'downloading' && <div className="desktop-update-progress" role="progressbar"
        aria-label="Download da atualização" aria-valuenow={state.progress || 0} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: (state.progress || 0) + '%' }}/>
      </div>}
      {state.phase === 'available' && <button className="desktop-update-primary" type="button" onClick={() => action('download')}>Baixar atualização</button>}
      {state.phase === 'ready' && <button className="desktop-update-primary" type="button" onClick={() => action('install')}>Instalar e reiniciar</button>}
      {state.phase !== 'available' && state.phase !== 'ready' && <button type="button"
        className="desktop-update-secondary" disabled={working} onClick={() => action('check')}>
        {working ? 'Verificando…' : 'Buscar atualizações'}
      </button>}
      <p className="desktop-update-help">Os downloads só começam com sua permissão. Antes de instalar, a Central verifica as tarefas e cria um backup local.</p>
      {state.backup && <p className="desktop-update-backup">Backup: {state.backup}</p>}
    </aside>}
  </>
}
