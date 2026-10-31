import test from 'node:test'
import assert from 'node:assert/strict'
import { loadMotionCapabilities, motionCapabilityRows } from './motionStudio.mjs'

function inventory() {
  return Object.fromEntries([
    ['comfyui_wan', 'generate'], ['remotion', 'compose'],
    ['whisperx', 'transcribe'], ['ffmpeg', 'encode'],
  ].map(([id, stage]) => [id, {
    stage, contract_implemented: true, installed: false, version: null,
    version_source: null, service_status: 'pending', execution_supported: false,
    endpoint_configured: false,
  }]))
}

test('real backend shape maps to four pending services, never completed renders', () => {
  const rows = motionCapabilityRows(inventory())
  assert.deepEqual(rows.map(row => row.id), ['comfyui_wan', 'remotion', 'whisperx', 'ffmpeg'])
  assert.ok(rows.every(row => row.installation === 'Não detectado'))
  assert.ok(rows.every(row => row.contract === 'Implementado'))
  assert.ok(rows.every(row => row.verification === 'Não verificado'))
  assert.ok(rows.every(row => row.rendering === 'Serviço pendente'))
  assert.ok(rows.every(row => row.execution === 'Execução indisponível'))
})

test('installed runtime and metadata version do not imply verification', () => {
  const data = inventory()
  Object.assign(data.whisperx, { installed: true, version: '3.1.0', version_source: 'package_metadata' })
  const row = motionCapabilityRows(data).find(row => row.id === 'whisperx')
  assert.equal(row.installation, 'Detectado no servidor')
  assert.equal(row.version, '3.1.0')
  assert.match(row.versionSource, /sem teste de execução/)
  assert.equal(row.verification, 'Não verificado')
  assert.equal(row.rendering, 'Serviço pendente')
  assert.equal(motionCapabilityRows(data).find(row => row.id === 'ffmpeg').version, 'Não descoberta')
})

test('configured endpoint does not imply connectivity or installed runtime', () => {
  const data = inventory()
  assert.match(motionCapabilityRows(data)[0].endpoint, /não configurado/)
  data.comfyui_wan.endpoint_configured = true
  const row = motionCapabilityRows(data)[0]
  assert.equal(row.endpoint, 'Endpoint configurado; conexão não verificada')
  assert.equal(row.installed, false)
  assert.equal(row.verification, 'Não verificado')
})

test('unexpected service state or extra claims cannot become a verified render', () => {
  const data = inventory()
  Object.assign(data.ffmpeg, { installed: true, service_status: 'completed', execution_supported: true, verified: true })
  const row = motionCapabilityRows(data).find(row => row.id === 'ffmpeg')
  assert.equal(row.rendering, 'Estado do serviço não reconhecido')
  assert.equal(row.verification, 'Não verificado')
  assert.equal(row.execution, 'Suporte declarado; execução não verificada')
})

test('contract not implemented remains separate from installed', () => {
  const data = inventory()
  Object.assign(data.ffmpeg, { installed: true, contract_implemented: false })
  assert.equal(motionCapabilityRows(data)[3].contract, 'Não implementado')
  assert.equal(motionCapabilityRows(data)[3].installation, 'Detectado no servidor')
})

test('malformed or incomplete responses are rejected instead of fabricated absence', () => {
  for (const bad of [null, [], {}, { detail: 'Login required' }]) {
    assert.throws(() => motionCapabilityRows(bad), /inventário Motion inválido/)
  }
  for (const change of [
    { installed: 'false' }, { stage: 'encode' }, { execution_supported: null },
    { version: {} }, { version_source: 'guess' }, { endpoint_configured: undefined },
  ]) {
    const data = inventory()
    Object.assign(data.remotion, change)
    assert.throws(() => motionCapabilityRows(data), /inventário Motion inválido/)
  }
})

test('loader calls only the existing GET endpoint through the shared api prefix', async () => {
  const calls = []
  const rows = await loadMotionCapabilities(async (...args) => { calls.push(args); return inventory() })
  assert.deepEqual(calls, [['/motion/capabilities', 'GET']])
  assert.equal(rows.length, 4)
})

test('HTTP errors and invalid responses reach the reload/error UI', async () => {
  await assert.rejects(loadMotionCapabilities(async () => { throw new Error('Modo local obrigatório') }), /Modo local/)
  await assert.rejects(loadMotionCapabilities(async () => ({})), /inventário Motion inválido/)
  await assert.rejects(loadMotionCapabilities(() => { throw new Error('Sessão expirada') }), /Sessão expirada/)
})

test('hung request times out and a subsequent reload can succeed', async () => {
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  await assert.rejects(loadMotionCapabilities(() => pending, 10), /demorou demais/)
  const rows = await loadMotionCapabilities(async () => inventory())
  assert.equal(rows.length, 4)
  finish({}) // A late response cannot change the already rejected request.
})
