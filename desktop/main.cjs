'use strict'

const { app, BrowserWindow, ipcMain, screen, shell, dialog } = require('electron')
const { spawn } = require('node:child_process')
const net = require('node:net')
const path = require('node:path')
const fs = require('node:fs')
const crypto = require('node:crypto')
const { createDesktopUpdater } = require('./updater.cjs')

app.setAppUserModelId('br.central.desktop')
if (!app.requestSingleInstanceLock()) app.quit()

const SMALL_WIDTH = 576
const SMALL_HEIGHT = 78
let dockWindow = null
let backend = null
let target = null
let allowedOrigin = null
let updaterController = null
let updateToken = null

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
  updateToken = crypto.randomBytes(32).toString('hex')
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
    CENTRAL_DESKTOP_UPDATE_TOKEN: updateToken,
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

async function stopBackendSafely() {
  const owned = backend
  if (!owned || owned.exitCode !== null || !owned.pid) throw new Error('Servidor local não está disponível.')
  const killer = spawn('taskkill.exe', ['/PID', String(owned.pid), '/T', '/F'], {
    windowsHide: true, stdio: 'ignore',
  })
  await new Promise((resolve, reject) => {
    killer.once('error', reject)
    killer.once('exit', code => code === 0 ? resolve() : reject(new Error('Não foi possível encerrar o backend com segurança.')))
  })
  if (owned.exitCode === null) {
    await Promise.race([
      new Promise(resolve => owned.once('exit', resolve)),
      new Promise((_, reject) => setTimeout(() => reject(new Error('O backend ainda está em execução.')), 8000)),
    ])
  }
  backend = null
}
async function internalUpdateRequest(method, operation) {
  if (!target || !updateToken || !app.isPackaged) throw new Error('Atualização disponível apenas na instalação desktop.')
  const response = await fetch(new URL('/api/internal/desktop-update/' + operation, target.origin), {
    method, headers: { 'x-central-desktop-token': updateToken },
    signal: AbortSignal.timeout(6000),
  })
  if (!response.ok) {
    if (response.status === 409) throw new Error('Há tarefas em execução ou aguardando aprovação. Conclua-as antes de atualizar.')
    throw new Error('Não foi possível confirmar que o servidor está seguro para atualizar.')
  }
  return response.json()
}
async function restoreBackend() {
  target = await startBundledBackend()
  allowedOrigin = target.origin
  await dockWindow?.loadURL(target.href)
}

function bounds(layout = 'dock') {
  const cursor = screen.getCursorScreenPoint()
  const { workArea } = screen.getDisplayNearestPoint(cursor)
  const width = layout === 'full' ? Math.min(980, workArea.width - 20)
    : layout === 'compose' ? Math.min(790, workArea.width - 20)
    : Math.min(SMALL_WIDTH, workArea.width - 20)
  const height = layout === 'full' ? Math.min(780, workArea.height - 26)
    : layout === 'compose' ? Math.min(184, workArea.height - 12)
    : Math.min(SMALL_HEIGHT, workArea.height - 12)
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
    updaterController = createDesktopUpdater({
      app, getWindow: () => dockWindow,
      prepareBackend: () => internalUpdateRequest('POST', 'prepare'),
      cancelBackend: () => internalUpdateRequest('POST', 'cancel'),
      stopBackend: stopBackendSafely,
      restartBackend: restoreBackend,
    })
    const allowedRenderer = event => {
      if (!dockWindow || event.sender.id !== dockWindow.webContents.id) return false
      if (event.senderFrame !== dockWindow.webContents.mainFrame) return false
      try { return new URL(event.senderFrame.url).origin === allowedOrigin }
      catch { return false }
    }
    ipcMain.handle('central-desktop:update-state', event =>
      allowedRenderer(event) ? updaterController.getState() : null)
    ipcMain.handle('central-desktop:update-action', async (event, action) => {
      if (!allowedRenderer(event) || !['check', 'download', 'install'].includes(action)) return null
      if (action === 'install') {
        const answer = dialog.showMessageBoxSync(dockWindow, {
          type: 'question', buttons: ['Cancelar', 'Instalar e reiniciar'],
          defaultId: 0, cancelId: 0, noLink: true, title: 'Atualização da Central',
          message: 'Deseja instalar a atualização agora?',
          detail: 'As tarefas serão verificadas e o backup será criado antes do reinício.',
        })
        if (answer !== 1) return updaterController.getState()
      }
      return updaterController.action(action)
    })
    // The compact compose state is a short transparent Electron window.
    // Only a successfully submitted chat message enlarges it to 'full'.
    ipcMain.on('central-desktop:set-layout', (event, layout) => {
      if (!allowedRenderer(event)) return
      if (!['dock', 'compose', 'full'].includes(layout)) return
      dockWindow.setBounds(bounds(layout), false)
    })
    ipcMain.on('central-desktop:set-expanded', (event, expanded) => {
      if (!allowedRenderer(event)) return
      dockWindow.setBounds(bounds(expanded === true ? 'full' : 'dock'), false)
    })
    createWindow()
    updaterController.start()
  } catch (error) {
    dialog.showErrorBox('Central', error.message)
    app.quit()
  }
})

app.on('before-quit', stopBackend)
app.on('window-all-closed', () => app.quit())
