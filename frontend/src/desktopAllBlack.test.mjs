import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { MIN_ALL_BLACK_SCREEN_WIDTH, shouldUseDesktopAllBlack,
  getDesktopAllBlackState, applyDesktopAllBlack } from './desktopAllBlack.mjs'

const read = name => readFileSync(new URL(name, import.meta.url), 'utf8')
const css = read('./desktop-noir.css')

test('native theme requires 1024px monitor, never a web tab or tablet', () => {
  assert.equal(MIN_ALL_BLACK_SCREEN_WIDTH, 1024)
  assert.equal(shouldUseDesktopAllBlack(false, 1920), false)
  assert.equal(shouldUseDesktopAllBlack(true, 320), false)
  assert.equal(shouldUseDesktopAllBlack(true, 768), false)
  assert.equal(shouldUseDesktopAllBlack(true, 1023), false)
  assert.equal(shouldUseDesktopAllBlack(true, 1024), true)
  assert.equal(shouldUseDesktopAllBlack(true, 1920), true)
  assert.equal(shouldUseDesktopAllBlack(true, NaN), false)
  assert.equal(getDesktopAllBlackState({ screen: { width: 1440 }, innerWidth: 360 }, true), true,
    'the compact Electron dock must still have the theme on a desktop monitor')
  assert.equal(getDesktopAllBlackState({ screen: { width: 800 }, innerWidth: 1440 }, true), false)
})

test('resize and display changes can enable and disable theme without modifying saved preferences', () => {
  const tokens = new Set()
  const root = { classList: { toggle(name, enabled) {
    if (enabled) tokens.add(name)
    else tokens.delete(name)
  } } }
  assert.equal(applyDesktopAllBlack(root, shouldUseDesktopAllBlack(true, 1920)), true)
  assert.ok(tokens.has('central-desktop-all-black'))
  assert.equal(applyDesktopAllBlack(root, shouldUseDesktopAllBlack(true, 800)), false)
  assert.ok(!tokens.has('central-desktop-all-black'))
  assert.equal(applyDesktopAllBlack(root, shouldUseDesktopAllBlack(false, 1920)), false)
  const app = read('./App.jsx')
  assert.match(app, /window\.addEventListener\('resize', sync\)/)
  assert.match(app, /window\.screen\?\.orientation\?\.addEventListener\?\.\('change', sync\)/)
  assert.match(app, /if\(!desktopMode\)\{localStorage\.setItem\('central-theme'/)
  assert.doesNotMatch(app, /localStorage\.setItem\('central-desktop-all-black'/)
})

test('exact all-black design tokens and original accent are centralized', () => {
  const expected = [
    ['--desktop-black-bg', '#000000'],
    ['--desktop-black-sidebar', '#050505'],
    ['--desktop-black-panel', '#0D0D0D'],
    ['--desktop-black-raised', '#141414'],
    ['--desktop-black-input', '#101010'],
    ['--desktop-black-border', '#242424'],
    ['--desktop-black-copy', '#F5F5F5'],
    ['--desktop-black-secondary', '#A3A3A3'],
    ['--desktop-black-disabled', '#666666'],
    ['--desktop-black-accent', '#D7B4FA'],
    ['--desktop-black-duration', '180ms'],
  ]
  for (const [token,value] of expected) {
    assert.ok(css.includes(token + ': ' + value), 'Missing design token ' + token)
  }
  assert.match(css, /background: var\(--desktop-black-bg\) !important/)
  assert.doesNotMatch(css, /--central-noir-/)
})

test('no selector leaks into web/PWA or displays without native All Black class', () => {
  const app = read('./App.jsx')
  const dock = read('./DesktopDock.jsx')
  const mode = read('./desktopMode.mjs')
  assert.match(app, /if \(desktopMode\) import\('\.\/desktop-noir\.css'\)/)
  assert.match(app, /getDesktopAllBlackState\(window, desktopMode\)/)
  assert.match(app, /applyDesktopAllBlack\(document\.documentElement/)
  assert.match(mode, /bridge\?\.isDesktop === true/)
  assert.match(dock, /import '\.\/desktop-liquid-glass\.css'\s*\nimport '\.\/desktop-noir\.css'/)
  assert.doesNotMatch(app, /^import '\.\/desktop-noir\.css'/m)
  assert.doesNotMatch(read('./index.css'), /--desktop-black-bg/)
  assert.doesNotMatch(css, /(?:^|\n)\s*(?:html|body|#root|:root)\s*\{/m)
  const roots = [...css.matchAll(/(?:^|\n)(html\.central-desktop-shell[^\n{]*)/g)]
  assert.ok(roots.length > 30)
  assert.ok(roots.every(x => x[1].includes('.central-desktop-all-black')),
    'Every theme selector must require the desktop-only class and breakpoint guard')
})

test('every interface family gets the same tokens; pink Slime, chat and previews remain functional', () => {
  const selectors = [
    '.central-main', '.desktop-dock', '.central-drawer', '.bg-card', '.bg-panel',
    '.desktop-conversation', '.desktop-quick-composer', '.desktop-message-bubble',
    '.desktop-preview-sheet', '.desktop-update-popover', '.liquid-chat-composer',
    '.desktop-quick-mode-options', 'textarea,select', '.bg-sidebar',
    'table', '[role="dialog"]', '[role="tooltip"]', '[role="status"]',
    '::-webkit-scrollbar-thumb', '#root > main', '.cia-intro[data-theme="dark"]',
  ]
  for (const selector of selectors) {
    assert.ok(css.includes(selector), 'missing theme coverage: ' + selector)
  }
  assert.doesNotMatch(css, /desktop-slime-canvas|desktop-slime-button/)
  assert.match(read('./DesktopSlime.jsx'), /createOriginalPinkSlime/)
  const app = read('./App.jsx')
  assert.match(app, /desktopChatLayout\(/)
  assert.match(app, /nextAvatarChat\(/)
  assert.match(app, /page === 'chat' && !desktopMode/)
  assert.match(app, /desktop-preview-sheet/)
})

test('premium polish respects visible keyboard focus, semantic states and reduced motion', () => {
  assert.match(css, /:focus-visible/)
  assert.match(css, /outline: 2px solid var\(--desktop-black-accent\)/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/)
  assert.match(css, /@media \(forced-colors: active\)/)
  assert.match(css, /\/\* Reports, usage graphs, tables/)
  assert.doesNotMatch(css, /(?:\*\s*\{\s*filter:\s*grayscale)/)
})
