// Identical SVG outlines, gradients and brand colors from the user's
// reference showcase TSX. Render status comes from real Central APIs.
export const AIIcons = {
  CentralCore: ({ className = "w-6 h-6", isWorking = false }) => (
    <svg viewBox="0 0 100 100" className={className} fill="none">
      <defs>
        <linearGradient id="coreGradLight" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#94a3b8" />
          <stop offset="50%" stopColor="#64748b" />
          <stop offset="100%" stopColor="#334155" />
        </linearGradient>
      </defs>
      <circle cx="50" cy="50" r="28" fill="#f1f5f9" className={isWorking ? "animate-ping opacity-60" : "opacity-40"} />
      <g className={isWorking ? "origin-center animate-[spin_4s_linear_infinite]" : "origin-center animate-[spin_14s_linear_infinite]"}>
        <ellipse cx="50" cy="50" rx="42" ry="18" stroke="url(#coreGradLight)" strokeWidth="3" transform="rotate(30 50 50)" strokeLinecap="round" strokeDasharray="180 40" />
        <ellipse cx="50" cy="50" rx="42" ry="18" stroke="url(#coreGradLight)" strokeWidth="3" transform="rotate(90 50 50)" strokeLinecap="round" strokeDasharray="150 50" />
        <ellipse cx="50" cy="50" rx="42" ry="18" stroke="url(#coreGradLight)" strokeWidth="3" transform="rotate(150 50 50)" strokeLinecap="round" strokeDasharray="200 30" />
      </g>
      <circle cx="50" cy="50" r="10" className={`fill-slate-700 ${isWorking ? "animate-bounce" : "animate-pulse"}`} />
      <circle cx="50" cy="50" r="4.5" fill="#ffffff" />
    </svg>
  ),
  OpenAI: ({ className = "w-5 h-5", color = "#10a37f", state = "idle" }) => (
    <svg viewBox="0 0 24 24" className={`${className} transition-transform duration-500 ${state === 'active' ? 'scale-125 rotate-12' : state === 'working' ? 'animate-[spin_3s_linear_infinite]' : 'animate-breathing hover:rotate-45'}`} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a4.5 4.5 0 0 0-3.89 2.25L4.22 11a4.5 4.5 0 0 0 0 4.5l1.95 3.38a4.5 4.5 0 0 0 6.14 1.65l6.75-3.9a4.5 4.5 0 0 0 2.25-3.89V9a4.5 4.5 0 0 0-2.25-3.89L12.3 1.2" />
      <path d="M12 22a4.5 4.5 0 0 0 3.89-2.25L19.78 13a4.5 4.5 0 0 0 0-4.5l-1.95-3.38a4.5 4.5 0 0 0-6.14-1.65L4.94 7.37A4.5 4.5 0 0 0 2.69 11.26V15a4.5 4.5 0 0 0 2.25 3.89L11.7 22.8" />
      <circle cx="12" cy="12" r="3" className={state === 'working' ? 'animate-ping' : ''} />
    </svg>
  ),
  Claude: ({ className = "w-5 h-5", color = "#d97757", state = "idle" }) => (
    <svg viewBox="0 0 24 24" className={`${className} transition-all duration-300 ${state === 'active' ? 'scale-125 drop-shadow-md' : state === 'working' ? 'animate-wiggle' : 'animate-subtle-float'}`} fill={color}>
      <path d="M12 1L14.2 8.8L21.5 6.5L16.2 12L21.5 17.5L14.2 15.2L12 23L9.8 15.2L2.5 17.5L7.8 12L2.5 6.5L9.8 8.8L12 1Z" />
    </svg>
  ),
  Gemini: ({ className = "w-5 h-5", state = "idle" }) => (
    <svg viewBox="0 0 24 24" className={`${className} transition-all duration-300 ${state === 'active' ? 'scale-125 drop-shadow-md' : state === 'working' ? 'animate-[spin_2s_ease-in-out_infinite]' : 'animate-pulse'}`} fill="none">
      <defs>
        <linearGradient id="geminiGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#4facfe" />
          <stop offset="50%" stopColor="#a18cd1" />
          <stop offset="100%" stopColor="#fbc2eb" />
        </linearGradient>
      </defs>
      <path d="M12 2C12 7.52 16.48 12 22 12C16.48 12 12 16.48 12 22C12 16.48 7.52 12 2 12C7.52 12 12 7.52 12 2Z" fill="url(#geminiGrad)" />
    </svg>
  ),
  DeepSeek: ({ className = "w-5 h-5", color = "#3b82f6", state = "idle" }) => (
    <svg viewBox="0 0 24 24" className={`${className} transition-all duration-300 ${state === 'active' ? 'scale-125 -translate-y-1' : state === 'working' ? 'animate-swim' : 'animate-float'}`} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12c2-4 6-7 11-7 4 0 8 2 9 6-2 4-5 7-10 7-3 0-6-1-8-3l-2 2v-5z" />
      <circle cx="15" cy="10" r="1.5" fill={color} className="animate-ping origin-center" />
    </svg>
  ),
  Meta: ({ className = "w-5 h-5", color = "#0ea5e9", state = "idle" }) => (
    <svg viewBox="0 0 24 24" className={`${className} transition-all duration-300 ${state === 'active' ? 'scale-125' : state === 'working' ? 'animate-pulse' : 'hover:scale-110'}`} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18.178 8c5.096 0 5.096 8 0 8-5.095 0-7.133-8-12.739-8-4.585 0-4.585 8 0 8 5.606 0 7.644-8 12.74-8z" />
    </svg>
  ),
  Mistral: ({ className = "w-5 h-5", color = "#f59e0b", state = "idle" }) => (
    <svg viewBox="0 0 24 24" className={`${className} transition-all duration-300 ${state === 'active' ? 'scale-125' : state === 'working' ? 'animate-pulse' : 'hover:rotate-12'}`} fill={color}>
      <path d="M3 4h4v4H3V4zm14 0h4v4h-4V4zM7 8h4v4H7V8zm6 0h4v4h-4V8zM3 12h4v8H3v-8zm8 0h2v4h-2v-4zm6 0h4v8h-4v-8zM7 16h4v4H7v-4zm6 0h4v4h-4v-4z" />
    </svg>
  )
};

export const referenceBrandKinds = Object.freeze({
  openai: 'OpenAI', openai_chatgpt: 'OpenAI', codex_cli: 'OpenAI',
  anthropic: 'Claude', claude_cli: 'Claude',
  gemini: 'Gemini', gemini_cli: 'Gemini',
  deepseek: 'DeepSeek',
  ollama: 'Meta', meta: 'Meta',
  mistral: 'Mistral',
})
export function ReferenceProviderIcon({ kind, className = 'w-5 h-5', state = 'idle' }) {
  const Component = AIIcons[referenceBrandKinds[String(kind || '').toLowerCase()]] || AIIcons.CentralCore
  return <Component className={className} state={state} />
}
