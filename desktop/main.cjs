'use strict'
const { app, BrowserWindow, dialog, session, Menu } = require('electron')
const { spawn } = require('node:child_process')
const { createConnection } = require('node:net')
const fs = require('node:fs')
const path = require('node:path')
const { inventory, summary } = require('./dependency_inventory.cjs')
const { isRunning, stopOwnedBackend } = require('./process_lifecycle.cjs')

const READY = /^CENTRAL_DESKTOP_READY=(http:\/\/127\.0\.0\.1:(\d{1,5})\/)$/
let child = null
let win = null
let serverOrigin = null
let closingBackend = false

function diagnostics(firstRun = false) {
  return dialog.showMessageBox({
    type: 'info', title: 'Central IA — dependências opcionais',
    message: 'Diagnóstico local de recursos disponíveis',
    detail: summary(inventory()),
    buttons: firstRun ? ['Abrir a Central', 'Sair'] : ['Entendido'],
    defaultId: 0, cancelId: firstRun ? 1 : 0, noLink: true,
    checkboxLabel: firstRun ? 'Não mostrar automaticamente nas próximas inicializações' : undefined,
    checkboxChecked: false,
  })
}

async function welcomeIfNeeded() {
  const marker = path.join(app.getPath('userData'), 'desktop-dependencies-reviewed-v1')
  if (fs.existsSync(marker)) return true
  const choice = await diagnostics(true)
  if (choice.response !== 0) return false
  if (choice.checkboxChecked) {
    try {
      fs.mkdirSync(path.dirname(marker), { recursive: true, mode: 0o700 })
      fs.writeFileSync(marker, 'v1\n', { flag: 'wx', mode: 0o600 })
    } catch (_) {}
  }
  return true
}

function backendSpec() {
  if (app.isPackaged) {
    const binary = path.join(process.resourcesPath, 'backend', 'central-desktop-backend.exe')
    if (!fs.existsSync(binary)) throw new Error('Backend Python ausente do pacote.')
    return { executable: binary, args: [], cwd: path.dirname(binary) }
  }
  const root = path.resolve(__dirname, '..')
  const python = process.env.CENTRAL_DESKTOP_PYTHON ||
    path.join(root, '.venv', 'Scripts', 'python.exe')
  if (!fs.existsSync(python)) throw new Error('Ambiente Python .venv nao encontrado.')
  return { executable: python, args: [path.join(__dirname, 'backend_launcher.py')], cwd: root }
}

function ping(port) {
  return new Promise((resolve, reject) => {
    const socket = createConnection({ host: '127.0.0.1', port })
    const timer = setTimeout(() => socket.destroy(new Error('Timeout local')), 1800)
    socket.once('connect', () => { clearTimeout(timer); socket.end(); resolve() })
    socket.once('error', err => { clearTimeout(timer); reject(err) })
  })
}

function startPython() {
  const spec = backendSpec()
  const data = path.join(app.getPath('userData'), 'data')
  fs.mkdirSync(data, { recursive: true, mode: 0o700 })
  const env = {
    ...process.env,
    CENTRAL_DATA_DIR: data,
    CENTRAL_DEPLOYMENT_MODE: 'local',
    CENTRAL_HOST: '127.0.0.1',
    CENTRAL_JOB_MODE: 'embedded',
  }
  // Desktop must not accidentally reuse the Web server encryption key,
  // registration policy or experimental automation switches.
  for (const key of ['CENTRAL_SECRET_KEY', 'CENTRAL_PUBLIC_ORIGIN',
                     'CENTRAL_ALLOW_REGISTRATION', 'CENTRAL_WORKTREE_REVIEWS_ENABLED']) {
    delete env[key]
  }
  return new Promise((resolve, reject) => {
    let decided = false
    let buffer = ''
    const spawned = spawn(spec.executable, spec.args, {
      cwd: spec.cwd, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    })
    child = spawned
    const timer = setTimeout(() => fail(new Error('Backend nao iniciou dentro do limite.')), 60000)
    function fail(err) {
      if (decided) return
      decided = true
      clearTimeout(timer)
      spawned.kill()
      reject(err)
    }
    spawned.stdout.on('data', part => {
      buffer = (buffer + part.toString('utf8')).slice(-8192)
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() || ''
      for (const line of lines) {
        const match = line.match(READY)
        if (!match || decided) continue
        const port = Number(match[2])
        if (port < 1 || port > 65535) return fail(new Error('Porta local invalida.'))
        ping(port).then(() => {
          if (decided) return
          decided = true
          clearTimeout(timer)
          resolve(match[1])
        }, fail)
      }
    })
    spawned.stderr.on('data', () => {}) // Never expose credentials in UI logs
    spawned.on('error', fail)
    spawned.on('exit', () => {
      if (!decided) return fail(new Error('O servidor Python encerrou durante a inicializacao.'))
      if (win && !win.isDestroyed()) win.close()
    })
  })
}

function showWindow(url) {
  serverOrigin = new URL(url).origin
  win = new BrowserWindow({
    width: 1280, height: 830, minWidth: 860, minHeight: 580,
    show: false, autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false, contextIsolation: true,
      sandbox: true, webSecurity: true,
    },
  })
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.webContents.on('will-navigate', (event, target) => {
    try {
      if (new URL(target).origin === serverOrigin) return
    } catch (_) {}
    event.preventDefault()
  })
  win.webContents.on('will-attach-webview', event => event.preventDefault())
  win.once('ready-to-show', () => win.show())
  win.loadURL(url).catch(() => {
    dialog.showErrorBox('Central IA', 'A interface local nao carregou.')
    app.quit()
  })
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (win && !win.isDestroyed()) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })
  app.whenReady().then(async () => {
    Menu.setApplicationMenu(Menu.buildFromTemplate([{
      label: 'Central IA', submenu: [
        { label: 'Verificar dependências opcionais', click: () => { diagnostics().catch(() => {}) } },
        { role: 'quit', label: 'Sair' },
      ],
    }]))
    session.defaultSession.setPermissionRequestHandler((_wc, _permission, done) => done(false))
    session.defaultSession.webRequest.onBeforeRequest((details, done) => {
      try {
        const url = new URL(details.url)
        if (url.protocol === 'data:' || (url.protocol === 'blob:' && url.origin === serverOrigin)) return done({})
        if (url.protocol === 'http:' && url.origin === serverOrigin &&
            url.hostname === '127.0.0.1') return done({})
      } catch (_) {}
      done({ cancel: true })
    })
    try {
      if (!await welcomeIfNeeded()) { app.quit(); return }
      showWindow(await startPython())
    } catch (err) {
      dialog.showErrorBox('Central IA Desktop', err.message)
      app.quit()
    }
  })
  app.on('before-quit', event => {
    if (closingBackend || !isRunning(child)) return
    // Preserve database integrity and stop the whole PyInstaller tree.
    event.preventDefault()
    closingBackend = true
    stopOwnedBackend(child).finally(() => app.quit())
  })
  app.on('window-all-closed', () => app.quit())
}
