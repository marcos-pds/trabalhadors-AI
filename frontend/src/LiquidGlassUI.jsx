import { useEffect, useRef, useState } from 'react'
import { LiquidGlass } from 'liquid-glass-web-react'
import { AIIcons } from './ReferenceIcons.jsx'

// Refraction decorates the background; interactive content stays sharp.
export function LiquidGlassUnderlay({ className = '', strength = 0.08, radius = 28,
  depth = 8, edgeHighlight = 0.32, glow = 0.16, chromaticAberration = 0.15 }) {
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
  return <div ref={ref} aria-hidden="true" className={'liquid-underlay ' + className}>
    {reduced ? <span className="liquid-underpaint"/> : (
      <LiquidGlass className="liquid-refractor" x={0.5} y={0.5}
        width={Math.max(48, bounds.width)} height={Math.max(36, bounds.height)}
        radius={radius} strength={strength} chromaticAberration={chromaticAberration}
        curvature={0.72} depth={depth} glow={glow} edgeHighlight={edgeHighlight}
        quality={256} shadow={false}>
        <span className="liquid-underpaint"><span className="liquid-underpaint-shine"/></span>
      </LiquidGlass>
    )}
  </div>
}

const drawings = {
  send: <><path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  message: <path d="M20 11a8 8 0 0 1-8 8 8 8 0 0 1-3-.6L4 20l1.5-5A8 8 0 1 1 20 11Z"/>,
  sparkles: <><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z" /><path d="M20 2v4"/><path d="M22 4h-4"/><circle cx="4" cy="20" r="2"/></>,
  play: <path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/>,
  brain: <><path d="M12 6a4 4 0 0 0-8 1v9a4 4 0 0 0 8 2m0-12a4 4 0 0 1 8 1v9a4 4 0 0 1-8 2V4m0 14v2"/></>,
  monitor: <><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M9 21h6m-3-4v4"/></>,
  zap: <path d="m13 2-9 12h7l-1 8 10-12h-7V2Z"/>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><path d="M16 3.128a4 4 0 0 1 0 7.744"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/></>,
  git: <><circle cx="6" cy="3" r="2"/><circle cx="6" cy="21" r="2"/><circle cx="18" cy="6" r="2"/><path d="M6 5v14m0-10c0-3 3-3 6-3h4"/></>,
  layout: <><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M10 9v12"/></>,
  folder: <path d="M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6Z"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  activity: <path d="M2 12h4l3-7 5 14 3-7h5"/>,
  chart: <path d="M4 20V10m5 10V6m5 14v-7m5 7V3"/>,
  puzzle: <path d="M4 4h6v2a2 2 0 0 0 4 0V4h6v6h-2a2 2 0 0 0 0 4h2v6h-6v-2a2 2 0 0 0-4 0v2H4v-6h2a2 2 0 0 0 0-4H4V4Z"/>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M4 9 6 6l3 1 2-3h3l2 3 3-1 2 3-2 3 2 3-2 3-3-1-2 3h-3l-2-3-3 1-2-3 2-3-2-3Z"/></>,
  menu: <path d="M4 5h16M4 12h16M4 19h16"/>,
  check: <path d="m4 12 5 5L20 6"/>,
  x: <path d="M5 5l14 14M19 5 5 19"/>,
}
export function CommandIcon({ name = 'sparkles', className = '' }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    strokeLinejoin="round" className={'living-command-icon ' + className}>
    {drawings[name] || drawings.sparkles}
  </svg>
}


// The home illustration preserves the EXACT four brand marks and positions
// of the supplied showcase. It is an illustration, not a provider health claim.
const ORBIT_BRANDS = [
  { key: 'openai', title: 'OpenAI', Icon: AIIcons.OpenAI, kinds: ['openai', 'openai_chatgpt', 'codex_cli'] },
  { key: 'claude', title: 'Claude', Icon: AIIcons.Claude, kinds: ['anthropic', 'claude_cli'] },
  { key: 'gemini', title: 'Gemini', Icon: AIIcons.Gemini, kinds: ['gemini', 'gemini_cli'] },
  { key: 'deepseek', title: 'DeepSeek', Icon: AIIcons.DeepSeek, kinds: ['deepseek'] },
]

export function LiveAgentOrbit({ providers = [], running = false }) {
  const enabled = providers.filter(p => p.enabled)
  return <div className={'reference-orbit' + (running ? ' is-working' : '')}
    aria-label={'Representação visual de provedores de IA. ' + enabled.length +
      ' conexão(ões) habilitada(s).'}>
    <div className="reference-orbit-blur reference-orbit-blur-green" aria-hidden="true" />
    <div className="reference-orbit-blur reference-orbit-blur-blue" aria-hidden="true" />
    <div className="reference-orbit-halo reference-orbit-halo-outer" aria-hidden="true" />
    <div className="reference-orbit-halo reference-orbit-halo-inner" aria-hidden="true" />
    <div className="reference-glass-core">
      <LiquidGlassUnderlay className="reference-glass-refraction" strength={0.075} radius={85}/>
      <AIIcons.CentralCore className="reference-core-icon relative z-10" isWorking={running}/>
      <div className="reference-core-shine" aria-hidden="true"/>
    </div>
    {ORBIT_BRANDS.map((brand, index) => {
      const connected = enabled.some(p => brand.kinds.includes(String(p.kind || '').toLowerCase()))
      const angle = (index * 360) / ORBIT_BRANDS.length
      const x = Math.cos(angle * Math.PI / 180) * 46.875
      const y = Math.sin(angle * Math.PI / 180) * 46.875
      return <div key={brand.key} className="reference-orbit-satellite"
        style={{ '--satellite-x': x + '%', '--satellite-y': y + '%', '--satellite-index': index }}
        title={brand.title + ' · ' + (connected ? 'conexão habilitada' : 'ícone de referência; não conectado')}>
        <span className="reference-orbit-satellite-glass">
          <brand.Icon className="h-5 w-5" state="idle"/>
        </span>
      </div>
    })}
    {running && <div className="reference-orbit-pulse" aria-hidden="true"/>}
  </div>
}
