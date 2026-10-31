'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const { RENDERER_PREFERENCES, createNetworkPolicy, backendOrigin, requestHeaders,
  responseHeaders, externalAuthURL, dataDirectory, backendEnvironment } = require('./security_policy.cjs')
const APP = 'http://127.0.0.1:41001'
const PREVIEW = 'http://127.0.0.1:42002'
const request = (url, extra = {}) => ({ url, resourceType: 'xhr', initiatorOrigin: APP, ...extra })

test('renderer has no Node, preload, webview, or relaxed web security', () => {
  assert.equal(RENDERER_PREFERENCES.nodeIntegration, false)
  assert.equal(RENDERER_PREFERENCES.nodeIntegrationInWorker, false)
  assert.equal(RENDERER_PREFERENCES.nodeIntegrationInSubFrames, false)
  assert.equal(RENDERER_PREFERENCES.contextIsolation, true)
  assert.equal(RENDERER_PREFERENCES.sandbox, true)
  assert.equal(RENDERER_PREFERENCES.webSecurity, true)
  assert.equal(RENDERER_PREFERENCES.webviewTag, false)
  assert.equal(RENDERER_PREFERENCES.allowRunningInsecureContent, false)
  assert.equal(RENDERER_PREFERENCES.preload, undefined)
})

test('only authenticated backend preview is allowed; revocation is rechecked', async () => {
  let current = { status: 'running', url: PREVIEW + '/' }
  let calls = 0
  const guard = createNetworkPolicy(APP, async () => { calls++; return current })
  assert.equal(await guard.allows(request(APP + '/api/projects')), true)
  assert.equal(await guard.allows(request(PREVIEW + '/', { resourceType: 'subFrame' })), true)
  assert.equal(await guard.allows(request(PREVIEW + '/app.js', { initiatorOrigin: PREVIEW })), true)
  assert.equal(await guard.allows(request(PREVIEW.replace('http:', 'ws:') + '/hmr', { initiatorOrigin: PREVIEW })), true)
  assert.equal(await guard.allows(request('http://127.0.0.1:49999/')), false)
  current = { status: 'stopped' }
  assert.equal(await guard.allows(request(PREVIEW + '/app.js', { initiatorOrigin: PREVIEW })), false)
  assert.ok(calls >= 4)
})

test('unrelated ports/protocols and external hosts never gain network permission', async () => {
  const guard = createNetworkPolicy(APP, async () => ({ status: 'running', url: PREVIEW + '/' }))
  for (const url of ['https://example.com/', 'file:///C:/secret.txt', 'javascript:alert(1)',
    'http://localhost:42002/', 'http://[::1]:42002/', 'http://user:pass@127.0.0.1:42002/',
    'http://127.0.0.1:8765/', 'http://192.168.0.1/', 'ftp://127.0.0.1:42002/', 'not a URL']) {
    assert.equal(await guard.allows(request(url)), false, url)
  }
  assert.equal(await guard.allows(request(PREVIEW + '/', { resourceType: 'mainFrame' })), false)
  assert.equal(await guard.allows(request(APP + '/api/projects', { initiatorOrigin: PREVIEW })), false)
  assert.equal(await guard.allows(request(APP + '/api/projects', { initiatorOrigin: 'null' })), false)
})

test('Docker preview prefix and API failures fail closed', async () => {
  const guard = createNetworkPolicy(APP, async () => ({ status: 'running', url: PREVIEW + '/secret-prefix/' }))
  assert.equal(await guard.allows(request(PREVIEW + '/secret-prefix/index.html')), true)
  assert.equal(await guard.allows(request(PREVIEW + '/secret-prefix-neighbor/index.html')), false)
  assert.equal(await guard.allows(request(PREVIEW + '/index.html')), false)
  for (const status of [null, {}, { status: 'running', url: 'https://evil.test/' },
    { status: 'running', url: APP + '/' }, { status: 'running', url: PREVIEW + '/?secret=x' }]) {
    assert.equal(await createNetworkPolicy(APP, async () => status).allows(request(PREVIEW + '/')), false)
  }
  assert.equal(await createNetworkPolicy(APP, async () => { throw Error('401') }).allows(request(PREVIEW + '/')), false)
})

test('simultaneous preview requests share only their in-flight authorization', async () => {
  let calls = 0
  const guard = createNetworkPolicy(APP, async () => {
    calls++; await new Promise(resolve => setImmediate(resolve))
    return { status: 'running', url: PREVIEW + '/' }
  })
  assert.deepEqual(await Promise.all([guard.allows(request(PREVIEW + '/a.js')),
    guard.allows(request(PREVIEW + '/b.js'))]), [true, true])
  assert.equal(calls, 1)
  await guard.allows(request(PREVIEW + '/c.js'))
  assert.equal(calls, 2)
})

test('data/blob documents cannot bypass navigation restrictions', async () => {
  const guard = createNetworkPolicy(APP, async () => ({ status: 'running', url: PREVIEW + '/' }))
  assert.equal(await guard.allows(request('data:text/html,<script>alert(1)</script>', { resourceType: 'subFrame' })), false)
  assert.equal(await guard.allows(request('data:image/png;base64,AA==', { resourceType: 'image' })), true)
  assert.equal(await guard.allows(request('blob:' + APP + '/token', { resourceType: 'image' })), true)
  assert.equal(await guard.allows(request('blob:' + APP + '/token', { resourceType: 'mainFrame' })), false)
})

