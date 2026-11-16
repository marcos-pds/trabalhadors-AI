'use strict'
const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const { createBackup } = require('../backup.cjs')

test('desktop backup preserves a stopped SQLite WAL database and secrets, verifies SHA256 and retains copies', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'central-backup-test-'))
  try {
    const data = path.join(root, 'data')
    const backups = path.join(root, 'backups')
    await fs.mkdir(path.join(data, 'metadata'), { recursive: true })
    const sqlite = Buffer.concat([Buffer.from('SQLite format 3\0'), Buffer.alloc(4096)])
    await fs.writeFile(path.join(data, 'central.sqlite3'), sqlite)
    await fs.writeFile(path.join(data, 'central.sqlite3-wal'), Buffer.from('test WAL'))
    await fs.writeFile(path.join(data, 'metadata', 'secret.key'), Buffer.from('secret for encryption'))
    const first = await createBackup(data, backups, '0.3.3', 2)
    assert.match(first, /backup-/)
    const manifest = JSON.parse(await fs.readFile(path.join(first, 'manifest.json'), 'utf8'))
    assert.equal(manifest.appVersion, '0.3.3')
    assert.equal(manifest.files.length, 3)
    assert.deepEqual(await fs.readFile(path.join(first, 'data', 'central.sqlite3')), sqlite)
    assert.equal((await fs.readFile(path.join(first, 'data', 'metadata', 'secret.key'))).toString(), 'secret for encryption')
    await createBackup(data, backups, '0.3.3', 2)
    await createBackup(data, backups, '0.3.3', 2)
    const retained = (await fs.readdir(backups)).filter(x => x.startsWith('backup-'))
    assert.equal(retained.length, 2)
    assert.ok(await fs.stat(path.join(data, 'central.sqlite3')))
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('backup fails closed when the database is missing', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'central-backup-no-db-'))
  try {
    await fs.mkdir(path.join(root, 'data'))
    await assert.rejects(
      createBackup(path.join(root, 'data'), path.join(root, 'backups'), '0.3.3'),
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})
