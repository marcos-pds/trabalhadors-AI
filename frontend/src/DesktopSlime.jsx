import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { createOriginalPinkSlime } from './originalPinkSlime.js'

// Original user-supplied Pink Slime. Its scene is transparent so the avatar
// does not inherit the Liquid Glass filter or any coloured card around it.
export default function DesktopSlime({ active = false, running = false, typing = false, failed = false }) {
  const hostRef = useRef(null)
  const slimeRef = useRef(null)
  const stateRef = useRef({ active, running, typing, failed })
  const previousRef = useRef({ running, failed })
  const [fallback, setFallback] = useState(false)
  stateRef.current = { active, running, typing, failed }

  useEffect(() => {
    const slime = slimeRef.current
    const previous = previousRef.current
    previousRef.current = { running, failed }
    if (!slime) return
    slime.isChatOpen = active
    slime.isTyping = typing || running
    if (failed && !previous.failed) slime.triggerReaction('dizzy', 2.2)
    else if (previous.running && !running && !failed) slime.triggerReaction('love', 2.5)
  }, [active, running, typing, failed])

  useEffect(() => {
    const host = hostRef.current
    const button = host?.closest('button')
    if (!host || !button) return undefined

    let renderer
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true, alpha: true, powerPreference: 'high-performance',
        preserveDrawingBuffer: false,
      })
    } catch {
      setFallback(true)
      return undefined
    }

    renderer.setClearColor(0, 0)
    renderer.setPixelRatio(1)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.08
    renderer.domElement.style.cssText =
      'display:block;width:100%;height:100%;pointer-events:none;background:transparent;'
    host.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50)
    camera.position.set(0, 0.08, 4.9)

    scene.add(new THREE.HemisphereLight(0xfff7f9, 0xd8b4c2, 1.45))
    const keyLight = new THREE.DirectionalLight(0xfffcfb, 1.65)
    keyLight.position.set(-2.6, 3.8, 4.2)
    scene.add(keyLight)
    const fillLight = new THREE.DirectionalLight(0xffe4ee, 0.75)
    fillLight.position.set(3.2, 1.2, 2.8)
    scene.add(fillLight)
    const rimLight = new THREE.DirectionalLight(0xffffff, 0.65)
    rimLight.position.set(0, 2.5, -3.5)
    scene.add(rimLight)

    const slime = createOriginalPinkSlime(scene)
    slime.isChatOpen = stateRef.current.active
    slime.isTyping = stateRef.current.typing || stateRef.current.running
    slimeRef.current = slime

    // Supersample at 3.5x+ the visible avatar size. The character stays small,
    // but its eyes and mouth render at 190-256 physical pixels before downscale.
    function resize() {
      if (!host.isConnected) return
      const width = Math.max(42, host.getBoundingClientRect().width)
      const physical = Math.max(192, Math.min(256, Math.ceil(width * Math.max(3.6, (window.devicePixelRatio || 1) * 2))))
      renderer.setSize(physical, physical, false)
      camera.aspect = 1
      camera.updateProjectionMatrix()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(host)

    const mouse = new THREE.Vector2()
    const pointer = { down: false, moved: 0, x: 0, y: 0, id: null }
    function onPointerMove(event) {
      const bounds = button.getBoundingClientRect()
      mouse.x = THREE.MathUtils.clamp(((event.clientX - bounds.left) / bounds.width) * 2 - 1, -1, 1)
      mouse.y = THREE.MathUtils.clamp(1 - ((event.clientY - bounds.top) / bounds.height) * 2, -1, 1)
      if (!pointer.down) {
        slime.idleTime = 0
        return
      }
      const dx = event.clientX - pointer.x
      const dy = event.clientY - pointer.y
      pointer.moved += Math.hypot(dx, dy)
      pointer.x = event.clientX
      pointer.y = event.clientY
      if (pointer.moved > 6) {
        slime.expression = 'dizzy'
        slime.currentRotY += dx * .022
        slime.targetRotY = slime.currentRotY
        slime.currentRotX = THREE.MathUtils.clamp(slime.currentRotX + dy * .015, -.55, .55)
        slime.dragOffset.x = THREE.MathUtils.clamp(dx * .03, -.6, .6)
        slime.dragOffset.y = THREE.MathUtils.clamp(-dy * .03, -.5, .5)
        slime.jiggleIntensity = 1.1
      }
    }
    function onPointerDown(event) {
      if (event.button !== 0) return
      pointer.down = true
      pointer.moved = 0
      pointer.x = event.clientX
      pointer.y = event.clientY
      pointer.id = event.pointerId
      button.dataset.slimeDrag = 'false'
      try { button.setPointerCapture(event.pointerId) } catch { /* unavailable pointer capture */ }
      slime.triggerSquash(1.14, .86, 1.14, .6)
    }
    function endPointer(event) {
      if (!pointer.down) return
      pointer.down = false
      if (pointer.id !== null && button.hasPointerCapture?.(pointer.id)) {
        button.releasePointerCapture(pointer.id)
      }
      pointer.id = null
      if (pointer.moved > 6) {
        button.dataset.slimeDrag = 'true'
        slime.triggerReaction('dizzy', 1.8)
        slime.triggerSquash(.84, 1.24, .84, 1.4)
      }
    }
    function onClick() {
      if (button.dataset.slimeDrag === 'true') return
      slime.triggerReaction('happy', 2.6)
    }

    button.addEventListener('pointerdown', onPointerDown)
    button.addEventListener('pointermove', onPointerMove)
    button.addEventListener('pointerup', endPointer)
    button.addEventListener('pointercancel', endPointer)
    button.addEventListener('click', onClick)
    window.addEventListener('pointermove', onPointerMove)

    const clock = new THREE.Clock()
    let frame = 0
    let disposed = false
    const animate = () => {
      if (disposed) return
      frame = requestAnimationFrame(animate)
      const dt = Math.min(clock.getDelta(), .05)
      const t = clock.getElapsedTime()
      slime.isChatOpen = stateRef.current.active
      slime.isTyping = stateRef.current.typing || stateRef.current.running
      if (!document.hidden) {
        slime.update(dt, t, mouse, pointer.down && pointer.moved > 6)
        renderer.render(scene, camera)
      }
    }
    frame = requestAnimationFrame(animate)
    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      observer.disconnect()
      button.removeEventListener('pointerdown', onPointerDown)
      button.removeEventListener('pointermove', onPointerMove)
      button.removeEventListener('pointerup', endPointer)
      button.removeEventListener('pointercancel', endPointer)
      button.removeEventListener('click', onClick)
      window.removeEventListener('pointermove', onPointerMove)
      delete button.dataset.slimeDrag
      slimeRef.current = null
      const geometries = new Set()
      const materials = new Set()
      const textures = new Set()
      scene.traverse(object => {
        if (object.geometry) geometries.add(object.geometry)
        for (const material of [].concat(object.material || [])) {
          if (!material) continue
          materials.add(material)
          if (material.map) textures.add(material.map)
        }
      })
      geometries.forEach(geometry => geometry.dispose())
      textures.forEach(texture => texture.dispose())
      materials.forEach(material => material.dispose())
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [])

  return <span ref={hostRef} aria-hidden="true" className="desktop-slime-canvas">
    {fallback && <span className="desktop-slime-fallback"><i/><i/><b/></span>}
  </span>
}