test('preview cannot receive Central credentials or overwrite Central cookies', () => {
  const headers = { Cookie: 'central_session=secret', Authorization: 'Bearer secret',
    'Proxy-Authorization': 'secret', 'X-Central-Request': '1', Referer: APP, Accept: 'text/html' }
  assert.deepEqual(requestHeaders(PREVIEW, APP, headers), { Accept: 'text/html' })
  assert.equal(requestHeaders(APP, APP, headers), headers)
  const incoming = { 'Set-Cookie': ['central_session=evil'], 'clear-site-data': ['"cookies"'], 'Content-Type': ['text/html'] }
  assert.deepEqual(responseHeaders(PREVIEW, APP, incoming), { 'Content-Type': ['text/html'] })
  assert.equal(responseHeaders(APP, APP, incoming), incoming)
})

function authURL() {
  const url = new URL('https://auth.openai.com/api/accounts/authorize')
  url.search = new URLSearchParams({ redirect_uri: APP + '/api/chatgpt-plan/callback',
    response_type: 'code', state: 'state_12345678901234567890', code_challenge: 'a'.repeat(43),
    code_challenge_method: 'S256' }).toString()
  return url
}

test('external browser receives only a fixed OAuth destination and local callback', () => {
  assert.equal(externalAuthURL(authURL().href, APP), authURL().href)
  for (const mutate of [u => { u.hostname = 'auth.openai.com.evil.test' },
    u => { u.protocol = 'http:' }, u => { u.username = 'user' }, u => { u.pathname = '/other' },
    u => u.searchParams.set('redirect_uri', 'http://127.0.0.1:8765/api/chatgpt-plan/callback'),
    u => u.searchParams.set('redirect_uri', APP + '/admin'),
    u => u.searchParams.append('state', 'ambiguous'),
    u => u.searchParams.set('code_challenge_method', 'plain'), u => u.searchParams.set('state', 'short')]) {
    const url = authURL(); mutate(url)
    assert.equal(externalAuthURL(url.href, APP), null, url.href)
  }
  for (const value of ['file:///C:/Windows/notepad.exe', 'ms-settings:privacy', 'javascript:alert(1)']) {
    assert.equal(externalAuthURL(value, APP), null)
  }
})

const missingFS = { lstatSync() { const err = new Error('missing'); err.code = 'ENOENT'; throw err } }
const windows = { path: path.win32, home: 'C:\\Users\\operator', fs: missingFS }

test('operator data override is absolute, specific and isolated from defaults', () => {
  assert.equal(dataDirectory('C:\\Users\\operator\\AppData\\Roaming', undefined, windows),
    'C:\\Users\\operator\\AppData\\Roaming\\Central IA Desktop')
  assert.equal(dataDirectory('C:\\AppData', 'D:\\Portable\\CentralIA', windows), 'D:\\Portable\\CentralIA')
  for (const value of ['', '.', 'relative/path', 'C:\\', 'C:\\Users\\operator',
    '\\\\host\\share\\data', '//host/share/data', ' C:\\temp', 'C:\\temp.', 'C:\\temp\\data:stream']) {
    assert.throws(() => dataDirectory('C:\\AppData', value, windows), undefined, value)
  }
})

test('existing symlinks, junctions, files and redirected ancestors are rejected', () => {
  for (const fake of [
    { lstatSync: () => ({ isSymbolicLink: () => true, isDirectory: () => true }) },
    { lstatSync: () => ({ isSymbolicLink: () => false, isDirectory: () => false }) },
    { lstatSync: () => ({ isSymbolicLink: () => false, isDirectory: () => true }), realpathSync: () => 'D:\\outside' },
  ]) {
    assert.throws(() => dataDirectory('C:\\AppData', 'C:\\temp\\data', { ...windows, fs: fake }))
  }
})

test('desktop backend cannot inherit web storage, secret or automation settings', () => {
  const env = backendEnvironment({ PATH: 'node', CENTRAL_DATA_DIR: 'web', CENTRAL_SECRET_KEY: 'web-key',
    CENTRAL_DATABASE_URL: 'web-db', CENTRAL_DESKTOP_SKIP_WELCOME: '1', PYTHONPATH: 'evil', NODE_OPTIONS: 'evil' }, 'desktop/data')
  assert.equal(env.CENTRAL_DATA_DIR, 'desktop/data')
  assert.equal(env.CENTRAL_JOB_MODE, 'embedded')
  assert.equal(env.PATH, 'node')
  for (const key of ['CENTRAL_SECRET_KEY', 'CENTRAL_DATABASE_URL', 'CENTRAL_DESKTOP_SKIP_WELCOME', 'PYTHONPATH', 'NODE_OPTIONS']) {
    assert.equal(env[key], undefined)
  }
  assert.throws(() => backendOrigin('https://example.com/'))
})
