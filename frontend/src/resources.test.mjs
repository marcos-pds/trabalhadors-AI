import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { buildSync } from 'esbuild'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createResourceClient, preflight, resourceKinds, searchMarketplace } from './resourceClient.mjs'

// Bundle JSX in memory; no DOM library, generated files, servers or user data.
const bundled = buildSync({ entryPoints: [fileURLToPath(new URL('./ResourcesPanel.jsx', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false, jsx: 'automatic',
  external: ['react', 'react/jsx-runtime'] }).outputFiles[0].text
const module = { exports: {} }
new Function('require', 'module', 'exports', bundled)(createRequire(import.meta.url), module, module.exports)
const { ImportReview } = module.exports

for (const [kind, name] of [['skill', 'SKILL.md'], ['skill', 'pack.zip'], ['vsix', 'example.vsix'], ['mcp', 'server.json']]) {
  test('accepts compatible local file: ' + name, () => assert.doesNotThrow(() => preflight(kind, name, 100)))
}
for (const [kind, name, size] of [['skill', 'code.vsix', 100], ['vsix', 'SKILL.md', 100],
  ['mcp', 'code.vsix', 100], ['mcp', 'server.json', 131073], ['skill', 'pack.zip', 1048577],
  ['vsix', 'big.vsix', 8388609], ['skill', '../SKILL.md', 100], ['skill', 'C:\\SKILL.md', 100],
  ['mcp', 'server.json', 0]]) {
  test('rejects incompatible/oversized/path input: ' + name + size, () => assert.throws(() => preflight(kind, name, size)))
}

test('preview never imports, activates or sends the local file to an external origin', async () => {
  const writes = [], uploads = []
  const client = createResourceClient(async (...args) => writes.push(args), async (...args) => {
    uploads.push(args); return { ok: true, json: async () => ({ preview_id: 'p', confirmation: 'h' }) }
  })
  const file = { name: 'example.vsix', size: 100 }
  const preview = await client.preview('vsix', file)
  assert.equal(uploads[0][0], '/api/resources/preview/vsix')
  assert.equal(uploads[0][1].body, file)
  assert.equal(uploads[0][1].headers['X-Central-Request'], '1')
  assert.equal(writes.length, 0)
  assert.throws(() => client.confirm(preview, false))
  await client.confirm(preview, true)
  assert.deepEqual(writes, [['/resources/previews/p/confirm', 'POST', { confirmation: 'h' }]])
})

test('backend validation errors are shown without an automatic confirmation or retry', async () => {
  let uploads = 0
  const client = createResourceClient(() => { throw Error('must not write') }, async () => {
    uploads++; return { ok: false, json: async () => ({ detail: 'Pacote inválido' }) }
  })
  await assert.rejects(() => client.preview('skill', { name: 'SKILL.md', size: 100 }), /Pacote inválido/)
  assert.equal(uploads, 1)
})

test('activation is separately confirmed and unavailable for VSIX and MCP', async () => {
  const calls = []
  const client = createResourceClient(async (...args) => calls.push(args))
  for (const kind of ['vsix', 'mcp']) assert.throws(() => client.state({ kind }, 'active', true))
  const resource = { id: 's', kind: 'skill', sha256: 'hash' }
  assert.throws(() => client.state(resource, 'active', false))
  await client.state(resource, 'active', true)
  await client.state(resource, 'revoked', true)
  assert.deepEqual(calls.map(x => x[2].state), ['active', 'revoked'])
  assert.ok(calls.every(x => x[2].confirmation === 'hash'))
})

test('Marketplace search requires explicit consent and sends only the query', async () => {
  const calls = []
  const api = async (...args) => { calls.push(args); return { items: [] } }
  assert.throws(() => searchMarketplace(api, 'python', false), /Autorize/)
  assert.throws(() => searchMarketplace(api, 'x', true), /2 e 100/)
  await searchMarketplace(api, '  python  ', true)
  assert.deepEqual(calls, [['/resources/marketplace/search', 'POST', { query: 'python', consent: true }]])
})

for (const kind of ['skill', 'vsix', 'mcp']) {
  test('review renders untrusted metadata as escaped text and requires consent: ' + kind, () => {
    const preview = { kind, sha256: 'digest', metadata: { name: '<script>alert(1)</script>',
      file_count: 10, execution_enabled: false, tools_verified: false } }
    const props = { preview, consent: false, busy: false, onConsent() {}, onConfirm() {}, onCancel() {} }
    const html = renderToStaticMarkup(React.createElement(ImportReview, props))
    assert.ok(html.includes('ainda não importado'))
    assert.ok(html.includes('&lt;script&gt;'))
    assert.ok(!html.includes('<script>'))
    assert.match(html, /disabled=""[^>]*>Confirmar importação inativa/)
    const accepted = renderToStaticMarkup(React.createElement(ImportReview, { ...props, consent: true }))
    assert.doesNotMatch(accepted, /disabled=""[^>]*>Confirmar importação inativa/)
    assert.ok(resourceKinds[kind].notice)
  })
}
