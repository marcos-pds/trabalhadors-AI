'use strict'
const { app, BrowserWindow, dialog, session, Menu, shell } = require('electron')
const { spawn } = require('node:child_process')
const http = require('node:http')
const fs = require('node:fs')
const path = require('node:path')
const { inventory, summary } = require('./dependency_inventory.cjs')
const { isRunning, stopOwnedBackend } = require('./process_lifecycle.cjs')
const { PROFILES, planFor, planText } = require('./setup_profiles.cjs')
const { RENDERER_PREFERENCES, backendOrigin, createNetworkPolicy, requestHeaders,
  responseHeaders, externalAuthURL, dataDirectory, backendEnvironment } = require('./security_policy.cjs')

const READY = /^CENTRAL_DESKTOP_READY=(http:\/\/127\.0\.0\.1:(\d{1,5})\/)$/
let child = null
let win = null
let serverOrigin = null
let quitting = false
let shutdownComplete = false
let shutdown = null
let appSession = null
let authWindow = null
let authBusy = false
const authPolls = new Set()
app.setName('Central IA')
if (process.platform === 'win32') app.setAppUserModelId('br.centralia.desktop')

async function chooseSetupProfile() {
  const choice = await dialog.showMessageBox({
    type: 'question', title: 'Central IA — componentes opcionais',
    message: 'Qual perfil você deseja preparar?',
    detail: 'Esta versão apenas mostra o plano; não instala nada automaticamente.',
    buttons: [...PROFILES.map(p => p.title), 'Cancelar'],
    defaultId: 0, cancelId: PROFILES.length, noLink: true,
  })
  if (choice.response >= PROFILES.length) return
  const profile = PROFILES[choice.response]
  const plan = planFor(profile.id, inventory())
  await dialog.showMessageBox({
    type: 'info', title: 'Plano: ' + plan.title,
    message: 'Componentes opcionais do perfil',
    detail: planText(plan),
    buttons: ['Entendido'], noLink: true,
  })
}

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
  if (!app.isPackaged && process.env.CENTRAL_DESKTOP_SKIP_WELCOME === '1') return true
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
    path.join(root, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin',
      process.platform === 'win32' ? 'python.exe' : 'python')
  if (!fs.existsSync(python)) throw new Error('Ambiente Python .venv nao encontrado.')
  return { executable: python, args: [path.join(__dirname, 'backend_launcher.py')], cwd: root }
}

function ping(port) {
  return new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port, path: '/api/health/ready',
      timeout: 2500, agent: false }, res => {
      let body = ''
      res.on('data', chunk => {
        body += chunk.toString('utf8')
        if (body.length > 8192) req.destroy(new Error('Resposta de saude invalida.'))
      })
      res.on('error', reject)
      res.on('end', () => {
        try {
          const health = JSON.parse(body)
          if (res.statusCode !== 200 || health.status !== 'ready' || health.database !== 'ready') {
            throw new Error('Backend local ainda nao esta pronto.')
          }
          resolve()
        } catch (err) { reject(err) }
      })
    })
    req.once('timeout', () => req.destroy(new Error('Timeout da saude local.')))
    req.once('error', reject)
  })
}

function startPython() {
  const spec = backendSpec()
  const data = path.join(app.getPath('userData'), 'data')
  fs.mkdirSync(data, { recursive: true, mode: 0o700 })
  const env = backendEnvironment(process.env, data)
  return new Promise((resolve, reject) => {
    let decided = false
    let ready = false
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
      // Readiness failure must also stop a PyInstaller child tree.
      stopOwnedBackend(spawned).finally(() => reject(err))
    }
    spawned.stdout.on('data', part => {
      buffer = (buffer + part.toString('utf8')).slice(-8192)
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() || ''
      for (const line of lines) {
        const match = line.match(READY)
        if (!match || decided || quitting) continue
        const port = Number(match[2])
        if (port < 1 || port > 65535) return fail(new Error('Porta local invalida.'))
        ping(port).then(() => {
          if (decided || quitting || !isRunning(spawned)) {
            fail(new Error('Inicializacao interrompida.'))
            return
          }
          decided = true
          ready = true
          clearTimeout(timer)
          resolve(match[1])
        }, fail)
      }
    })
    spawned.stderr.on('data', () => {}) // Never expose credentials in UI logs
    spawned.on('error', fail)
    spawned.on('exit', () => {
      if (!decided) return fail(new Error('O servidor Python encerrou durante a inicializacao.'))
      if (ready && !quitting) {
        dialog.showErrorBox('Central IA Desktop', 'O backend local encerrou. Reinicie a Central.')
        app.quit()
      }
    })
  })
}

