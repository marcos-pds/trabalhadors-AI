'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const vm = require('node:vm')
const source = fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8')

async function harness(options = {}) {
  const trace = { paths: {}, windows: [], quits: 0, dialogs: [], stops: 0, spawned: [] }
  const app = new EventEmitter()
  app.isPackaged = !!options.packaged
  app.setName = name => { trace.name = name }
  app.setAppUserModelId = () => {}
  app.getPath = name => trace.paths[name] || path.join(os.tmpdir(), 'central-desktop-unit-' + name)
  app.setPath = (name, value) => { trace.paths[name] = value }
  app.requestSingleInstanceLock = () => {
    trace.lockData = trace.paths.userData
    return options.instanceLock !== false
  }
  app.quit = () => { trace.quits++ }
  app.whenReady = () => Promise.resolve()
  class Window extends EventEmitter {
    constructor(config) {
      super(); this.config = config; this.webContents = new EventEmitter()
      this.webContents.setWindowOpenHandler = handler => { this.openHandler = handler }
      trace.windows.push(this)
    }
    loadURL(url) { this.url = url; queueMicrotask(() => this.emit('ready-to-show')); return Promise.resolve() }
    isDestroyed() { return !!this.destroyed }
    isMinimized() { return true }
    restore() { this.restored = true }
    focus() { this.focused = true }
    show() { this.shown = true }
    setTitle(title) { this.title = title }
    reload() { this.reloaded = true }
    close() { this.destroyed = true; this.emit('closed') }
  }
  const handlers = {}
  const appSession = {
    webRequest: Object.fromEntries(['onBeforeRequest', 'onBeforeSendHeaders', 'onHeadersReceived']
      .map(name => [name, fn => { handlers[name] = fn }])),
    on() {}, setPermissionRequestHandler(fn) { this.permission = fn },
    setPermissionCheckHandler(fn) { this.permissionCheck = fn },
    async fetch(url, config) {
      trace.fetch = { url, config }
      return new Response(JSON.stringify({ connected: false, connection: null }))
    },
  }
  const child = new EventEmitter()
  Object.assign(child, { pid: 123, exitCode: null, signalCode: null,
    stdout: new EventEmitter(), stderr: new EventEmitter(), kill() { this.exitCode = 0 } })
  let finishStop
  const stop = () => {
    trace.stops++
    if (options.holdStop) return new Promise(resolve => { finishStop = () => { child.exitCode = 0; resolve() } })
    child.exitCode = 0
    return Promise.resolve()
  }
  const fakeFS = {
    existsSync(file) { return file.endsWith('desktop-dependencies-reviewed-v1') ? !!options.marker : true },
    mkdirSync() {}, writeFileSync() {},
  }
  const electron = { app, BrowserWindow: Window, session: { fromPartition(partition) { trace.partition = partition; return appSession } },
    Menu: { buildFromTemplate: x => x, setApplicationMenu() {} },
    dialog: { async showMessageBox(...args) { trace.dialogs.push(args); return { response: 0 } },
      showErrorBox(...args) { trace.error = args } },
    shell: { async openExternal(url) { trace.external = url }, async openPath() {} },
  }
  const mockRequire = name => {
    if (name === 'electron') return electron
    if (name === 'node:fs') return fakeFS
    if (name === 'node:child_process') return { spawn(executable, args, config) {
      trace.spawned.push({ executable, args, config })
      queueMicrotask(() => child.stdout.emit('data', Buffer.from('CENTRAL_DESKTOP_READY=http://127.0.0.1:41001/\n')))
      return child
    } }
    if (name === 'node:http') return { get(config, receive) {
      trace.health = config
      const req = new EventEmitter(); req.destroy = err => req.emit('error', err)
      queueMicrotask(() => {
        const res = new EventEmitter(); res.statusCode = options.badHealth ? 503 : 200
        receive(res)
        res.emit('data', Buffer.from(JSON.stringify({ status: options.badHealth ? 'unavailable' : 'ready', database: 'ready' })))
        res.emit('end')
      })
      return req
    } }
    if (name === './process_lifecycle.cjs') return { isRunning: c => c?.exitCode === null, stopOwnedBackend: stop }
    if (name.startsWith('./')) return require(path.join(__dirname, name))
    return require(name)
  }
  const sandbox = { require: mockRequire, __dirname, Buffer, URL, AbortSignal,
    setTimeout, clearTimeout, setInterval: () => ({}), clearInterval() {},
    process: { platform: 'win32', resourcesPath: path.join(os.tmpdir(), 'resources'),
      env: { CENTRAL_DESKTOP_USER_DATA: path.join(os.tmpdir(), 'central-desktop-unit-isolated'),
        CENTRAL_DESKTOP_SKIP_WELCOME: '1' } },
  }
  vm.runInNewContext(source, sandbox, { filename: 'main.cjs' })
  await new Promise(resolve => setImmediate(resolve))
  return { trace, app, handlers, child, appSession, electron, finishStop: () => finishStop() }
}

