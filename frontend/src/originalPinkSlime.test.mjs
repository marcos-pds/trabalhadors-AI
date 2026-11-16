import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'
import { createOriginalPinkSlime } from './originalPinkSlime.js'

// Geometry and animation tests run without WebGL or a visible browser window.
// Canvas context is needed only to construct the original eye textures.
const context = {
  createRadialGradient: () => ({ addColorStop() {} }),
  createLinearGradient: () => ({ addColorStop() {} }),
  fillRect() {}, save() {}, restore() {}, translate() {}, rotate() {},
  beginPath() {}, ellipse() {}, fill() {},
}
const oldDocument = globalThis.document
test('original Pink Slime geometry, materials and expression system are preserved', () => {
  globalThis.document = { createElement: tag => {
    assert.equal(tag, 'canvas')
    return { width: 256, height: 256, getContext: () => context }
  } }
  try {
    const scene = new THREE.Scene()
    const slime = createOriginalPinkSlime(scene)
    assert.equal(slime.modelConfig.id, 'pink')
    assert.equal(slime.modelConfig.midColor, '#f2577b')
    assert.ok(slime.bodyGeo.attributes.position.count > 9000)
    assert.ok(slime.leftEyeMat.map)
    assert.ok(slime.rightEyeMat.map)
    slime.triggerReaction('happy', 2)
    assert.equal(slime.expression, 'happy')
    assert.equal(slime.isJumping, true)
    slime.update(1 / 60, 0.5, new THREE.Vector2(0.2, 0), false)
    assert.equal(slime.happyEyesGroup.visible, true)
    slime.triggerReaction('yawn', 2)
    slime.update(1 / 60, 0.6, new THREE.Vector2(0, 0), false)
    assert.equal(slime.openMouthGroup.visible, true)
    slime.triggerReaction('dizzy', 2)
    assert.ok(slime.jiggleIntensity > 0)
    assert.equal(scene.children.includes(slime.root), true)
  } finally {
    globalThis.document = oldDocument
  }
})
