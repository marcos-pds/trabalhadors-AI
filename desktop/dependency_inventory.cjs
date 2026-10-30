'use strict'
// Read-only first-run diagnosis. NEVER executes external tools, downloads,
// installs, touches the registry, asks for admin or accesses saved credentials.
const fs = require('node:fs')
const path = require('node:path')

const COMPONENTS = Object.freeze([
  { id: 'git', label: 'Git', files: ['git.exe'], category: 'project' },
  { id: 'vscode', label: 'Visual Studio Code', files: ['code.cmd', 'code.exe'], category: 'project' },
  { id: 'ollama', label: 'Ollama', files: ['ollama.exe'], category: 'ai' },
  { id: 'codex', label: 'Codex CLI', files: ['codex.exe', 'codex.cmd'], category: 'ai' },
  { id: 'claude', label: 'Claude Code CLI', files: ['claude.exe', 'claude.cmd'], category: 'ai' },
  { id: 'gemini', label: 'Gemini CLI', files: ['gemini.exe', 'gemini.cmd'], category: 'ai' },
  { id: 'opencode', label: 'OpenCode', files: ['opencode.exe', 'opencode.cmd'], category: 'ai' },
  { id: 'docker', label: 'Docker CLI', files: ['docker.exe'], category: 'isolation' },
  { id: 'ffmpeg', label: 'FFmpeg', files: ['ffmpeg.exe'], category: 'motion' },
  { id: 'node', label: 'Node.js', files: ['node.exe'], category: 'dev' },
])
const OPTIONAL_UNVERIFIED = Object.freeze([
  { id: 'models', label: 'Modelos de IA locais', category: 'ai' },
  { id: 'browser_mcp', label: 'Chrome DevTools MCP', category: 'qa' },
  { id: 'playwright', label: 'Playwright e navegadores', category: 'qa' },
  { id: 'acp', label: 'Servidores ACP', category: 'ai' },
  { id: 'whisperx', label: 'WhisperX', category: 'motion' },
  { id: 'remotion', label: 'Remotion', category: 'motion' },
  { id: 'comfyui', label: 'ComfyUI / Wan', category: 'motion' },
])

function _pathEntries(env) {
  const variable = Object.keys(env).find(k => k.toLowerCase() === 'path')
  const value = variable ? String(env[variable]) : ''
  return value.split(path.delimiter)
    .map(entry => entry.trim().replace(/^"|"$/g, ''))
    .filter(entry => entry && path.isAbsolute(entry))
    .slice(0, 160)
}

function filePresent(file, directories, filesystem = fs) {
  // Do not reveal PATH strings or execute files, including npm shims.
  for (const folder of directories) {
    const full = path.join(folder, file)
    try {
      const info = filesystem.lstatSync(full)
      if (info.isFile() && !info.isSymbolicLink()) return true
    } catch (_) {}
  }
  return false
}

function inventory(env = process.env, filesystem = fs) {
  const dirs = _pathEntries(env)
  const detected = COMPONENTS.map(component => ({
    id: component.id,
    label: component.label,
    category: component.category,
    status: component.files.some(name => filePresent(name, dirs, filesystem))
      ? 'found_on_path' : 'not_found_on_path',
    verified: false,
  }))
  // A binary on PATH does not prove login, version, model, running daemon,
  // license, API key, service health or acceptable GPU/VRAM.
  return {
    schema_version: 1,
    method: 'read_only_file_presence_on_path',
    dependencies: detected.concat(OPTIONAL_UNVERIFIED.map(component => ({
      ...component, status: 'not_checked', verified: false,
    }))),
    bundled: ['Electron / Chromium', 'React', 'Python / FastAPI', 'SQLite'],
    limitations: 'Deteccao nao comprova instalacao funcional, versao, autenticacao, licenca ou runtime ativo.',
    installs_performed: 0,
  }
}

function summary(scan) {
  const found = scan.dependencies.filter(d => d.status === 'found_on_path')
  const absent = scan.dependencies.filter(d => d.status !== 'found_on_path')
  return [
    'Incluidos no pacote: ' + scan.bundled.join(', '),
    '',
    'Detectados no PATH (sem verificar versao ou funcionamento):',
    found.length ? found.map(d => '  • ' + d.label).join('\n') : '  Nenhum componente opcional confirmado',
    '',
    'Ausentes ou ainda nao verificados:',
    absent.map(d => '  • ' + d.label).join('\n'),
    '',
    'Esta etapa nao baixa nem instala nada. Os componentes opcionais exigem',
    'verificacao de versao, licenca, espaco, origem e aprovacao individual.',
  ].join('\n').slice(0, 3800)
}

module.exports = { COMPONENTS, OPTIONAL_UNVERIFIED, filePresent, inventory, summary }
