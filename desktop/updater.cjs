'use strict'

const { autoUpdater } = require('electron-updater')
const path = require('node:path')
const { createBackup } = require('./backup.cjs')

function createDesktopUpdater({ app, getWindow, getBackendAddress, prepareBackend, cancelBackend, stopBackend, restartBackend }) {
  let state = { phase: 'idle', currentVersion: app.getVersion(), version: null, progress: 0, message: '', backup: null }
  let busy = false
  const enabled = app.isPackaged && process.platform === 'win32'
  function publish(change) {
    state = { ...state, ...change }
    const window = getWindow()
    if (window && !window.isDestroyed()) window.webContents.send('central-desktop:update-state', state)
  }

  // Do NOT silently download or silently install. On quitting a normal window,
  // the cached update remains cached until user expressly chooses Install.
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = false
  autoUpdater.allowPrerelease = false
  autoUpdater.allowDowngrade = false
  autoUpdater.logger = {
    info() {}, warn() {}, error() {}, debug() {},
  }

  autoUpdater.on('checking-for-update', () => publish({ phase: 'checking', message: 'Buscando versão estável...' }))
  autoUpdater.on('update-available', info => publish({
    phase: 'available', version: info.version, message: 'Uma atualização está disponível.', progress: 0,
  }))
  autoUpdater.on('update-not-available', () => publish({
    phase: 'current', version: null, message: 'Você está usando a versão mais recente.', progress: 0,
  }))
  autoUpdater.on('download-progress', progress => publish({
    phase: 'downloading', progress: Math.min(100, Math.round(progress.percent || 0)),
    message: 'Baixando atualização do GitHub...',
  }))
  autoUpdater.on('update-downloaded', info => publish({
    phase: 'ready', version: info.version, progress: 100,
    message: 'Download verificado. Pronto para instalar com sua confirmação.',
  }))
  autoUpdater.on('error', error => publish({
    phase: 'error', message: 'Falha na atualização: ' + String(error.message || error).slice(0, 280),
  }))

  async function check() {
    if (!enabled) return publish({ phase: 'unsupported', message: 'Atualizações disponíveis apenas no aplicativo Windows instalado.' })
    if (busy || state.phase === 'downloading' || state.phase === 'backing-up') return
    busy = true
    try { await autoUpdater.checkForUpdates() }
    catch (error) { publish({ phase: 'error', message: 'Não foi possível consultar o GitHub: ' + error.message }) }
    finally { busy = false }
    return state
  }

  async function download() {
    if (!enabled || state.phase !== 'available' || busy) return state
    busy = true
    publish({ phase: 'downloading', progress: 0, message: 'Baixando somente após sua confirmação...' })
    try { await autoUpdater.downloadUpdate() }
    catch (error) { publish({ phase: 'error', message: 'Falha no download: ' + error.message }) }
    finally { busy = false }
    return state
  }

  async function install() {
    if (!enabled || state.phase !== 'ready' || busy) return state
    busy = true
    let prepared = false
    let stopped = false
    try {
      publish({ phase: 'checking-tasks', message: 'Conferindo tarefas da Central...' })
      await prepareBackend()
      prepared = true
      publish({ phase: 'backing-up', message: 'Fechando o servidor para salvar um backup consistente...' })
      await stopBackend()
      stopped = true
      const userData = app.getPath('userData')
      const saved = await createBackup(path.join(userData, 'data'), path.join(userData, 'backups'), app.getVersion(), 5)
      publish({ phase: 'installing', backup: saved,
        message: 'Backup confirmado. Fechando a Central e iniciando a atualização...' })
      // The updater verifies the downloaded installer via its latest.yml sha512
      // and, when configured, Windows Authenticode publisher signature.
      autoUpdater.quitAndInstall(true, true)
    } catch (error) {
      publish({ phase: 'error', message: 'Atualização cancelada para proteger seus dados: ' + error.message })
      if (stopped) await restartBackend().catch(() => {})
      else if (prepared) await cancelBackend().catch(() => {})
    } finally { busy = false }
    return state
  }

  async function action(name) {
    if (name === 'check') return check()
    if (name === 'download') return download()
    if (name === 'install') return install()
    throw new Error('Ação de atualização inválida.')
  }

  function start() {
    if (!enabled) return
    // Checking does not download or install anything.
    setTimeout(() => check(), 14000).unref?.()
    setInterval(() => check(), 6 * 60 * 60 * 1000).unref?.()
  }

  return { action, getState: () => ({ ...state }), start }
}

module.exports = { createDesktopUpdater }
