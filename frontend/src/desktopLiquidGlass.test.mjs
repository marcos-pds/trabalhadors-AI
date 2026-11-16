import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const file = name => readFileSync(new URL(name, import.meta.url), 'utf8')

test('Liquid Glass styling is activated by Electron only, not by web or PWA', () => {
  const css = file('./desktop-liquid-glass.css')
  const dock = file('./DesktopDock.jsx')
  const app = file('./App.jsx')
  const guard = file('./desktopMode.mjs')
  assert.match(css, /html\.central-desktop-shell \.central-desktop-mode/)
  assert.match(css, /html\.central-desktop-shell #root > main/)
  assert.match(dock, /import '\.\/desktop-liquid-glass\.css'/)
  assert.match(app, /lazy\(\(\) => import\('\.\/DesktopDock\.jsx'\)\)/)
  assert.match(app, /lazy\(\(\) => import\('\.\/DesktopGlassSurface\.jsx'\)\)/)
  assert.match(guard, /setExpanded === 'function'/)
  assert.doesNotMatch(app, /^import '\.\/desktop-liquid-glass\.css'/m)
})

test('the actual rdev refraction is behind the workspace, never on pink avatar', () => {
  const surface = file('./DesktopGlassSurface.jsx')
  const css = file('./desktop-liquid-glass.css')
  const slime = file('./DesktopSlime.jsx')
  assert.match(surface, /from 'liquid-glass-react'/)
  assert.match(surface, /displacementScale=\{18\}/)
  assert.match(surface, /pointerEvents:'none'/)
  assert.match(css, /\.desktop-rdev-glass/)
  assert.match(css, /\.desktop-slime-canvas/)
  assert.match(css, /backdrop-filter: none !important;/)
  assert.match(slime, /createOriginalPinkSlime/)
})

test('native Electron never inherits the white PWA caption and intro', () => {
  const frame = file('./DesktopFrame.jsx')
  const intro = file('./StartupIntro.jsx')
  assert.match(frame, /isNativeDesktop/)
  assert.match(frame, /if \(isNativeDesktop \|\| !visible\) return children/)
  assert.match(intro, /window\.centralDesktop\?\.isDesktop === true/)
  assert.match(intro, /return 'dark'/)
})

test('desktop glass theme covers all Central screens and input types', () => {
  const css = file('./desktop-liquid-glass.css')
  for (const selector of [
    '.central-main', '.bg-panel', '.bg-card', '.liquid-chat-composer',
    '.central-drawer', '.liquid-command-menu', 'input:not([type="checkbox"])',
    'textarea, select', 'table', '[role="dialog"]', '[role="status"]'
  ]) {
    assert.ok(css.includes(selector), 'missing glass theme coverage: ' + selector)
  }
})
