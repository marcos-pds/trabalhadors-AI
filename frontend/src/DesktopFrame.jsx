import { useEffect, useState } from 'react'

// Standard Window Controls Overlay API; no Node, preload or window-control IPC.
export default function DesktopFrame({ children }) {
  const [visible, setVisible] = useState(() => Boolean(navigator.windowControlsOverlay?.visible))
  useEffect(() => {
    const overlay = navigator.windowControlsOverlay
    if (!overlay) return
    const update = () => setVisible(overlay.visible)
    update()
    overlay.addEventListener('geometrychange', update)
    return () => overlay.removeEventListener('geometrychange', update)
  }, [])
  if (!visible) return children
  return <div className="desktop-frame">
    <div className="desktop-titlebar" aria-label="Barra de título da Central IA">Central IA</div>
    <div className="desktop-content">{children}</div>
  </div>
}
