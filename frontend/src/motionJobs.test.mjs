import test from 'node:test'
import assert from 'node:assert/strict'
import {mediaManifest} from './motionJobs.mjs'

test('media form produces typed source/output links without shell commands or claimed results',()=>{
  const p=mediaManifest({mode:'audio',source:'clip.mp4',output:'renders/final.wav'})
  assert.equal(p.jobs[0].adapter,'ffmpeg')
  assert.deepEqual(p.jobs[0].params,{profile:'pcm_s16le'})
  assert.equal(p.artifacts[1].kind,'audio')
  assert.deepEqual(p.artifacts[1].provenance,{source:'planned',job_id:'render',inputs:['source']})
  assert.equal(p.jobs[0].command,undefined)
})

test('transcription and composition retain their distinct artifact kinds and parameters',()=>{
  const transcribe=mediaManifest({mode:'transcribe',source:'speech.wav',output:'renders/speech.json'})
  assert.equal(transcribe.artifacts[0].kind,'audio')
  assert.equal(transcribe.artifacts[1].kind,'captions')
  assert.equal(transcribe.jobs[0].adapter,'whisperx')
  const compose=mediaManifest({mode:'compose',source:'scene.tsx',output:'renders/scene.mp4',composition:'Intro'})
  assert.equal(compose.artifacts[0].kind,'composition')
  assert.deepEqual(compose.jobs[0].params,{composition:'Intro',fps:30})
})
