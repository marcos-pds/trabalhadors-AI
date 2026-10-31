const adapters = [
  { id: 'comfyui_wan', name: 'ComfyUI / Wan', stage: 'generate', purpose: 'Geração de vídeo',
    diagnostic: 'A detecção do ComfyUI exige configuração explícita no servidor. Pesos Wan, GPU e conexão com o serviço ainda precisam de verificação.' },
  { id: 'remotion', name: 'Remotion', stage: 'compose', purpose: 'Composição de cenas',
    diagnostic: 'Confira se o executável Remotion está disponível no ambiente do servidor. Composições e navegador ainda precisam de verificação.' },
  { id: 'whisperx', name: 'WhisperX', stage: 'transcribe', purpose: 'Transcrição e alinhamento',
    diagnostic: 'Confira se o executável WhisperX está disponível no ambiente do servidor. Modelos, alinhamento e recursos de GPU ainda precisam de verificação.' },
  { id: 'ffmpeg', name: 'FFmpeg', stage: 'encode', purpose: 'Codificação de mídia',
    diagnostic: 'Confira se o executável FFmpeg está disponível no ambiente do servidor. Codecs e processamento de arquivos ainda precisam de verificação.' },
]

const invalid = () => new Error('O servidor retornou um inventário Motion inválido. Recarregue ou confira a versão do servidor.')

export function motionCapabilityRows(inventory) {
  if (!inventory || typeof inventory !== 'object' || Array.isArray(inventory)) throw invalid()
  return adapters.map(adapter => {
    const item = inventory[adapter.id]
    if (!item || typeof item !== 'object' || Array.isArray(item) || item.stage !== adapter.stage ||
        ['contract_implemented', 'installed', 'execution_supported', 'endpoint_configured'].some(key => typeof item[key] !== 'boolean') ||
        typeof item.service_status !== 'string' || item.service_status.length > 64 ||
        !(item.version === null || (typeof item.version === 'string' && item.version.length > 0 && item.version.length <= 128)) ||
        !(item.version_source === null || item.version_source === 'package_metadata')) throw invalid()
    return {
      ...adapter,
      installed: item.installed,
      installation: item.installed ? 'Detectado no servidor' : 'Não detectado',
      contract: item.contract_implemented ? 'Implementado' : 'Não implementado',
      // This endpoint supplies presence/metadata, never render verification evidence.
      verification: 'Não verificado',
      rendering: item.service_status === 'pending' ? 'Serviço pendente' : 'Estado do serviço não reconhecido',
      execution: item.execution_supported ? 'Suporte declarado; execução não verificada' : 'Execução indisponível',
      version: item.version || 'Não descoberta',
      versionSource: item.version_source === 'package_metadata' ? 'Metadados do pacote; sem teste de execução' : 'Sem versão verificada por execução',
      endpoint: adapter.id === 'comfyui_wan'
        ? (item.endpoint_configured ? 'Endpoint configurado; conexão não verificada' : 'Endpoint não configurado nesta consulta') : null,
    }
  })
}

export async function loadMotionCapabilities(api, timeoutMs = 10000) {
  let timer
  try {
    const response = await Promise.race([
      Promise.resolve().then(() => api('/motion/capabilities', 'GET')),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('A consulta Motion demorou demais. Confira a conexão com o servidor e tente novamente.')), timeoutMs)
      }),
    ])
    return motionCapabilityRows(response)
  } finally {
    clearTimeout(timer)
  }
}
