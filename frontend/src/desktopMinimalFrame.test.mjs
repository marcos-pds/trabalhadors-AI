import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = name => readFileSync(new URL(name, import.meta.url), 'utf8')

test('default automatic mode has no visible Auto label or framed select in desktop chat', () => {
  const composer = read('./DesktopChatPrompt.jsx')
  const modeSection = composer.slice(composer.indexOf('className="desktop-quick-mode-picker"'))
  assert.match(composer, /mode !== 'auto' && <span className="desktop-quick-mode-active">/)
  assert.match(composer, /\{showModes && <div id="desktop-quick-mode-options"/)
  assert.match(modeSection, /setMode\(value\)/)
  assert.match(modeSection, /'auto','Auto'/)
  assert.doesNotMatch(modeSection, /className="desktop-quick-mode-label"/)
  assert.doesNotMatch(modeSection, /<select aria-label="Modo de execução"/)
  assert.match(modeSection, /aria-expanded=\{showModes\}/)
})

test('mode popup is not clipped by rounded composer, and is accessible in expanded chat', () => {
  const composer = read('./DesktopChatPrompt.jsx')
  const css = read('./desktop-liquid-glass.css')
  const composerEnd = composer.indexOf('</form>\n    </div>')
  const optionsPos = composer.indexOf('{showModes && <div id="desktop-quick-mode-options"')
  assert.ok(optionsPos > composerEnd, 'the mode popup must be a sibling of the clipped composer')
  assert.match(css, /\.desktop-prompt-only\.is-embedded \.desktop-quick-mode-options/)
  assert.match(css, /bottom: calc\(100% \+ 8px\)/)
  assert.match(composer, /document\.addEventListener\('pointerdown', closeOnOutside\)/)
  assert.match(composer, /document\.addEventListener\('keydown', closeOnEscape, true\)/)
})

test('only Electron desktop removes frames and dark shadows; Liquid Glass remains', () => {
  const css = read('./desktop-liquid-glass.css')
  const desktop = read('./desktop.css')
  const app = read('./App.jsx')
  const snippet = css.slice(css.indexOf('Desktop visual cleanup: remove the outlined frame'))
  assert.ok(snippet.length > 2500, 'missing desktop-only cleanup overrides')
  assert.match(snippet, /html\.central-desktop-shell \.central-desktop-mode \.desktop-dock/)
  assert.match(snippet, /\.desktop-dock::before/)
  assert.match(snippet, /\.central-main[\s\S]*?box-shadow: none !important/)
  assert.match(snippet, /\.desktop-quick-composer[\s\S]*?border: 0 !important;[\s\S]*?box-shadow: none !important/)
  assert.match(snippet, /\.desktop-quick-rdev-glass/)
  assert.match(desktop, /\.central-desktop-mode/)
  assert.match(app, /lazy\(\(\) => import\('\.\/DesktopDock\.jsx'\)\)/)
  assert.doesNotMatch(app, /^import '\.\/desktop-liquid-glass\.css'/m)
})

test('window itself has no operating system shadow', () => {
  const main = read('../../desktop/main.cjs')
  assert.match(main, /transparent: true/)
  assert.match(main, /hasShadow: false/)
  assert.match(main, /backgroundColor: '#00000000'/)
})
