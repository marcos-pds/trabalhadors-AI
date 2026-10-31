'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const base = require('./package.json').build;
const thumbprint = 'a'.repeat(40);

function load(name, options = {}) {
  const calls = [];
  const module = { exports: {} };
  const env = { SystemRoot: 'C:\\Windows', CENTRAL_SIGN_CERT_SHA1: thumbprint, ...options.env };
  const hooks = { sign() {}, afterPack() {} };
  const code = fs.readFileSync(path.join(__dirname, name), 'utf8');
  vm.runInNewContext(code, {
    module, exports: module.exports, __dirname, process: { env, platform: options.platform || 'win32' },
    require(id) {
      if (id === './package.json') return { build: base };
      if (id === './signing.cjs') return hooks;
      if (id === 'node:path') return path.win32;
      if (id === 'node:fs') return { existsSync: () => options.exists !== false };
      if (id === 'node:child_process') return { execFileSync(...args) {
        calls.push(args); if (options.failure) throw new Error('signing rejected');
      } };
      throw new Error('unexpected dependency: ' + id);
    },
  }, { filename: name });
  return { value: module.exports, calls, hooks };
}

test('signed config preserves icon, artifactName, targets, resources and installer/data settings', () => {
  const before = JSON.stringify(base);
  const { value: signed, hooks } = load('electron-builder.signed.cjs');
  for (const key of ['icon', 'artifactName', 'target']) assert.equal(signed.win[key], base.win[key]);
  assert.equal(signed.directories.output, 'dist-signed');
  assert.equal(signed.nsis, base.nsis);
  assert.equal(signed.files, base.files);
  assert.equal(signed.extraResources, base.extraResources);
  assert.equal(signed.forceCodeSigning, true);
  assert.equal(signed.win.signExecutable, true);
  assert.equal(signed.win.signAndEditExecutable, true);
  assert.equal(signed.afterPack, hooks.afterPack);
  assert.equal(signed.win.signtoolOptions.sign, hooks.sign);
  assert.equal(signed.win.signtoolOptions.signingHashAlgorithms.join(','), 'sha256');
  assert.ok(signed.win.signExts.includes('.dll') && signed.win.signExts.includes('.pyd'));
  assert.equal(JSON.stringify(base), before); // unsigned build object is never mutated
});

test('invalid/missing certificate rejects config before a signed build can begin', () => {
  for (const value of ['', 'not-a-cert', 'a'.repeat(39), 'a'.repeat(41)]) {
    assert.throws(() => load('electron-builder.signed.cjs', { env: { CENTRAL_SIGN_CERT_SHA1: value } }), /Certificado ausente/);
  }
});

