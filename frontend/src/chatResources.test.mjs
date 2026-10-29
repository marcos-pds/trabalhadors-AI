import test from 'node:test'
import assert from 'node:assert/strict'
import { parseResourceCommand, matchingResources, setChatResourceState } from './chatResources.mjs'

test('slash commands parse list, activation and deactivation without invoking AI', () => {
  assert.deepEqual(parseResourceCommand('/skills'), {kind:'skill', action:'listar', query:''})
  assert.deepEqual(parseResourceCommand('/skill ativar impeccable'), {kind:'skill', action:'ativar', query:'impeccable'})
  assert.deepEqual(parseResourceCommand('/PLUGINS DESATIVAR Chrome DevTools'), {kind:'plugin', action:'desativar', query:'Chrome DevTools'})
  assert.equal(parseResourceCommand('/skills-unknown'), null)
  assert.equal(parseResourceCommand('ative /skills'), null)
})

test('resource matching preserves ambiguities and separates skills from plugins', () => {
  const rows = [{id:'one',kind:'skill',metadata:{name:'Design'}}, {id:'two',kind:'skill',metadata:{name:'Design'}}, {id:'mcp',kind:'mcp',metadata:{name:'Design'}}]
  assert.equal(matchingResources(rows, parseResourceCommand('/skill ativar Design')).length, 2)
  assert.equal(matchingResources(rows, parseResourceCommand('/plugin ativar Design'))[0].id, 'mcp')
  assert.equal(matchingResources(rows, parseResourceCommand('/skill ativar one'))[0].id, 'one')
})

const scope = {target_kind:'project', target_id:'project', label:'Projeto atual'}
const skill = {id:'s',kind:'skill',sha256:'fresh-digest',state:'inactive',metadata:{name:'Design'}}
function mockApi(resource, failBinding = false) {
  const calls = []
  return {calls, api: async (path, method, payload) => {
    calls.push({path,method,payload})
    if (failBinding && path.endsWith('/bindings')) throw new Error('Destino não autorizado')
    return resource
  }}
}

test('activation reads a fresh digest, binds the destination and uses the guarded state endpoint', async () => {
  const {api,calls} = mockApi(skill)
  const message = await setChatResourceState(api, {id:'s',sha256:'stale'}, true, scope)
  assert.match(message, /ativa e associada/)
  assert.deepEqual(calls.map(c => c.path), ['/resources/s','/resources/s/bindings','/resources/s/state'])
  assert.deepEqual(calls[2].payload, {state:'active',confirmation:'fresh-digest'})
})

test('an unspecified or rejected destination never activates a skill globally', async () => {
  const noScope = mockApi(skill)
  await assert.rejects(() => setChatResourceState(noScope.api, skill, true), /Escolha/)
  assert.equal(noScope.calls.length, 1)
  const denied = mockApi(skill, true)
  await assert.rejects(() => setChatResourceState(denied.api, skill, true, scope), /não autorizado/)
  assert.ok(!denied.calls.some(c => c.path.endsWith('/state')))
})

test('deactivation removes only this skill binding and preserves other projects', async () => {
  const {api,calls} = mockApi({...skill,state:'active'})
  await setChatResourceState(api, skill, false, scope)
  assert.equal(calls.length, 2)
  assert.deepEqual(calls[1].payload, {target_kind:'project',target_id:'project',enabled:false})
})

test('only the official supported MCP can be activated; VSIX is not silently installed', async () => {
  const mcp = {id:'m',kind:'mcp',sha256:'mhash',state:'inactive',metadata:{name:'DevTools',server_id:'chrome-devtools',version:'1.0.1'}}
  const supported = mockApi(mcp)
  await setChatResourceState(supported.api, mcp, true)
  assert.deepEqual(supported.calls[1].payload, {state:'active',confirmation:'mhash'})
  const unsupported = mockApi({...mcp,metadata:{name:'other'}})
  await assert.rejects(() => setChatResourceState(unsupported.api, mcp, true), /Somente o Chrome/)
  assert.equal(unsupported.calls.length, 1)
  const vsix = mockApi({id:'v',kind:'vsix'})
  await assert.rejects(() => setChatResourceState(vsix.api, {id:'v'}, true), /instalação/)
  assert.equal(vsix.calls.length, 1)
})
