import { useState } from 'react'
import GlassCascadeIntro from './intro/GlassCascadeIntro.tsx'

export default function StartupIntro() {
  const [show, setShow] = useState(true)
  const [theme] = useState(() => {
    try {
      return localStorage.getItem('central-theme-design') === 'reference-ice-v1' &&
        localStorage.getItem('central-theme') === 'dark' ? 'dark' : 'light'
    } catch { return 'light' }
  })
  return show ? <GlassCascadeIntro theme={theme} appRootId="root" sound volume={0.55}
    onComplete={() => setShow(false)}/> : null
}
