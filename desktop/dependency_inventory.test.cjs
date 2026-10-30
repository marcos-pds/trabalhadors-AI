'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const { inventory, filePresent, summary, COMPONENTS } = require('./dependency_inventory.cjs')

test('read-only inventory never launches commands or verifies credentials', () => {
  const found = new Set([
    path.join('C:\\', 'tools', 'git.exe'),
    path.join('C:\\', 'tools', 'ffmpeg.exe'),
  ])
  const fs = {
    lstatSync(name) {
      if (!found.has(name)) throw new Error('missing')
      return { isFile: () => true, isSymbolicLink: () => false }
    },
  }
  const env = { PATH: 'C:\\tools', OPENAI_API_KEY: 'must-not-leak' }
  const report = inventory(env, fs)
  assert.equal(report.installs_performed, 0)
  assert.equal(report.dependencies.find(d => d.id === 'git').status, 'found_on_path')
  assert.equal(report.dependencies.find(d => d.id === 'ollama').status, 'not_found_on_path')
  assert.equal(report.dependencies.find(d => d.id === 'models').status, 'not_checked')
  assert.ok(report.dependencies.every(d => d.verified === false))
  assert.ok(!JSON.stringify(report).includes('must-not-leak'))
  assert.ok(!summary(report).includes('must-not-leak'))
})

test('symbolic links and folders are not classified as binaries', () => {
  const fake = { lstatSync: () => ({ isFile: () => false, isSymbolicLink: () => true }) }
  assert.equal(filePresent('git.exe', ['C:\\tools'], fake), false)
})

test('catalog IDs are stable, distinct and include optional AI and video tools', () => {
  const report = inventory({ PATH: '' })
  const ids = report.dependencies.map(d => d.id)
  assert.equal(new Set(ids).size, ids.length)
  for (const id of ['ollama','codex','claude','gemini','opencode',
                    'ffmpeg','playwright','comfyui','browser_mcp']) {
    assert.ok(ids.includes(id))
  }
  assert.ok(COMPONENTS.every(c => c.files.every(f => !f.includes('..'))))
})

test('PATH entries that are relative never become a working directory probe', () => {
  const checked = []
  const fs = { lstatSync: name => { checked.push(name); throw new Error('none') } }
  inventory({ PATH: '.;..;node_modules;.\\bin' }, fs)
  assert.deepEqual(checked, [])
})