async function backendJSON(endpoint) {
  if (!serverOrigin || quitting) throw new Error('Backend indisponivel.')
  const response = await appSession.fetch(serverOrigin + endpoint, {
    credentials: 'include', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(4000),
  })
  if (!response.ok) throw new Error('Autorizacao local indisponivel.')
  const reader = response.body.getReader()
  let size = 0
  const chunks = []
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      size += value.length
      if (size > 16384) throw new Error('Resposta local excede o limite.')
      chunks.push(Buffer.from(value))
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
  } finally { await reader.cancel().catch(() => {}) }
}

function configureSession() {
  appSession = session.fromPartition('persist:central-desktop-v1')
  appSession.setPermissionRequestHandler((_wc, _permission, done) => done(false))
  appSession.setPermissionCheckHandler(() => false)
  const guard = createNetworkPolicy(serverOrigin, () => backendJSON('/api/preview/status'))
  appSession.webRequest.onBeforeRequest((details, done) => {
    guard.allows(details).then(allowed => done({ cancel: !allowed }), () => done({ cancel: true }))
  })
  appSession.webRequest.onBeforeSendHeaders((details, done) => {
    done({ requestHeaders: requestHeaders(details.url, serverOrigin, details.requestHeaders) })
  })
  appSession.webRequest.onHeadersReceived((details, done) => {
    done({ responseHeaders: responseHeaders(details.url, serverOrigin, details.responseHeaders || {}) })
  })
  appSession.on('will-download', (event, item) => {
    try { if (new URL(item.getURL()).origin === serverOrigin) return } catch (_) {}
    event.preventDefault()
  })
}

async function openAuth(target, popup) {
  const url = externalAuthURL(target, serverOrigin)
  if (!url || authBusy || quitting) return
  authBusy = true
  try {
    const before = await backendJSON('/api/chatgpt-plan/status')
    const choice = await dialog.showMessageBox(win, {
      type: 'question', title: 'Central IA ? autorizar no navegador',
      message: 'Abrir a autenticacao oficial da OpenAI no navegador padrao?',
      detail: 'Destino: https://auth.openai.com. A janela desktop nao executa essa pagina. '
        + 'Ao concluir, a Central sera atualizada. Nenhuma credencial e exibida aqui.',
      buttons: ['Cancelar', 'Abrir navegador'], defaultId: 0, cancelId: 0, noLink: true,
    })
    if (choice.response !== 1 || quitting || !popup || popup.isDestroyed()) {
      if (popup && !popup.isDestroyed()) popup.close()
      return
    }
    await shell.openExternal(url)
    const until = Date.now() + 10 * 60 * 1000
    const previous = JSON.stringify(before.connection || null)
    const timer = setInterval(async () => {
      if (quitting || popup.isDestroyed() || Date.now() >= until) {
        clearInterval(timer); authPolls.delete(timer)
        if (!popup.isDestroyed()) popup.close()
        return
      }
      try {
        const current = await backendJSON('/api/chatgpt-plan/status')
        if (current.connected && JSON.stringify(current.connection || null) !== previous) {
          clearInterval(timer); authPolls.delete(timer)
          // The external browser has no Electron opener. Refresh the local UI
          // after backend-confirmed success; do not inject renderer JavaScript.
          if (win && !win.isDestroyed()) win.reload()
          popup.close()
        }
      } catch (_) {}
    }, 2000)
    authPolls.add(timer)
    popup.once('closed', () => { clearInterval(timer); authPolls.delete(timer) })
  } catch (_) {
    if (popup && !popup.isDestroyed()) popup.close()
  } finally { authBusy = false }
}

function attachAuthPopup(popup) {
  authWindow = popup
  popup.setTitle('Central IA ? autenticacao no navegador')
  popup.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  popup.webContents.on('will-attach-webview', event => event.preventDefault())
  const navigate = (event, target) => {
    event.preventDefault()
    if (externalAuthURL(target, serverOrigin)) openAuth(target, popup).catch(() => {})
    else if (!popup.isDestroyed()) popup.close()
  }
  popup.webContents.on('will-navigate', navigate)
  popup.webContents.on('will-redirect', navigate)
  popup.once('closed', () => { if (authWindow === popup) authWindow = null })
}