test('data override precedes instance lock; renderer session and backend data stay desktop-only', async () => {
  const { trace, appSession } = await harness()
  assert.equal(trace.name, 'Central IA')
  assert.equal(trace.lockData, path.join(os.tmpdir(), 'central-desktop-unit-isolated'))
  assert.equal(trace.paths.sessionData, trace.paths.userData)
  assert.equal(trace.partition, 'persist:central-desktop-v1')
  assert.equal(trace.windows[0].config.webPreferences.session, appSession)
  assert.equal(trace.windows[0].config.webPreferences.nodeIntegration, false)
  assert.ok(trace.windows[0].config.icon.endsWith(path.join('assets', 'icon.png')))
  assert.equal(trace.windows[0].config.backgroundColor,'#ffffff')
  assert.equal(trace.windows[0].config.titleBarStyle,'hidden')
  assert.equal(trace.windows[0].config.accentColor,false)
  assert.equal(trace.windows[0].config.titleBarOverlay.color,'#ffffff')
  assert.equal(trace.spawned[0].config.env.CENTRAL_DATA_DIR, path.join(trace.lockData, 'data'))
  assert.equal(trace.health.path, '/api/health/ready')
  assert.equal(trace.health.hostname, '127.0.0.1')
  assert.equal(trace.dialogs.length, 0)
})

test('second instance never starts Python, first instance is restored and focused', async () => {
  const second = await harness({ instanceLock: false })
  assert.equal(second.trace.spawned.length, 0)
  assert.equal(second.trace.quits, 1)
  const first = await harness()
  first.app.emit('second-instance')
  assert.equal(first.trace.windows[0].restored, true)
  assert.equal(first.trace.windows[0].focused, true)
})

test('packaged app ignores development skip-welcome flag', async () => {
  const { trace } = await harness({ packaged: true })
  assert.equal(trace.dialogs.length, 1)
  assert.equal(trace.spawned.length, 1)
  assert.equal(trace.spawned[0].args.length, 0)
  const marked = await harness({ packaged: true, marker: true })
  assert.equal(marked.trace.dialogs.length, 0)
})

test('failed HTTP readiness stops owned backend before opening a window', async () => {
  const { trace } = await harness({ badHealth: true })
  assert.equal(trace.windows.length, 0)
  assert.equal(trace.stops, 1)
  assert.ok(trace.error)
  assert.ok(trace.quits > 0)
})

test('all quit attempts wait for the same backend cleanup', async () => {
  const { trace, app, finishStop } = await harness({ holdStop: true })
  let prevented = 0
  const event = { preventDefault() { prevented++ } }
  app.emit('before-quit', event)
  app.emit('before-quit', event)
  assert.equal(prevented, 2)
  assert.equal(trace.stops, 1)
  assert.equal(trace.quits, 0)
  finishStop()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(trace.quits, 1)
  app.emit('before-quit', event)
  assert.equal(prevented, 2)
})

test('untrusted popups, webviews, and file navigation cannot gain renderer privileges', async () => {
  const { trace, appSession } = await harness()
  const win = trace.windows[0]
  assert.equal(win.openHandler({ url: 'https://evil.test/', referrer: { url: win.url } }).action, 'deny')
  assert.equal(win.openHandler({ url: 'about:blank', referrer: { url: 'http://127.0.0.1:42002/' } }).action, 'deny')
  const allowed = win.openHandler({ url: 'about:blank', referrer: { url: win.url } })
  assert.equal(allowed.action, 'allow')
  assert.equal(allowed.overrideBrowserWindowOptions.webPreferences.nodeIntegration, false)
  let denied = 0
  win.webContents.emit('will-attach-webview', { preventDefault() { denied++ } })
  win.webContents.emit('will-navigate', { preventDefault() { denied++ } }, 'file:///C:/secret')
  assert.equal(denied, 2)
  assert.equal(appSession.permissionCheck(), false)
  appSession.permission(null, 'camera', allowed => assert.equal(allowed, false))
})
