import test from 'node:test'
import assert from 'node:assert/strict'
import { pauseLimitKey } from './pauseLimit.mjs'

test('only a checkpoint limit pause triggers the continuation popup', () => {
  for (const status of ['queued','running','completed','failed','cancelled','awaiting_approval']) {
    assert.equal(pauseLimitKey({run_id:'r',status,updated_at:'now'}), null)
  }
  assert.equal(pauseLimitKey(null), null)
  assert.equal(pauseLimitKey({run_id:'r',status:'paused_limit',updated_at:'first'}), 'r:first')
})

test('repeated polls identify the same pause, but a subsequent pause can prompt again', () => {
  const pause = {run_id:'r',status:'paused_limit',updated_at:'first'}
  assert.equal(pauseLimitKey(pause), pauseLimitKey({...pause}))
  assert.notEqual(pauseLimitKey(pause), pauseLimitKey({...pause,updated_at:'second'}))
  assert.notEqual(pauseLimitKey(pause), pauseLimitKey({...pause,run_id:'other'}))
})
