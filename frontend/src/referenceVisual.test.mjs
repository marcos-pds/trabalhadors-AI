import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const load = name => readFileSync(new URL('./' + name, import.meta.url),'utf8')

test('reference artwork has the exact supplied SVG motifs and brand gradients', () => {
  const source = load('ReferenceIcons.jsx')
  for (const token of [
    'M12 2a4.5', 'M12 1L14.2', 'M2 12c2-4', 'M18.178 8c5.096',
    'M3 4h4v4H3V4z', '#10a37f', '#d97757', '#3b82f6',
    '#0ea5e9', '#f59e0b', '#4facfe', '#a18cd1', '#fbc2eb',
    'coreGradLight', 'ellipse cx="50" cy="50" rx="42" ry="18"',
  ]) assert.ok(source.includes(token), 'reference token: ' + token)
})

test('Ice White background and glass pill use reference colors and dimensions', () => {
  const css = load('index.css')
  for (const token of [
    '#f0f4f8', '#f8fafc', '#e2e8f0', '#334155', '#0f172a',
    '#fb923c', 'width:320px;height:320px', 'width:180px;height:180px',
    'border-radius:9999px', 'reference-glass-core',
    'reference-send-button', 'reference-orbit-satellite',
  ]) assert.ok(css.includes(token), 'css token: ' + token)
})

test('visual fidelity does not replace protected Central tasks with simulation', () => {
  const app = load('App.jsx')
  assert.ok(app.includes('reference-send-button'))
  assert.ok(app.includes('setAutonomous(e.target.checked)'))
  assert.ok(app.includes('window.confirm('))
  assert.ok(app.includes('onWorkspaceApproval('))
  assert.ok(app.includes('EventSource('))
  assert.ok(app.includes("matchingChatCommands(prompt)"))
  assert.ok(!app.includes('triggerPageBuildSimulation'))
  assert.ok(!app.includes('Tarefa executada. Sincronizado localmente.'))
  const orbit = load('LiquidGlassUI.jsx')
  assert.ok(orbit.includes("['openai', 'openai_chatgpt', 'codex_cli']"))
  assert.ok(orbit.includes('ícone de referência; não conectado'))
})
