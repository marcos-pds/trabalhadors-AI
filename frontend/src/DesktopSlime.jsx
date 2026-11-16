import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'

// A real 3D black/graphite Slime. The canvas is transparent: glass styling is
// deliberately applied only to the surrounding dock, never to the avatar.
export default function DesktopSlime({ active = false }) {
  const host = useRef(null)
  const [fallback, setFallback] = useState(false)
  useEffect(() => {
    const target = host.current
    if (!target) return
    let renderer
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' })
    } catch {
      setFallback(true)
      return undefined
    }
    renderer.setClearColor(0x000000, 0)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.42
    renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;pointer-events:none'
    target.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 20)
    camera.position.set(0, 0.03, 3.65)
    scene.add(new THREE.HemisphereLight(0xa7b5df, 0x05060d, 2.3))
    const key = new THREE.DirectionalLight(0xf1f4ff, 3.6)
    key.position.set(-2.7, 4, 4.5)
    scene.add(key)
    const side = new THREE.DirectionalLight(0x8798df, 2.8)
    side.position.set(3, 1.6, -0.3)
    scene.add(side)
    const edge = new THREE.DirectionalLight(0xd7d4ff, 1.45)
    edge.position.set(-1, 2, -4)
    scene.add(edge)
    const root = new THREE.Group()
    scene.add(root)

    const bodyGeo = new THREE.SphereGeometry(1, 64, 48)
    const pos = bodyGeo.attributes.position
    const color = []
    const top = new THREE.Color('#454b5e')
    const middle = new THREE.Color('#141926')
    const bottom = new THREE.Color('#05060c')
    const mixed = new THREE.Color()
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i)
      const bulge = 1 + .13 * Math.exp(-Math.pow((y + .26) / .45, 2))
      const lower = y < -.55 ? .83 + .17 * (y + 1) / .45 : 1
      pos.setXYZ(i, x * bulge * lower, y < -.55 ? -.55 + .27 * Math.sin((y + .55) / .45 * Math.PI / 2) : y * .9, z * bulge * lower)
      const t = Math.min(1, Math.max(0, (y + .9) / 1.8))
      if (t < .55) mixed.lerpColors(bottom, middle, t / .55)
      else mixed.lerpColors(middle, top, (t - .55) / .45)
      color.push(mixed.r, mixed.g, mixed.b)
    }
    bodyGeo.setAttribute('color', new THREE.Float32BufferAttribute(color, 3))
    bodyGeo.computeVertexNormals()
    const body = new THREE.Mesh(bodyGeo, new THREE.MeshPhysicalMaterial({
      vertexColors: true, roughness: .24, metalness: .12, clearcoat: 1,
      clearcoatRoughness: .13, transparent: false,
    }))
    root.add(body)

    const eyes = new THREE.Group()
    const eyeMat = new THREE.MeshPhysicalMaterial({ color: 0x100d17, roughness: .15, clearcoat: 1 })
    const gleamMat = new THREE.MeshBasicMaterial({ color: 0xeef2ff })
    const irisMat = new THREE.MeshBasicMaterial({ color: 0x9686c9 })
    for (const direction of [-1, 1]) {
      const eye = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 20), eyeMat)
      eye.scale.set(.18, .24, .09)
      eye.position.set(direction * .35, .11, .98)
      eyes.add(eye)
      const iris = new THREE.Mesh(new THREE.SphereGeometry(.07, 16, 12), irisMat)
      iris.position.set(direction * .35 + .014, .08, 1.075)
      eyes.add(iris)
      const glint = new THREE.Mesh(new THREE.SphereGeometry(.046, 12, 8), gleamMat)
      glint.position.set(direction * .35 - .05, .19, 1.085)
      eyes.add(glint)
    }
    root.add(eyes)
    const smile = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-.19, -.28, 1.037),
      new THREE.Vector3(-.08, -.34, 1.063),
      new THREE.Vector3(.08, -.34, 1.063),
      new THREE.Vector3(.19, -.28, 1.037),
    ])
    root.add(new THREE.Mesh(new THREE.TubeGeometry(smile, 22, .019, 8, false),
      new THREE.MeshBasicMaterial({ color: 0x090910 })))

    const resize = () => {
      if (!target.isConnected) return
      const side = Math.max(32, Math.round(target.getBoundingClientRect().width))
      renderer.setSize(side, side, false)
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(target)
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    const timer = new THREE.Clock()
    let frame = 0
    let rendered = true
    const animate = () => {
      if (!rendered) return
      const t = timer.getElapsedTime()
      if (!reduced?.matches) {
        root.position.y = Math.sin(t * 1.9) * (active ? .055 : .028)
        root.rotation.y = Math.sin(t * .78) * .14
        body.scale.set(1 + .012 * Math.sin(t * 2.1), 1 - .016 * Math.sin(t * 2.1), 1)
      }
      renderer.render(scene, camera)
      frame = requestAnimationFrame(animate)
    }
    frame = requestAnimationFrame(animate)
    return () => {
      rendered = false
      cancelAnimationFrame(frame)
      observer.disconnect()
      target.removeChild(renderer.domElement)
      scene.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose()
        if (obj.material) (Array.isArray(obj.material) ? obj.material : [obj.material]).forEach(mat => mat.dispose())
      })
      renderer.dispose()
    }
  }, [active])
  return <span ref={host} className="desktop-slime-canvas" aria-hidden="true">
    {fallback && <span className="desktop-slime-fallback"><i/><i/><b/></span>}
  </span>
}
