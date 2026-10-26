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
const { GitSkillImportControls, ImportReview, OfficialMcpImportButton,
  ResourceStatuses, VscodeInstallControls } = module.exports

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

test('activation is separately confirmed; only official pinned MCP is eligible', async () => {
  const calls = []
  const client = createResourceClient(async (...args) => calls.push(args))
  assert.throws(() => client.state({ kind: 'vsix' }, 'active', true))
  assert.throws(() => client.state({ kind: 'mcp', metadata: { name: 'untrusted' } }, 'active', true))
  await client.state({ id: 'mcp', kind: 'mcp', sha256: 'hash',
    metadata: { server_id: 'chrome-devtools', version: '1.0.1' } }, 'active', true)
  const resource = { id: 's', kind: 'skill', sha256: 'hash' }
  assert.throws(() => client.state(resource, 'active', false))
  await client.state(resource, 'active', true)
  await client.state(resource, 'revoked', true)
  assert.deepEqual(calls.map(x => x[2].state), ['active', 'active', 'revoked'])
  assert.ok(calls.every(x => x[2].confirmation === 'hash'))
})

test('official pinned DevTools manifest can be reviewed without granting filesystem access', () => {
  const html = renderToStaticMarkup(React.createElement(OfficialMcpImportButton, {
    busy: false, onPreview() {},
  }))
  assert.match(html, /Revisar manifesto oficial Chrome DevTools MCP 1\.0\.1/)
  assert.doesNotMatch(html, /disabled=/)
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

test('resource UI shows distinct status signals', () => {
  const item = { kind: 'skill', import_status: 'imported', validation_status: 'validated', enabled: true,
    associated: true, availability: 'requires_run_context' }
  const html = renderToStaticMarkup(React.createElement(ResourceStatuses, { item }))
  assert.match(html, /Importado/)
  assert.match(html, /Validado/)
  assert.match(html, /Habilitado/)
  assert.match(html, /Associado/)
  assert.match(html, /Disponibilidade depende da execu/)
})

test('VSIX installation UI identifies the target, installed status and separate uninstall action', () => {
  const selected = { metadata: { publisher: 'pub', name: 'extension', version: '1.2.3' } }
  const targets = [{ target_id: 'vscode-1', name: 'Visual Studio Code', version: '1.100.0',
    installed_extensions: [{ id: 'pub.extension', version: '1.0.0' }] }]
  const html = renderToStaticMarkup(React.createElement(VscodeInstallControls, { selected, targets,
    targetId: 'vscode-1', busy: false, result: null, onTarget() {}, onInstall() {}, onUninstall() {} }))
  assert.match(html, /Instalação explícita no VS Code/)
  assert.match(html, /Instalada neste destino: pub.extension@1.0.0/)
  assert.match(html, /Revisar instalação/)
  assert.match(html, /Revisar desinstalação/)
  assert.match(html, /privilégios da sua conta/)
})


test('Git import can preview a public URL without a saved connection', () => {
  const html = renderToStaticMarkup(React.createElement(GitSkillImportControls, {
    repositoryUrl: 'https://github.com/acme/public-skills', onRepositoryUrl() {},
    busy: false, action: null, onPreview() {}, authRequired: null, connections: [],
    onUseConnection() {}, token: '', onToken() {}, onConnect() {},
  }))
  assert.match(html, /Repositórios públicos são lidos sem token/)
  assert.match(html, /Buscar Skill e mostrar prévia/)
  assert.doesNotMatch(html, /disabled=""[^>]*>Buscar Skill e mostrar prévia/)
  assert.doesNotMatch(html, /Token GitHub de leitura/)
})

test('Git preview reports equivalent tool-specific Skill copies without importing duplicates', () => {
  const html = renderToStaticMarkup(React.createElement(ImportReview, {
    preview: { kind: 'skill', sha256: 'abc', metadata: { name: 'impeccable' },
      source: { provider: 'github', repository: 'pbakaus/impeccable', ref: 'main', commit: 'abc',
        skill_paths: ['.agent/skills/impeccable', 'skill'], identical_copies: true, scan_complete: false } },
    consent: false, busy: false, onConsent() {}, onConfirm() {}, onCancel() {},
  }))
  assert.match(html, /cópias idênticas de SKILL.md/)
  assert.match(html, /\.agent\/skills\/impeccable/)
  assert.match(html, /VSIX e configurações MCP continuam recursos separados/)
  assert.match(html, /lista pode não incluir todas as cópias/)
})

test('Git batch preview lists every Skill and confirms one atomic inactive import', () => {
  const html = renderToStaticMarkup(React.createElement(ImportReview, {
    preview: { kind: 'skill', batch: true, confirmation: 'token', preview_id: 'batch', skills: [
      { sha256: 'one', metadata: { name: 'design', version: '1.0.0' },
        source: { provider: 'github', repository: 'acme/tools', path: 'tools/design' } },
      { sha256: 'two', metadata: { name: 'review', version: '2.0.0' },
        source: { provider: 'github', repository: 'acme/tools', path: 'tools/review' } },
    ] },
    consent: false, busy: false, onConsent() {}, onConfirm() {}, onCancel() {},
  }))
  assert.match(html, /Prévia - 2 Skills ainda não importadas/)
  assert.match(html, /design - 1.0.0/)
  assert.match(html, /review - 2.0.0/)
  assert.match(html, /autorizo importar todas como privadas e inativas/)
  assert.match(html, /Confirmar importação das 2 Skills inativas/)
})

test('Git import offers a scoped connection after anonymous access is refused', () => {
  const html = renderToStaticMarkup(React.createElement(GitSkillImportControls, {
    repositoryUrl: 'https://github.com/acme/private-skills', onRepositoryUrl() {},
    busy: false, action: null, onPreview() {},
    authRequired: { provider: 'github', repository: 'acme/private-skills' },
    connections: [{ id: 'saved', service: 'github', repository: 'acme/private-skills' }],
    onUseConnection() {}, token: '', onToken() {}, onConnect() {},
  }))
  assert.match(html, /pode ser privado/)
  assert.match(html, /Tentar conexão salva: acme\/private-skills/)
  assert.match(html, /Conectar outra credencial/)
  assert.doesNotMatch(html, /Token GitHub fine-grained/)
  assert.doesNotMatch(html, /Conectar e continuar importação/)
})

test('instructions-only import discloses omitted files before consent', () => {
  const source = { import_mode: 'instructions_only', omitted_file_count: 52 }
  for (const preview of [
    {kind:'skill', metadata:{name:'impeccable'}, source},
    {kind:'skill', skills:[{metadata:{name:'impeccable'},source}]},
  ]) {
    const html = renderToStaticMarkup(React.createElement(ImportReview, {
      preview, consent:false, busy:false,
    }))
    assert.match(html, /52/)
    assert.match(html, /Somente as instruções/)
    assert.match(html, /não estarão disponíveis/)
    assert.match(html, /disabled/)
  }
})
