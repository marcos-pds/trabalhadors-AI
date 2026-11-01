import { useEffect, useRef, useState } from 'react'
import { LiquidGlass } from 'liquid-glass-web-react'

// Refraction decorates the background; interactive content stays sharp.
export function LiquidGlassUnderlay({ className = '', strength = 0.08, radius = 28 }) {
  const ref = useRef(null)
  const [bounds, setBounds] = useState({ width: 340, height: 110 })
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const container = ref.current
    if (!container) return
    const refresh = () => {
      const { width, height } = container.getBoundingClientRect()
      setBounds(before => Math.abs(before.width - width) < 2 &&
        Math.abs(before.height - height) < 2 ? before : {
          width: Math.max(1, Math.round(width)),
          height: Math.max(1, Math.round(height)),
        })
    }
    refresh()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(refresh)
    observer.observe(container)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!query) return undefined
    const sync = () => setReduced(query.matches)
    sync()
    query.addEventListener?.('change', sync)
    return () => query.removeEventListener?.('change', sync)
  }, [])
  return <span ref={ref} aria-hidden="true" className={'liquid-underlay ' + className}>
    {reduced ? <span className="liquid-underpaint"/> : (
      <LiquidGlass className="liquid-refractor" x={0.5} y={0.5}
        width={Math.max(48, bounds.width)} height={Math.max(36, bounds.height)}
        radius={radius} strength={strength} chromaticAberration={0.15}
        curvature={0.72} depth={8} glow={0.16} edgeHighlight={0.32}
        quality={256} shadow={false}>
        <span className="liquid-underpaint"><span className="liquid-underpaint-shine"/></span>
      </LiquidGlass>
    )}
  </span>
}

const drawings = {
  plus: <path d="M12 5v14M5 12h14"/>,
  message: <path d="M20 11a8 8 0 0 1-8 8 8 8 0 0 1-3-.6L4 20l1.5-5A8 8 0 1 1 20 11Z"/>,
  sparkles: <><path d="m12 2 2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2L12 2Z"/></>,
  play: <><path d="m9 6 10 6-10 6V6Z"/><rect x="3" y="3" width="18" height="18" rx="4"/></>,
  brain: <><path d="M12 6a4 4 0 0 0-8 1v9a4 4 0 0 0 8 2m0-12a4 4 0 0 1 8 1v9a4 4 0 0 1-8 2V4m0 14v2"/></>,
  monitor: <><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M9 21h6m-3-4v4"/></>,
  zap: <path d="m13 2-9 12h7l-1 8 10-12h-7V2Z"/>,
  users: <><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2H3ZM16 5a3 3 0 0 1 0 6M17 14a5 5 0 0 1 4 5v1"/></>,
  git: <><circle cx="6" cy="3" r="2"/><circle cx="6" cy="21" r="2"/><circle cx="18" cy="6" r="2"/><path d="M6 5v14m0-10c0-3 3-3 6-3h4"/></>,
  layout: <><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M10 9v12"/></>,
  folder: <path d="M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6Z"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  activity: <path d="M2 12h4l3-7 5 14 3-7h5"/>,
  chart: <path d="M4 20V10m5 10V6m5 14v-7m5 7V3"/>,
  puzzle: <path d="M4 4h6v2a2 2 0 0 0 4 0V4h6v6h-2a2 2 0 0 0 0 4h2v6h-6v-2a2 2 0 0 0-4 0v2H4v-6h2a2 2 0 0 0 0-4H4V4Z"/>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M4 9 6 6l3 1 2-3h3l2 3 3-1 2 3-2 3 2 3-2 3-3-1-2 3h-3l-2-3-3 1-2-3 2-3-2-3Z"/></>,
  menu: <path d="M4 6h16M4 12h16M4 18h16"/>,
  check: <path d="m4 12 5 5L20 6"/>,
  x: <path d="M5 5l14 14M19 5 5 19"/>,
}
export function CommandIcon({ name = 'sparkles', className = '' }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
    strokeLinejoin="round" className={'living-command-icon ' + className}>
    {drawings[name] || drawings.sparkles}
  </svg>
}

export function LiveAgentOrbit({ providers = [], running = false }) {
  const enabled = providers.filter(item => item.enabled).slice(0, 5)
  return <div className={'living-agent-orbit' + (running ? ' is-working' : '')}
    aria-label={enabled.length + ' provedores configurados; ' +
      (running ? 'execução em andamento' : 'sem execução em andamento')}>
    <div aria-hidden="true" className="living-orbit-halo halo-one"/>
    <div aria-hidden="true" className="living-orbit-halo halo-two"/>
    <div className="living-core">
      <LiquidGlassUnderlay radius={80} className="living-core-refraction"/>
      <div className="living-core-mark" aria-hidden="true">✳</div>
      <span className="living-core-caption">CENTRAL</span>
    </div>
    {enabled.map((provider, index) => {
      const angle = index * 2 * Math.PI / enabled.length - Math.PI / 2
      return <div key={provider.id} className="living-provider"
        title={provider.name + ' — configuração salva'}
        style={{
          '--orbit-x': Math.cos(angle) * 46 + '%',
          '--orbit-y': Math.sin(angle) * 46 + '%',
          '--orbit-delay': -(index * 0.6) + 's',
        }}>
        <span className="living-provider-dot" aria-hidden="true">✦</span>
        <span>{provider.name}</span>
      </div>
    })}
    {!enabled.length && <span className="living-orbit-hint">Conecte um modelo para começar</span>}
  </div>
}
