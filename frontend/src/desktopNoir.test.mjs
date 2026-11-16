import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = name => readFileSync(new URL(name, import.meta.url), 'utf8')
const noir = read('./desktop-noir.css')

test('true black design tokens and actual desktop application background', () => {
  assert.match(noir, /--central-noir-black:\s*#000000/)
  assert.match(noir, /--color-ink:\s*#000000/)
  assert.match(noir, /--color-panel:\s*#090909/)
  assert.match(noir, /--color-card:\s*#101010/)
  assert.match(noir, /\.central-main[\s\S]*?background:\s*#000000 !important/)
  assert.match(noir, /\.desktop-conversation-scroll\s*\{[\s\S]*?background:\s*#000 !important/)
})

test('noir CSS never affects browser/PWA and is loaded after glass in Electron', () => {
  const dock = read('./DesktopDock.jsx')
  const app = read('./App.jsx')
  const mode = read('./desktopMode.mjs')
  assert.match(dock, /import '\.\/desktop-liquid-glass\.css'\s*\nimport '\.\/desktop-noir\.css'/)
  assert.match(app, /if \(desktopMode\) import\('\.\/desktop-noir\.css'\)/)
  assert.match(mode, /bridge\?\.isDesktop === true/)
  assert.doesNotMatch(app, /^import '\.\/desktop-noir\.css'/m)
  assert.doesNotMatch(read('./index.css'), /central-noir-black/)
  // Every top-level Noir rule must be gated by the Electron preload class.
  assert.doesNotMatch(noir, /(?:^|\n)\s*(?:html|body|#root|\*|:root)\s*\{/m)
  assert.match(read('../../desktop/preload.cjs'), /classList\.add\('central-desktop-shell'\)/)
})

test('all main screens, component families and auxiliary login/intro are covered', () => {
  for (const selector of [
    '.desktop-dock', '.desktop-conversation', '.desktop-quick-composer',
    '.desktop-preview-sheet', '.desktop-update-popover', '.central-drawer',
    '.bg-card', '.bg-panel', '.bg-sidebar', '.flow-activity',
    '.reference-tools-menu', '.liquid-command-menu', '.liquid-chat-composer',
    'input:not([type="checkbox"])', 'textarea,select',
    'table', '[role="dialog"]', '[role="status"]',
    '#root > main', '.cia-intro[data-theme="dark"]',
  ]) {
    assert.ok(noir.includes(selector), 'Missing true-black component coverage: ' + selector)
  }
})

test('Slime stays original pink and chat behaviour remains three-stage with opt-in preview', () => {
  const slime = read('./DesktopSlime.jsx')
  const slimeModel = read('./originalPinkSlime.js')
  const app = read('./App.jsx')
  const dock = read('./DesktopDock.jsx')
  assert.match(slime, /createOriginalPinkSlime/)
  assert.match(slimeModel, /#f2577b/)
  assert.doesNotMatch(noir, /\.desktop-slime-(?:canvas|button)[\s\S]*?\{[\s\S]*?filter:/)
  assert.match(app, /desktopChatLayout\(/)
  assert.match(app, /nextAvatarChat\(/)
  assert.match(app, /page === 'chat' && !desktopMode/)
  assert.match(app, /desktop-preview-sheet/)
  assert.match(dock, /DesktopUpdateControl/)
})

test('black theme retains accessible focus states and avoids glowing outer frame', () => {
  assert.match(noir, /:focus-visible\s*\{[\s\S]*?outline:\s*2px solid rgba\(255,255,255/)
  assert.match(noir, /\.desktop-dock\s*\{[\s\S]*?box-shadow:\s*none !important/)
  assert.match(noir, /\.central-main[\s\S]*?box-shadow:\s*none !important/)
  assert.match(noir, /\.desktop-quick-composer[\s\S]*?box-shadow:\s*none !important/)
  assert.match(noir, /@media \(forced-colors: active\)/)
  assert.match(noir, /@media \(prefers-reduced-motion: reduce\)/)
})
