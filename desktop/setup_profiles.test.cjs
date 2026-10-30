'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { inventory } = require('./dependency_inventory.cjs')
const { PROFILES, planFor, planText } = require('./setup_profiles.cjs')

test('all plan profiles use known components and never mark runtime verified', () => {
  const known = inventory({ PATH: '' })
  for (const profile of PROFILES) {
    const plan = planFor(profile.id, known)
    assert.equal(plan.profile, profile.id)
    assert.equal(plan.ready_to_install, false)
    assert.equal(plan.installs_performed, 0)
    assert.ok(plan.components.length >= 2)
    assert.ok(plan.components.every(x => !x.verified && !x.installable))
    assert.ok(planText(plan).includes('Não'))
  }
})

test('a binary on PATH is still not a certified or installable component', () => {
  const scan = inventory({ PATH: '' })
  scan.dependencies.find(x => x.id === 'git').status = 'found_on_path'
  const result = planFor('essential', scan)
  assert.equal(result.components.find(x => x.id === 'git').state, 'found_on_path')
  assert.equal(result.components.find(x => x.id === 'git').verified, false)
  assert.equal(result.ready_to_install, false)
})

test('unknown profile and invalid inventory are rejected without any side effects', () => {
  assert.throws(() => planFor('arbitrary_command', inventory({ PATH: '' })), RangeError)
  assert.throws(() => planFor('essential', null), TypeError)
})
