'use strict'

// Backup a fully stopped Central backend. Never copy a live WAL database.
// Backups remain outside the application installation directory and survive
// NSIS upgrades. No cloud/network access or arbitrary paths from the renderer.
const fs = require('node:fs/promises')
const fss = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')

function hashFile(file) {
  return new Promise((resolve, reject) => {
    const digest = crypto.createHash('sha256')
    const stream = fss.createReadStream(file)
    stream.on('data', block => digest.update(block))
    stream.on('error', reject)
    stream.on('end', () => resolve(digest.digest('hex')))
  })
}

async function fileList(root, prefix = '') {
  const found = []
  for (const name of await fs.readdir(path.join(root, prefix))) {
    const relative = path.join(prefix, name)
    const full = path.join(root, relative)
    const stat = await fs.lstat(full)
    if (stat.isSymbolicLink()) throw new Error('Backup recusado: dados contêm ligação simbólica.')
    if (stat.isDirectory()) found.push(...await fileList(root, relative))
    else if (stat.isFile()) found.push({ relative, bytes: stat.size })
    else throw new Error('Backup recusado: arquivo especial na pasta de dados.')
  }
  return found
}

async function createBackup(dataDir, backupDir, appVersion, keep = 5) {
  const db = await fs.stat(path.join(dataDir, 'central.sqlite3'))
  if (!db.isFile() || db.size === 0) throw new Error('O banco de dados não está pronto para backup.')
  const sourceFiles = await fileList(dataDir)
  if (!sourceFiles.some(x => x.relative === 'central.sqlite3')) throw new Error('Banco SQLite ausente.')
  await fs.mkdir(backupDir, { recursive: true, mode: 0o700 })
  const pending = await fs.mkdtemp(path.join(backupDir, '.pending-'))
  try {
    await fs.cp(dataDir, path.join(pending, 'data'), {
      recursive: true, force: false, errorOnExist: true, preserveTimestamps: true,
      dereference: false,
    })
    const manifest = []
    for (const file of sourceFiles) {
      const original = path.join(dataDir, file.relative)
      const copy = path.join(pending, 'data', file.relative)
      const copied = await fs.stat(copy)
      if (copied.size !== file.bytes) throw new Error('Falha na cópia: tamanho diferente.')
      const [one, two] = await Promise.all([hashFile(original), hashFile(copy)])
      if (one !== two) throw new Error('Falha na verificação SHA-256 do backup.')
      manifest.push({ file: file.relative.replaceAll(path.sep, '/'), size: file.bytes, sha256: two })
    }
    await fs.writeFile(path.join(pending, 'manifest.json'), JSON.stringify({
      appVersion, createdAt: new Date().toISOString(), files: manifest,
    }, null, 2), { mode: 0o600 })
    const suffix = crypto.randomBytes(3).toString('hex')
    const folder = 'backup-' + new Date().toISOString().replace(/[:.]/g, '-') + '-' + suffix
    const result = path.join(backupDir, folder)
    await fs.rename(pending, result)
    // Retain the most recent backups. Never delete the one we just created.
    const folders = (await fs.readdir(backupDir)).filter(name => name.startsWith('backup-')).sort().reverse()
    for (const old of folders.slice(Math.max(1, keep))) {
      await fs.rm(path.join(backupDir, old), { recursive: true, force: true }).catch(() => {})
    }
    return result
  } catch (error) {
    await fs.rm(pending, { recursive: true, force: true }).catch(() => {})
    throw error
  }
}

module.exports = { createBackup, fileList }
