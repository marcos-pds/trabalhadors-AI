import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const workflow = readFileSync(new URL('../../.github/workflows/release-desktop.yml', import.meta.url), 'utf8')
const desktopPackage = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))

test('only approved main CI completion publishes stable releases', () => {
  assert.match(workflow, /workflow_run:/)
  assert.match(workflow, /workflows: \["Central IA checks"\]/)
  assert.match(workflow, /types: \[completed\]/)
  assert.match(workflow, /branches: \[main\]/)
  assert.match(workflow, /github\.event\.workflow_run\.event == 'push'/)
  assert.match(workflow, /github\.event\.workflow_run\.head_branch == 'main'/)
  assert.match(workflow, /github\.event\.workflow_run\.head_repository\.full_name == github\.repository/)
  assert.match(workflow, /github\.event\.workflow_run\.conclusion == 'success'/)
  assert.match(workflow, /ref: \$\{\{ github\.event\.workflow_run\.head_sha \}\}/)
  assert.doesNotMatch(workflow, /pull_request:/)
})

test('publishing requires a new stable SemVer; existing tags and releases are protected', () => {
  assert.match(desktopPackage.version, /^\d+\.\d+\.\d+$/)
  assert.match(workflow, /Only stable SemVer versions are released/)
  assert.match(workflow, /gh release list --limit 200/)
  assert.match(workflow, /tagName -eq \$tag/)
  assert.match(workflow, /Version\]::Parse\(\$version\) -le \$previous/)
  assert.match(workflow, /git ls-remote --tags origin/)
  assert.match(workflow, /Refusing to publish/)
})

test('Windows installer must be signed and its SHA512 match the updater manifest', () => {
  assert.match(workflow, /CENTRAL_WINDOWS_SIGNING_PFX_BASE64/)
  assert.match(workflow, /CENTRAL_WINDOWS_SIGNING_PASSWORD/)
  assert.match(workflow, /Get-AuthenticodeSignature/)
  assert.match(workflow, /-ne 'Valid'/)
  assert.match(workflow, /Get-FileHash \$exe\.FullName -Algorithm SHA512/)
  assert.match(workflow, /desktop\/release\/latest\.yml/)
  assert.match(workflow, /Bundled backend exited/)
  assert.match(workflow, /sha512 does not match latest\.yml/i)
})

test('published GitHub Release contains signed EXE, latest.yml and blockmaps when present', () => {
  assert.match(workflow, /gh release create \$env:RELEASE_TAG @assets/)
  assert.match(workflow, /--target \$env:APPROVED_SHA/)
  assert.match(workflow, /--latest/)
  assert.match(workflow, /desktop\/release\/\*\.blockmap/)
  assert.match(workflow, /gh release view \$env:RELEASE_TAG/)
  assert.match(workflow, /Published GitHub Release lacks the updater manifest or installer/)
  assert.equal(desktopPackage.build.publish[0].provider, 'github')
  assert.equal(desktopPackage.build.publish[0].repo, 'trabalhadors-AI')
})
