import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = file => readFileSync(new URL('./' + file, import.meta.url), 'utf8')
const style = read('index.css')
const app = read('App.jsx')
const lens = read('LiquidGlassUI.jsx')
const corrected = style.slice(style.indexOf('Ice White glass correction'))

test('Ice White composer has a dark slate outline instead of the original white rim', () => {
  assert.ok(corrected.length > 1800)
  assert.match(corrected, /\.central-root\[data-theme="light"\] \.liquid-chat-composer \{/)
  assert.match(corrected, /border: 1\.5px solid rgba\(43, 57, 79, \.72\)/)
  assert.match(corrected, /border-color: rgba\(30, 41, 59, \.95\)/)
  assert.match(corrected, /backdrop-filter: blur\(18px\) saturate\(165%\)/)
})

test('Composer lens refracts a painted gradient without obscuring input events', () => {
  assert.match(corrected, /\.liquid-chat-composer \.liquid-underpaint \{/)
  assert.match(corrected, /\.liquid-chat-composer::after \{/)
  assert.match(corrected, /pointer-events: none/)
  assert.match(app, /<LiquidGlassUnderlay className="liquid-composer-refraction" strength=\{0\.14\}/)
  assert.match(app, /depth=\{14\} edgeHighlight=\{0\.52\} glow=\{0\.24\}/)
  assert.match(lens, /edgeHighlight=\{edgeHighlight\}/)
  assert.match(lens, /chromaticAberration=\{chromaticAberration\}/)
})

test('No native Expo dependency; reduced motion and forced color remain supported', () => {
  const pkg = JSON.parse(readFileSync(new URL('../../package.json', import.meta.url), 'utf8'))
  assert.ok(pkg.dependencies['liquid-glass-web-react'])
  assert.equal(pkg.dependencies['expo-liquid-glass-view'], undefined)
  assert.match(corrected, /@media \(prefers-reduced-motion: reduce\)/)
  assert.match(corrected, /@media \(forced-colors: active\)/)
  assert.match(corrected, /animation: none/)
  assert.match(corrected, /border: 2px solid CanvasText/)
})
