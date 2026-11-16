'use strict'

const { app, BrowserWindow, ipcMain, screen, shell, dialog } = require('electron')
const path = require('node:path')

const requested = process.env.CENTRAL_DESKTOP_URL || 'http://127.0.0.1:8765/'
const target = new URL(requested)
if (!['127.0.0.1', 'localhost'].includes(target.hostname) || target.protocol !== 'http:') {
  throw new Error('CENTRAL_DESKTOP_URL precisa apontar para o servidor local da Central.')
}
const allowedOrigin = target.origin
const SMALL_WIDTH = 576
const SMALL_HEIGHT = 78
let dockWindow

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

async function waitForCentral() {
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      const abort = AbortSignal.timeout(900)
      const response = await fetch(target, { signal: abort })
      if (response.ok) return true
    } catch { /* Backend is starting. */ }
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
    } catch { /* invalid destination */ }
    event.preventDefault()
  })
  dockWindow.on('closed', () => { dockWindow = null })
  dockWindow.loadURL(target.href).then(() => dockWindow?.show())
    .catch(error => dialog.showErrorBox('Central IA', 'Não foi possível carregar a Central: ' + error.message))
}

app.whenReady().then(async () => {
  const ready = await waitForCentral()
  if (!ready) {
    dialog.showErrorBox('Central IA indisponível',
      'Inicie a Central no endereço ' + target.origin + ' antes de abrir a versão desktop.')
    app.quit()
    return
  }
  ipcMain.on('central-desktop:set-expanded', (event, expanded) => {
    if (!dockWindow || event.sender.id !== dockWindow.webContents.id) return
    // IPC from any other navigation or subframe is not trusted.
    if (event.senderFrame !== dockWindow.webContents.mainFrame) return
    try {
      if (new URL(event.senderFrame.url).origin !== allowedOrigin) return
    } catch { return }
    dockWindow.setBounds(bounds(expanded), false)
  })
  createWindow()
})

app.on('window-all-closed', () => app.quit())
