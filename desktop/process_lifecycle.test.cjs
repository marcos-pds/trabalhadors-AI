'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { isRunning, stopOwnedBackend } = require('./process_lifecycle.cjs')

function fake(pid = 1234) {
  return { pid, exitCode: null, signalCode: null, killed: false,
    kill() { this.killed = true } }
}

test('Windows shuts down only the owned backend tree, without shell', async () => {
  const child = fake()
  let invocation = null
  const result = await stopOwnedBackend(child, {
    platform: 'win32',
    execFile(cmd, args, opts, callback) {
      invocation = { cmd, args, opts }
      callback(null)
    },
  })
  assert.equal(invocation.cmd, 'taskkill.exe')
  assert.deepEqual(invocation.args, ['/PID', '1234', '/T', '/F'])
  assert.equal(invocation.opts.windowsHide, true)
  assert.equal(result.method, 'process_tree')
})

test('Failed Windows taskkill falls back to owned process handle', async () => {
  const child = fake()
  const result = await stopOwnedBackend(child, {
    platform: 'win32',
    execFile(_cmd, _args, _opts, callback) { callback(new Error('missing taskkill')) },
  })
  assert.equal(child.killed, true)
  assert.equal(result.method, 'fallback_process_handle')
})

test('Exited or invalid child never invokes taskkill or kill', async () => {
  let calls = 0
  for (const child of [null, { pid: 0, exitCode: null, signalCode: null },
    { pid: 123, exitCode: 0, signalCode: null },
    { pid: 123, exitCode: null, signalCode: 'SIGTERM' }]) {
    assert.equal(isRunning(child), false)
    const output = await stopOwnedBackend(child, {
      platform: 'win32',
      execFile() { calls++ },
    })
    assert.equal(output.attempted, false)
  }
  assert.equal(calls, 0)
})

test('POSIX uses child handle rather than operating on a PID', async () => {
  const child = fake()
  const report = await stopOwnedBackend(child, { platform: 'linux' })
  assert.equal(child.killed, true)
  assert.equal(report.method, 'signal')
})

test('synchronous taskkill failure still closes the owned process', async () => {
  const child = fake()
  const report = await stopOwnedBackend(child, {
    platform: 'win32',
    execFile() { throw new Error('cannot spawn') },
  })
  assert.equal(child.killed, true)
  assert.equal(report.method, 'fallback_process_handle')
})
