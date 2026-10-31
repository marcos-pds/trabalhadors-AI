'use strict'
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const RENDERER_PREFERENCES = Object.freeze({
  nodeIntegration: false, nodeIntegrationInWorker: false, nodeIntegrationInSubFrames: false,
  contextIsolation: true, sandbox: true, webSecurity: true, webviewTag: false,
  allowRunningInsecureContent: false, navigateOnDragDrop: false,
})

function parsed(value) {
  if (typeof value !== 'string' || value.length > 8192 || /[\\\s\u0000-\u001f]/u.test(value)) return null
  try {
    const url = new URL(value)
    return url.username || url.password ? null : url
  } catch (_) { return null }
}

function loopback(value, protocols = ['http:']) {
  const url = parsed(value)
  return url && protocols.includes(url.protocol) && url.hostname === '127.0.0.1' &&
    url.port && Number(url.port) > 0 ? url : null
}

function backendOrigin(value) {
  const url = loopback(value)
  if (!url) throw new Error('Origem do backend local invalida.')
  return url.origin
}

function previewURL(status, origin) {
  if (!status || status.status !== 'running') return null
  const url = loopback(status.url)
  if (!url || url.origin === origin || url.search || url.hash || !url.pathname.endsWith('/')) return null
  return url
}

function sourceOrigin(details) {
  // Electron 45 retains initiatorOrigin across redirects. Opaque origins fail
  // closed rather than letting an untrusted iframe impersonate the application.
  if (details.initiatorOrigin !== undefined) return details.initiatorOrigin
  const source = details.frame?.url || details.referrer
  if (!source || source === 'about:blank') return null
  return parsed(source)?.origin || 'null'
}

function createNetworkPolicy(originURL, fetchPreview) {
  const origin = backendOrigin(originURL)
  let inFlight = null
  async function currentPreview() {
    // Coalesce simultaneous assets; never retain a positive authorization lease.
    if (!inFlight) {
      inFlight = Promise.resolve().then(fetchPreview).then(value => previewURL(value, origin), () => null)
        .finally(() => { inFlight = null })
    }
    return inFlight
  }
  async function allows(details) {
    const url = parsed(details.url)
    if (!url) return false
    const source = sourceOrigin(details)
    if (url.protocol === 'http:' && url.origin === origin) {
      return source === null || source === origin
    }
    const document = ['mainFrame', 'subFrame', 'object'].includes(details.resourceType)
    if (url.protocol === 'data:') return !document && ['image', 'font', 'media'].includes(details.resourceType)
    if (url.protocol === 'blob:') {
      if (document) return false
      if (url.origin === origin) return source === origin
      const preview = await currentPreview()
      return !!preview && url.origin === preview.origin && source === preview.origin
    }
    const local = loopback(details.url, ['http:', 'ws:'])
    if (!local || details.resourceType === 'mainFrame' || details.resourceType === 'object') return false
    const preview = await currentPreview()
    if (!preview || local.host !== preview.host || !local.pathname.startsWith(preview.pathname)) return false
    return source === origin || source === preview.origin ||
      (source === null && details.resourceType === 'subFrame')
  }
  return { origin, allows }
}

function requestHeaders(url, origin, headers) {
  if (parsed(url)?.origin === origin) return headers
  // HTTP cookies are host-scoped, not port-scoped. Preview projects must never
  // receive the Central session, CSRF header, bearer token, or app referrer.
  return Object.fromEntries(Object.entries(headers).filter(([key]) =>
    !['cookie', 'authorization', 'proxy-authorization', 'x-central-request', 'referer'].includes(key.toLowerCase())))
}

function responseHeaders(url, origin, headers) {
  if (parsed(url)?.origin === origin) return headers
  return Object.fromEntries(Object.entries(headers).filter(([key]) =>
    !['set-cookie', 'set-cookie2', 'clear-site-data'].includes(key.toLowerCase())))
}

function externalAuthURL(value, origin) {
  const url = parsed(value)
  if (!url || url.origin !== 'https://auth.openai.com' ||
      url.pathname !== '/api/accounts/authorize' || url.hash) return null
  for (const key of ['redirect_uri', 'response_type', 'state', 'code_challenge', 'code_challenge_method']) {
    if (url.searchParams.getAll(key).length !== 1) return null
  }
  const redirect = parsed(url.searchParams.get('redirect_uri'))
  if (!redirect || redirect.origin !== origin || redirect.pathname !== '/api/chatgpt-plan/callback' ||
      redirect.search || redirect.hash || url.searchParams.get('response_type') !== 'code' ||
      url.searchParams.get('code_challenge_method') !== 'S256' ||
      !/^[A-Za-z0-9_-]{16,256}$/.test(url.searchParams.get('state')) ||
      !/^[A-Za-z0-9_-]{43,128}$/.test(url.searchParams.get('code_challenge'))) return null
  return url.href
}

function dataDirectory(appData, override, options = {}) {
  const paths = options.path || path
  const home = options.home || os.homedir()
  const io = options.fs || fs
  const value = override === undefined ? paths.join(appData, 'Central IA Desktop') : override
  if (typeof value !== 'string' || !value || value.length > 1024 || value !== value.trim() ||
      /[\u0000-\u001f]/u.test(value) || /^[/\\]{2}/.test(value) || !paths.isAbsolute(value)) {
    throw new Error('CENTRAL_DESKTOP_USER_DATA exige pasta local absoluta e especifica.')
  }
  const resolved = paths.resolve(value)
  const equal = (a, b) => paths === path.win32 || process.platform === 'win32'
    ? a.toLowerCase() === b.toLowerCase() : a === b
  if (equal(resolved, paths.parse(resolved).root) || equal(resolved, paths.resolve(home))) {
    throw new Error('Dados desktop nao podem usar a raiz ou a pasta pessoal inteira.')
  }
  let current = paths.parse(resolved).root
  for (const part of resolved.slice(current.length).split(paths.sep).filter(Boolean)) {
    // Reject Windows path aliases/ADS rather than checking a different object.
    if (/[.: ]$/.test(part) || part.includes(':')) throw new Error('Nome de pasta de dados invalido.')
    current = paths.join(current, part)
    try {
      const stat = io.lstatSync(current)
      if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error('Nao use links/juncoes ou arquivos na pasta de dados.')
      if (!equal(io.realpathSync(current), paths.resolve(current))) throw new Error('Pasta de dados redirecionada por link/juncao.')
    } catch (err) {
      if (err.code !== 'ENOENT') throw err
    }
  }
  return resolved
}

function backendEnvironment(source, data) {
  const env = Object.fromEntries(Object.entries(source).filter(([key]) =>
    !key.toUpperCase().startsWith('CENTRAL_') &&
    !['PYTHONPATH', 'PYTHONHOME', 'NODE_OPTIONS', 'ELECTRON_RUN_AS_NODE'].includes(key.toUpperCase())))
  return Object.assign(env, { CENTRAL_DATA_DIR: data, CENTRAL_DEPLOYMENT_MODE: 'local',
    CENTRAL_HOST: '127.0.0.1', CENTRAL_JOB_MODE: 'embedded', PYTHONUNBUFFERED: '1' })
}

module.exports = { RENDERER_PREFERENCES, backendOrigin, createNetworkPolicy, requestHeaders,
  responseHeaders, externalAuthURL, dataDirectory, backendEnvironment }
