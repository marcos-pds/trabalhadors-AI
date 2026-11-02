'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

function run(target, requirePublisher = false) {
  if (!/^[a-f0-9]{40}$/i.test(process.env.CENTRAL_SIGN_CERT_SHA1 || '')) {
    throw new Error('CENTRAL_SIGN_CERT_SHA1 deve identificar o certificado confiavel do editor.');
  }
  if (process.platform !== 'win32') throw new Error('Assinatura Authenticode exige Windows.');
  if (typeof target !== 'string' || !path.isAbsolute(target) || !fs.existsSync(target)) {
    throw new Error('Destino de assinatura deve ser um caminho absoluto existente.');
  }
  const systemRoot = process.env.SystemRoot || process.env.WINDIR;
  if (!systemRoot || !path.win32.isAbsolute(systemRoot) || /^[/\\]{2}/.test(systemRoot)) {
    throw new Error('Diretorio Windows local nao encontrado para executar PowerShell.');
  }
  // Never let the build cwd or PATH select a different powershell.exe.
  const powershell = path.win32.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  execFileSync(powershell, ['-NoLogo', '-NoProfile', '-NonInteractive', '-File',
    path.join(__dirname, 'sign_windows.ps1'), '-Path', target, '-Sign',
    ...(requirePublisher ? ['-RequirePublisher'] : [])], { stdio: 'inherit', windowsHide: true, shell: false });
}
exports.sign = async configuration => run(configuration && configuration.path, true);
exports.afterPack = async context => {
  if (!context || context.electronPlatformName !== 'win32') {
    throw new Error('O hook de assinatura exige um pacote Windows.');
  }
  run(context.appOutDir);
};