function showWindow(url) {
  serverOrigin = backendOrigin(url)
  configureSession()
  win = new BrowserWindow({
    title: 'Central IA', icon: path.join(__dirname, 'assets', 'icon.png'), width: 1280, height: 830, minWidth: 860, minHeight: 580,
    show: false, autoHideMenuBar: true,
    backgroundColor: '#ffffff',
    ...(process.platform === 'win32' ? {
      titleBarStyle: 'hidden', accentColor: false,
      titleBarOverlay: { color: '#ffffff', symbolColor: '#475569', height: 32 },
    } : {}),
    webPreferences: { ...RENDERER_PREFERENCES, session: appSession },
  })
  win.webContents.on('page-title-updated', event => { event.preventDefault(); win.setTitle('Central IA') })
  win.webContents.setWindowOpenHandler(details => {
    // Only the app's existing blank OAuth placeholder may create a window.
    // Preview popups, arbitrary links and externally supplied feature flags fail closed.
    if (details.url === 'about:blank' && !authWindow && !quitting) {
      try {
        if (new URL(details.referrer.url).origin === serverOrigin) {
          return { action: 'allow', overrideBrowserWindowOptions: {
            show: false, webPreferences: { ...RENDERER_PREFERENCES, session: appSession },
          } }
        }
      } catch (_) {}
    }
    return { action: 'deny' }
  })
  win.webContents.on('did-create-window', attachAuthPopup)
  win.webContents.on('will-navigate', (event, target) => {
    try { if (new URL(target).origin === serverOrigin) return } catch (_) {}
    event.preventDefault()
  })
  win.webContents.on('will-frame-navigate', details => {
    if (details.isMainFrame) {
      try { if (new URL(details.url).origin === serverOrigin) return } catch (_) {}
      details.preventDefault()
    } else if (/^(?:file:|data:|javascript:|https:)/i.test(details.url)) {
      details.preventDefault()
    }
  })
  win.webContents.on('will-attach-webview', event => event.preventDefault())
  win.webContents.on('will-prevent-unload', event => { if (quitting) event.preventDefault() })
  win.webContents.on('render-process-gone', () => { if (!quitting) app.quit() })
  win.once('ready-to-show', () => { if (!quitting) win.show() })
  win.loadURL(url).catch(() => {
    if (!quitting) dialog.showErrorBox('Central IA Desktop', 'A interface local nao carregou.')
    app.quit()
  })
}

try {
  // This operator-controlled portable-data override also works in signed packages.
  // It changes only desktop storage, before Chromium sessions or the instance lock.
  const data = dataDirectory(app.getPath('appData'), process.env.CENTRAL_DESKTOP_USER_DATA)
  fs.mkdirSync(data, { recursive: true, mode: 0o700 })
  app.setPath('userData', data)
  app.setPath('sessionData', data)
} catch (err) {
  dialog.showErrorBox('Central IA Desktop', err.message)
  app.quit()
  throw err
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (win && !win.isDestroyed() && !quitting) {
      if (win.isMinimized()) win.restore()
      win.show()
      win.focus()
    }
  })
  app.whenReady().then(async () => {
    Menu.setApplicationMenu(Menu.buildFromTemplate([{
      label: 'Central IA', submenu: [
        { label: 'Verificar dependencias opcionais', click: () => { diagnostics().catch(() => {}) } },
        { label: 'Planejar componentes para instalacao', click: () => { chooseSetupProfile().catch(() => {}) } },
        { label: 'Abrir pasta de dados desktop', click: () => {
          shell.openPath(app.getPath('userData')).catch(() => {})
        } },
        { label: 'Sobre a Central IA', click: () => {
          dialog.showMessageBox(win, { type: 'info', title: 'Central IA',
            message: 'Central IA Desktop', detail: 'Dados desktop separados da versao Web. '
              + 'Previa local exige uma sessao autorizada; componentes opcionais nao sao instalados automaticamente.' })
        } },
        { role: 'quit', label: 'Sair' },
      ],
    }]))
    try {
      if (!await welcomeIfNeeded() || quitting) { app.quit(); return }
      const url = await startPython()
      if (quitting) return
      showWindow(url)
    } catch (err) {
      if (!quitting) dialog.showErrorBox('Central IA Desktop', err.message)
      app.quit()
    }
  }).catch(() => app.quit())
  app.on('before-quit', event => {
    quitting = true
    for (const timer of authPolls) clearInterval(timer)
    authPolls.clear()
    if (shutdownComplete) return
    if (!isRunning(child) && !shutdown) { shutdownComplete = true; return }
    event.preventDefault()
    if (!shutdown) {
      shutdown = stopOwnedBackend(child).catch(() => {}).finally(() => {
        shutdownComplete = true
        app.quit()
      })
    }
  })
  app.on('window-all-closed', () => app.quit())
}
