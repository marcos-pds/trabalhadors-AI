import assert from 'node:assert/strict'
import test from 'node:test'
import { isCentralDesktop } from './desktopMode.mjs'

test('normal browser and PWA sessions remain on the original web interface', () => {
  assert.equal(isCentralDesktop({ location: { search: '?desktop=true' } }), false)
  assert.equal(isCentralDesktop({ matchMedia: () => ({ matches: true }) }), false)
  assert.equal(isCentralDesktop({ centralDesktop: { isDesktop: false, setExpanded() {} } }), false)
  assert.equal(isCentralDesktop({ centralDesktop: { isDesktop: true } }), false)
})

test('Electron with the restricted preload bridge enables desktop UI', () => {
  assert.equal(isCentralDesktop({ centralDesktop: { isDesktop: true, setExpanded() {} } }), true)
})
