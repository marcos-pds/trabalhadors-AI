import { useEffect, useState } from 'react'
import LiquidGlass from 'liquid-glass-react'

// rdev/liquid-glass-react's actual displacement/edge-refraction component.
// Desktop-only lazy import. All controls sit ABOVE this pointer-inert layer,
// so the whole interface keeps normal focus and click behaviour.
// Do not mount this surface behind/over the original pink Slime avatar.
export default function DesktopGlassSurface({ className = '' }) {
  const [reduced, setReduced] = useState(() =>
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false)
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!media) return undefined
    const update = () => setReduced(media.matches)
    media.addEventListener?.('change', update)
    return () => media.removeEventListener?.('change', update)
  }, [])

  return <div aria-hidden="true" className={'desktop-rdev-glass ' + className}>
    {reduced
      ? <span className="desktop-rdev-static-surface"/>
      : <LiquidGlass mode="standard" blurAmount={0.075}
          displacementScale={18} aberrationIntensity={0.9}
          saturation={155} elasticity={0} cornerRadius={26}
          padding="0px" style={{height:'100%',width:'100%',pointerEvents:'none'}}>
          <span className="desktop-rdev-static-surface"/>
        </LiquidGlass>}
  </div>
}
