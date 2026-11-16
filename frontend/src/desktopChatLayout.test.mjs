import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { desktopChatLayout, nextAvatarChat, afterSuccessfulSend } from './desktopChatLayout.mjs'

const file = filename => readFileSync(new URL(filename, import.meta.url), 'utf8')

test('avatar click opens only floating composer, and second click closes it', () => {
  const initial = {page: 'chat', expanded: false, composerOpen: false}
  const opened = nextAvatarChat(initial)
  assert.deepEqual(opened, {page: 'chat', expanded: false, composerOpen: true})
  assert.equal(desktopChatLayout({authenticated:true, ...opened}), 'compose')
  assert.deepEqual(nextAvatarChat(opened), initial)
  assert.equal(desktopChatLayout({authenticated:true, ...initial}), 'dock')
})

test('avatar returns from any workspace to compact input instead of fullscreen chat', () => {
  assert.deepEqual(nextAvatarChat({page:'dashboard',expanded:true,composerOpen:false}),
    {page:'chat',expanded:false,composerOpen:true})
  assert.deepEqual(nextAvatarChat({page:'chat',expanded:true,composerOpen:false}),
    {page:'chat',expanded:false,composerOpen:false})
})

test('conversation is revealed only following a successful send', () => {
  const composition = {expanded:false,composerOpen:true}
  const accepted = afterSuccessfulSend({desktopMode:true,...composition})
  assert.deepEqual(accepted,{expanded:true,composerOpen:false})
  assert.equal(desktopChatLayout({authenticated:true,page:'chat',...accepted}), 'full')
  assert.deepEqual(afterSuccessfulSend({desktopMode:false,...composition}),composition)
  assert.equal(desktopChatLayout({authenticated:false,page:'chat',...composition}), 'full')
})

test('native Electron window has three height states and rejects unknown IPC layouts', () => {
  const main = file('../../desktop/main.cjs')
  const preload = file('../../desktop/preload.cjs')
  assert.match(main, /layout === 'compose' \? Math\.min\(184/)
  assert.match(main, /\['dock', 'compose', 'full'\]\.includes\(layout\)/)
  assert.match(preload, /setLayout\(layout\)/)
  assert.match(preload, /\['dock', 'compose', 'full'\]\.includes\(layout\)/)
})

test('the central orbit is not rendered in desktop empty chat but web remains unchanged', () => {
  const app = file('./App.jsx')
  const composer = file('./DesktopChatPrompt.jsx')
  const css = file('./desktop-liquid-glass.css')
  assert.match(app, /hideWelcome=\{desktopMode\}/)
  assert.match(app, /hideWelcome \? null : <ChatWelcome/)
  assert.match(app, /desktopComposerOpen && page === 'chat' && !desktopExpanded/)
  assert.match(app, /onSend=\{sendMessage\}/)
  assert.match(composer, /DesktopGlassSurface/)
  assert.match(composer, /LiquidGlassUnderlay/)
  assert.match(composer, /onSubmit=\{event =>/)
  assert.match(css, /html\.central-desktop-shell \.central-desktop-mode \.desktop-prompt-only/)
  assert.doesNotMatch(app, /import '\.\/DesktopChatPrompt\.jsx'/)
})
