import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = filename => readFileSync(new URL(filename, import.meta.url), 'utf8')

test('desktop conversation is separate from legacy web ChatPage', () => {
  const app = read('./App.jsx')
  const desktop = read('./DesktopConversation.jsx')
  assert.match(app, /page === 'chat' && desktopMode && <div className="desktop-chat-stage"/)
  assert.match(app, /page === 'chat' && !desktopMode && <div className="flex h-full min-h-0/)
  assert.match(desktop, /desktop-conversation-header/)
  assert.match(desktop, /desktop-conversation-scroll/)
  assert.match(desktop, /DesktopChatPrompt embedded/)
  assert.doesNotMatch(desktop, /<ChatPage|<LiveAgentOrbit|<ChatWelcome/)
})

test('desktop preview is opt-in, limited to a sheet and never opened after submit', () => {
  const app = read('./App.jsx')
  const css = read('./desktop-liquid-glass.css')
  assert.match(app, /desktop-preview-sheet/)
  assert.match(app, /onTogglePreview=\{\(\) => setExecutionPanelOpen\(open => !open\)\}/)
  assert.match(app, /setInspectedRun\(run\.id\);setExecutionPanelOpen\(!desktopMode\);setSteps/)
  assert.match(app, /setInspectedRun\(run\.id\);setExecutionPanelOpen\(!desktopMode\);try\{/)
  assert.match(app, /setExecutionPanelOpen\(!desktopMode && Boolean\(needsAttention\)\)/)
  assert.match(css, /\.desktop-preview-sheet\s*\{/)
  assert.match(css, /width: clamp\(350px, 51%, 530px\)/)
  assert.match(css, /\.desktop-preview-sheet-body > aside/)
  assert.match(css, /width: 100% !important/)
  assert.doesNotMatch(app, /setInspectedRun\(run\.id\);setExecutionPanelOpen\(true\);setSteps/)
})

test('compact composer is a single readable rdev Liquid Glass surface', () => {
  const composer = read('./DesktopChatPrompt.jsx')
  const css = read('./desktop-liquid-glass.css')
  assert.match(composer, /DesktopGlassSurface className="desktop-quick-rdev-glass"/)
  assert.doesNotMatch(composer, /LiquidGlassUnderlay/)
  assert.match(composer, /onUpload\(file\)/)
  assert.doesNotMatch(composer, /fetch\('\/api\/uploads\/text'/)
  assert.match(css, /\.desktop-quick-input-row > textarea\.desktop-quick-field/)
  assert.match(css, /-webkit-text-fill-color: #fcfdff !important/)
  assert.match(css, /rgba\(16,25,42,\.97\)/)
  assert.match(css, /\.desktop-prompt-only\.is-embedded/)
})

test('the original web chat, web preview and native pink Slime remain unchanged', () => {
  const app = read('./App.jsx')
  const dock = read('./DesktopDock.jsx')
  const slime = read('./DesktopSlime.jsx')
  assert.match(app, /<ChatPage data=\{data\}/)
  assert.match(app, /executionPanelOpen && <><div role="separator"/)
  assert.match(dock, /DesktopSlime/)
  assert.match(slime, /createOriginalPinkSlime/)
})
