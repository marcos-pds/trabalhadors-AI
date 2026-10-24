import test from 'node:test'
import assert from 'node:assert/strict'
import { connectCatalogStream } from './catalogConnectionStream.js'

function makeResponse(frames, status = 200) {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  }), { status, headers: { 'content-type': 'text/event-stream' } })
}

test('streams live attempts even when frames arrive across chunk boundaries', async () => {
  const frames = [
    { type: 'testing', model_id: 'a', model_name: 'A' },
    { type: 'failed', model_id: 'a', message: 'Erro HTTP 400', next_model: { id: 'b', name: 'B' } },
    { type: 'testing', model_id: 'b', model_name: 'B' },
    { type: 'passed', model_id: 'b', latency_ms: 120 },
    { type: 'connected', model: { id: 'b' }, models: [] },
  ]
  const stream = frames.map(item => 'data: ' + JSON.stringify(item) + '\n\n').join('')
  const chunks = [stream.slice(0, 4), stream.slice(4, 38), stream.slice(38, 79), stream.slice(79)]
  const seen = []
  let checked
  const result = await connectCatalogStream({ kind: 'gemini', api_key: 'secret-key' },
    event => seen.push(event),
    async (url, options) => {
      assert.equal(url, '/api/provider-catalog/connect/stream')
      assert.equal(options.method, 'POST')
      assert.equal(options.credentials, 'same-origin')
      assert.equal(options.headers['X-Central-Request'], '1')
      checked = JSON.parse(options.body)
      return makeResponse(chunks)
    })
  assert.equal(checked.api_key, 'secret-key')
  assert.deepEqual(seen.map(x => x.type), frames.map(x => x.type))
  assert.equal(seen[1].next_model.name, 'B')
  assert.equal(result.model.id, 'b')
})

test('a stream error leaves individual failed events visible', async () => {
  const seen = []
  await assert.rejects(
    connectCatalogStream({ kind: 'gemini', api_key: 'secret' }, event => seen.push(event),
      async () => makeResponse([
        'data: {"type":"testing","model_id":"a"}\n\n',
        'data: {"type":"failed","model_id":"a","message":"HTTP 400"}\n\n',
        'data: {"type":"error","message":"Nenhum modelo respondeu."}\n\n',
      ])),
    /Nenhum modelo respondeu/)
  assert.deepEqual(seen.map(e => e.type), ['testing', 'failed', 'error'])
})

test('reports HTTP errors without requiring an SSE body', async () => {
  await assert.rejects(
    connectCatalogStream({ kind: 'gemini' }, () => {}, async () =>
      new Response(JSON.stringify({ detail: 'Sessão expirada.' }),
        { status: 401, headers: { 'content-type': 'application/json' } })),
    /Sessão expirada/)
})

test('treats disconnected streams without a terminal event as incomplete', async () => {
  await assert.rejects(
    connectCatalogStream({ kind: 'gemini' }, () => {}, async () =>
      makeResponse(['data: {"type":"testing","model_id":"a"}\n\n'])),
    /interrompido/)
})
