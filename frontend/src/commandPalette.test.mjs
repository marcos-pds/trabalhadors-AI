import test from 'node:test'
import assert from 'node:assert/strict'
import { chatCommands, matchingChatCommands } from './commandPalette.mjs'

test('central slash palette includes real navigation and protected actions', () => {
  const names = chatCommands.map(item => item.command)
  assert.equal(names.length, new Set(names).size)
  for (const name of ['/novo', '/previa', '/agentes', '/provedores',
    '/skills', '/plugins', '/integracoes', '/github', '/aprovar',
    '/rejeitar', '/computador', '/memoria', '/equipe']) {
    assert.ok(names.includes(name), name)
  }
})

test('typing slash returns grouped suggestions; typing ordinary text does not', () => {
  assert.ok(matchingChatCommands('/').length > 10)
  assert.deepEqual(matchingChatCommands('criar um app'), [])
  assert.ok(matchingChatCommands('/prov').some(item => item.command === '/provedores'))
  assert.ok(matchingChatCommands('/GITH').some(item => item.command === '/github'))
})

test('slash resource arguments are left untouched for the original approval flow', () => {
  assert.deepEqual(matchingChatCommands('/skill ativar minha-skill'), [])
  assert.deepEqual(matchingChatCommands('/plugin desativar teste'), [])
  assert.deepEqual(matchingChatCommands('/skills listar'), [])
})

test('no palette command reports fictitious workers or automatically enables autonomy', () => {
  assert.ok(chatCommands.every(item => !/simular|executar ficticiamente/i.test(item.command)))
  assert.equal(chatCommands.some(item => item.command === '/autonomia-on'), false)
})
