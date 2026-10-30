'use strict'

// Stop only the Python process owned by this Electron instance.
// On Windows, killing the PyInstaller parent alone can leave a worker/child
// process holding the database and port. taskkill /T targets that process tree.
const { execFile } = require('node:child_process')

function isRunning(proc) {
  return !!proc && Number.isSafeInteger(proc.pid) && proc.pid > 0 &&
    proc.exitCode === null && proc.signalCode === null
}

function stopOwnedBackend(proc, options = {}) {
  const platform = options.platform || process.platform
  const exec = options.execFile || execFile
  if (!isRunning(proc)) return Promise.resolve({ attempted: false, reason: 'not_running' })
  if (platform !== 'win32') {
    try { proc.kill('SIGTERM') } catch (_) {}
    return Promise.resolve({ attempted: true, method: 'signal' })
  }
  const pid = proc.pid
  return new Promise(resolve => {
    let settled = false
    const done = (method) => {
      if (settled) return
      settled = true
      resolve({ attempted: true, method })
    }
    try {
      exec('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
        windowsHide: true, timeout: 6000,
      }, (error) => {
        if (error) {
          // Fallback to the process handle, never an arbitrary PID.
          try { if (isRunning(proc)) proc.kill() } catch (_) {}
        }
        done(error ? 'fallback_process_handle' : 'process_tree')
      })
    } catch (_) {
      try { if (isRunning(proc)) proc.kill() } catch (_) {}
      done('fallback_process_handle')
    }
  })
}

module.exports = { isRunning, stopOwnedBackend }
