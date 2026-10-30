/**
 * Read a POST-based SSE connection trace. Unlike EventSource, POST lets us send
 * credentials in the request body without ever placing an API key in a URL.
 */
export async function connectCatalogStream(payload, onEvent, fetchImpl = fetch) {
  const response = await fetchImpl('/api/provider-catalog/connect/stream', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-Central-Request': '1' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    let detail = 'Não foi possível iniciar o teste de conexão.'
    try {
      const result = await response.json()
      detail = typeof result.detail === 'string' ? result.detail : detail
    } catch { /* Preserve generic error when response is not JSON. */ }
    throw new Error(detail)
  }
  if (!response.body) throw new Error('O navegador não recebeu o fluxo de tentativas.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let terminal = null

  function processFrame(frame) {
    const data = frame.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart()).join('\n')
    if (!data) return
    const event = JSON.parse(data)
    if (!event || typeof event.type !== 'string') return
    onEvent(event)
    if (event.type === 'connected' || event.type === 'error') terminal = event
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, '\n')
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        processFrame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) processFrame(buffer)
  } finally {
    reader.releaseLock()
  }

  if (!terminal) throw new Error('O teste foi interrompido antes de concluir. Consulte as tentativas exibidas.')
  if (terminal.type === 'error') throw new Error(terminal.message || 'Os modelos não responderam ao teste.')
  return terminal
}
