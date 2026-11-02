'use strict'
// Lifetime belongs to the ChildProcess handle; never discover/kill unrelated PIDs.
const { execFile } = require('node:child_process')
const path = require('node:path')
const stopping = new WeakMap()

function isRunning(proc) {
  return !!proc && Number.isSafeInteger(proc.pid) && proc.pid > 0 &&
    proc.exitCode === null && proc.signalCode === null
}

function waitForExit(proc, timeout) {
  if (!isRunning(proc) || typeof proc.once !== 'function') return Promise.resolve(!isRunning(proc))
  return new Promise(resolve => {
    let timer
    const finish = exited => {
      clearTimeout(timer)
      proc.removeListener('exit', onExit)
      resolve(exited)
    }
    const onExit = () => finish(true)
    proc.once('exit', onExit)
    timer = setTimeout(() => finish(!isRunning(proc)), timeout)
    // Exit can occur between the initial test and attaching the listener.
    if (!isRunning(proc)) finish(true)
  })
}

function stopOwnedBackend(proc, options = {}) {
  if (proc && stopping.has(proc)) return stopping.get(proc)
  if (!isRunning(proc)) return Promise.resolve({ attempted: false, reason: 'not_running' })
  const operation = stop(proc, options)
  stopping.set(proc, operation)
  return operation
}

async function stop(proc, options) {
  const platform = options.platform || process.platform
  const exec = options.execFile || execFile
  const wait = Number.isInteger(options.waitMs) && options.waitMs >= 0 ? Math.min(options.waitMs, 2000) : 1000
  if (platform !== 'win32') {
    try { proc.kill('SIGTERM') } catch (_) {}
    if (!await waitForExit(proc, wait) && isRunning(proc) && typeof proc.once === 'function') {
      try { proc.kill('SIGKILL') } catch (_) {}
      await waitForExit(proc, wait)
    }
    return { attempted: true, method: 'signal', stopped: !isRunning(proc) }
  }
  const pid = proc.pid
  const systemRoot = options.systemRoot || process.env.SystemRoot || process.env.WINDIR
  const fallback = () => { try { if (isRunning(proc)) proc.kill() } catch (_) {} }
  if (!systemRoot || !path.win32.isAbsolute(systemRoot) || /^[/\\]{2}/.test(systemRoot)) {
    fallback()
    await waitForExit(proc, wait)
    return { attempted: true, method: 'fallback_process_handle', stopped: !isRunning(proc) }
  }
  const taskkill = path.win32.join(systemRoot, 'System32', 'taskkill.exe')
  const method = await new Promise(resolve => {
    let settled = false
    const done = method => {
      if (settled) return
      settled = true
      resolve(method)
    }
    try {
      exec(taskkill, ['/PID', String(pid), '/T', '/F'], {
        windowsHide: true, timeout: 6000, shell: false,
      }, error => {
        if (error) fallback()
        done(error ? 'fallback_process_handle' : 'process_tree')
      })
    } catch (_) {
      fallback()
      done('fallback_process_handle')
    }
  })
  await waitForExit(proc, wait)
  return { attempted: true, method, stopped: !isRunning(proc) }
}

module.exports = { isRunning, stopOwnedBackend }