test('sign callback invokes system PowerShell without shell or PATH lookup and enforces publisher', async () => {
  const { value, calls } = load('signing.cjs');
  const file = 'C:\\Build Output\\Central IA.exe';
  await value.sign({ path: file });
  assert.equal(calls.length, 1);
  const [executable, args, options] = calls[0];
  assert.equal(executable, 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe');
  assert.equal(args[args.indexOf('-Path') + 1], file);
  assert.ok(args.includes('-Sign') && args.includes('-RequirePublisher'));
  assert.equal(options.shell, false);
  assert.equal(options.windowsHide, true);
});

test('afterPack signs Windows tree while preserving valid third-party publishers', async () => {
  const { value, calls } = load('signing.cjs');
  await value.afterPack({ electronPlatformName: 'win32', appOutDir: 'C:\\Build\\win-unpacked' });
  assert.equal(calls[0][1].includes('-Sign'), true);
  assert.equal(calls[0][1].includes('-RequirePublisher'), false);
  await assert.rejects(value.afterPack({ electronPlatformName: 'linux', appOutDir: 'C:\\Build' }), /Windows/);
  assert.equal(calls.length, 1);
});

test('hook fails closed on missing targets, invalid host/tool paths and signing failure', async () => {
  await assert.rejects(load('signing.cjs', { exists: false }).value.sign({ path: 'C:\\missing.exe' }), /existente/);
  await assert.rejects(load('signing.cjs').value.sign({ path: 'relative.exe' }), /absoluto/);
  await assert.rejects(load('signing.cjs').value.sign(null), /absoluto/);
  await assert.rejects(load('signing.cjs', { platform: 'linux' }).value.sign({ path: 'C:\\app.exe' }), /Windows/);
  await assert.rejects(load('signing.cjs', { env: { SystemRoot: '\\\\server\\Windows' } }).value.sign({ path: 'C:\\app.exe' }), /Diretorio Windows/);
  await assert.rejects(load('signing.cjs', { env: { CENTRAL_SIGN_CERT_SHA1: '' } }).value.sign({ path: 'C:\\app.exe' }), /CENTRAL_SIGN_CERT/);
  await assert.rejects(load('signing.cjs', { failure: true }).value.sign({ path: 'C:\\app.exe' }), /signing rejected/);
});

const windows = process.platform === 'win32';
const powershell = windows ? path.join(process.env.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe') : '';
const script = path.join(__dirname, 'sign_windows.ps1');
function runPS(args) {
  const env = { ...process.env };
  delete env.CENTRAL_SIGN_CERT_SHA1;
  try {
    const stdout = execFileSync(powershell, ['-NoLogo', '-NoProfile', '-NonInteractive', '-File', script, ...args],
      { env, windowsHide: true, encoding: 'utf8', timeout: 30000, stdio: 'pipe' });
    return { status: 0, output: stdout };
  } catch (error) {
    return { status: error.status, output: String(error.stdout || '') + String(error.stderr || '') };
  }
}
function fixture(t) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'central-signing-test-'));
  t.after(() => {
    assert.ok(path.resolve(folder).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(folder, { recursive: true, force: true });
  });
  const file = path.join(folder, 'unsigned.exe');
  const bytes = Buffer.concat([Buffer.from('MZ'), Buffer.alloc(126)]);
  fs.writeFileSync(file, bytes);
  return { folder, file, bytes };
}

test('PowerShell audit tolerates unsigned input only in explicit read-only audit mode', { skip: !windows }, t => {
  const { file, bytes } = fixture(t);
  const audit = runPS(['-Path', file, '-AuditOnly']);
  assert.equal(audit.status, 0, audit.output);
  assert.match(audit.output, /Binarios: 1/);
  assert.notEqual(runPS(['-Path', file]).status, 0);
  assert.deepEqual(fs.readFileSync(file), bytes);
});

test('PowerShell rejects fail-open signing options and invalid publisher/TSA before signing', { skip: !windows }, t => {
  const { file, bytes } = fixture(t);
  for (const [args, expected] of [
    [['-Sign', '-AuditOnly'], /mutuamente exclusivos/],
    [['-RequirePublisher'], /CENTRAL_SIGN_CERT_SHA1/],
    [['-Sign', '-Thumbprint', thumbprint, '-TimestampUrl', 'http://timestamp.test/'], /HTTPS/],
  ]) {
    const result = runPS(['-Path', file, ...args]);
    assert.notEqual(result.status, 0, result.output);
    assert.match(result.output, expected);
  }
  assert.deepEqual(fs.readFileSync(file), bytes);
});

test('PowerShell refuses a report that would destroy a PE input even if named JSON', { skip: !windows }, t => {
  const { folder, bytes } = fixture(t);
  const input = path.join(folder, 'native.json');
  fs.writeFileSync(input, bytes);
  const result = runPS(['-Path', input, '-AuditOnly', '-Report', input]);
  assert.notEqual(result.status, 0);
  assert.match(result.output, /sobrescrever um binario/);
  assert.deepEqual(fs.readFileSync(input), bytes);
});

test('PowerShell rejects junctions before accessing a certificate or signing outside the tree', { skip: !windows }, t => {
  const { folder, file, bytes } = fixture(t);
  const outside = path.join(folder, 'outside');
  const tree = path.join(folder, 'package');
  fs.mkdirSync(outside); fs.mkdirSync(tree);
  try { fs.symlinkSync(outside, path.join(tree, 'escape'), 'junction'); }
  catch (err) { if (err.code === 'EPERM') { t.skip('junction not permitted'); return; } throw err; }
  const result = runPS(['-Path', tree, '-Sign', '-Thumbprint', thumbprint]);
  assert.notEqual(result.status, 0);
  assert.match(result.output, /Links simbolicos\/juncoes/);
  assert.deepEqual(fs.readFileSync(file), bytes);
});
