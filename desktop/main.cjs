'use strict'

const { app, BrowserWindow, ipcMain, screen, shell, dialog } = require('electron')
const { spawn } = require('node:child_process')
const net = require('node:net')
const path = require('node:path')
const fs = require('node:fs')

app.setAppUserModelId('br.central.desktop')
if (!app.requestSingleInstanceLock()) app.quit()

const SMALL_WIDTH = 576
const SMALL_HEIGHT = 78
let dockWindow = null
let backend = null
let target = null
let allowedOrigin = null

function chooseLocalUrl(urlText) {
  const url = new URL(urlText)
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname)) {
    throw new Error('O desktop aceita apenas o servidor local da Central.')
  }
  return url
}

function findUnusedPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port
      server.close(() => resolve(port))
    })
  })
}

async function startBundledBackend() {
  const executable = path.join(process.resourcesPath, 'central-backend', 'central-backend.exe')
  if (!fs.existsSync(executable)) {
    throw new Error('O componente local da Central não foi incluído nesta instalação.')
  }
  const port = await findUnusedPort()
  const dataDir = path.join(app.getPath('userData'), 'data')
  fs.mkdirSync(dataDir, { recursive: true })
  // Keep data and credentials outside Program Files so upgrades preserve them.
  const env = {
    ...process.env,
    CENTRAL_HOST: '127.0.0.1',
    CENTRAL_PORT: String(port),
    CENTRAL_DATA_DIR: dataDir,
    CENTRAL_JOB_MODE: 'embedded',
    CENTRAL_DEPLOYMENT_MODE: 'local',
  }
  backend = spawn(executable, [], { env, windowsHide: true, stdio: 'ignore' })
  backend.once('error', error => {
    dialog.showErrorBox('Central', 'Falha ao iniciar o serviço local: ' + error.message)
  })
  const url = chooseLocalUrl('http://127.0.0.1:' + port + '/')
  if (!await waitForCentral(url, 90)) {
    stopBackend()
    throw new Error('O serviço local não iniciou. Tente reparar ou reinstalar o aplicativo.')
  }
  return url
}

function stopBackend() {
  const owned = backend
  backend = null
  if (!owned || !owned.pid || owned.exitCode !== null) return
  // PyInstaller on Windows may have a worker child. Terminate only our tree.
  if (process.platform === 'win32') {
    try {
      const killer = spawn('taskkill.exe', ['/PID', String(owned.pid), '/T', '/F'], {
        windowsHide: true, stdio: 'ignore',
      })
      killer.on('error', () => owned.kill())
    } catch { owned.kill() }
  } else {
    owned.kill()
  }
}

function bounds(expanded = false) {
  const cursor = screen.getCursorScreenPoint()
  const { workArea } = screen.getDisplayNearestPoint(cursor)
  const width = expanded ? Math.min(980, workArea.width - 20) : Math.min(SMALL_WIDTH, workArea.width - 20)
  const height = expanded ? Math.min(780, workArea.height - 26) : Math.min(SMALL_HEIGHT, workArea.height - 12)
  return {
    x: workArea.x + Math.round((workArea.width - width) / 2),
    y: workArea.y + 6,
    width: Math.max(320, width), height: Math.max(70, height),
  }
}

async function waitForCentral(url, attempts = 30) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1200) })
      if (response.ok) return true
    } catch { /* The server is still starting. */ }
    if (backend && backend.exitCode !== null) return false
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  return false
}

function createWindow() {
  dockWindow = new BrowserWindow({
    ...bounds(false),
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    maximizable: false,
    minimizable: true,
    alwaysOnTop: true,
    skipTaskbar: false,
    autoHideMenuBar: true,
    backgroundColor: '#00000000',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  })
  dockWindow.setAlwaysOnTop(true, 'floating')
  dockWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const external = new URL(url)
      if (external.protocol === 'https:') shell.openExternal(external.href)
    } catch { /* invalid URL */ }
    return { action: 'deny' }
  })
  dockWindow.webContents.on('will-navigate', (event, url) => {
    try {
      if (new URL(url).origin === allowedOrigin) return
    } catch { /* invalid URL */ }
    event.preventDefault()
  })
  dockWindow.on('closed', () => { dockWindow = null })
  dockWindow.loadURL(target.href).then(() => dockWindow?.show())
    .catch(error => {
      dialog.showErrorBox('Central', 'Não foi possível abrir a interface: ' + error.message)
      app.quit()
    })
}

app.on('second-instance', () => dockWindow?.focus())

app.whenReady().then(async () => {
  try {
    // Installed edition starts its own local Python backend. Development
    // edition connects to an already-running local server.
    target = app.isPackaged
      ? await startBundledBackend()
      : chooseLocalUrl(process.env.CENTRAL_DESKTOP_URL || 'http://127.0.0.1:8765/')
    allowedOrigin = target.origin
    if (!await waitForCentral(target, app.isPackaged ? 1 : 30)) {
      throw new Error('Inicie a Central local antes de abrir o modo desktop.')
    }
    ipcMain.on('central-desktop:set-expanded', (event, expanded) => {
      if (!dockWindow || event.sender.id !== dockWindow.webContents.id) return
      if (event.senderFrame !== dockWindow.webContents.mainFrame) return
      try {
        if (new URL(event.senderFrame.url).origin !== allowedOrigin) return
      } catch { return }
      dockWindow.setBounds(bounds(expanded === true), false)
    })
    createWindow()
  } catch (error) {
    dialog.showErrorBox('Central', error.message)
    app.quit()
  }
})

app.on('before-quit', stopBackend)
app.on('window-all-closed', () => app.quit())
