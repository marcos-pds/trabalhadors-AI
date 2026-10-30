export const providerFilters = [
  ['all', 'Todos'], ['free', 'Gratuitos'], ['paid', 'Pagos'],
  ['trial', 'Créditos / avaliação'], ['verify', 'Verificar condições'], ['local', 'Local'],
]

export function providerCategory(provider) {
  const { kind } = provider
  if (['ollama', 'lmstudio', 'localai', 'jan', 'vllm', 'llamacpp'].includes(kind) ||
      /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(?::|\/|$)/i.test(provider.base_url || '')) return 'local'
  if (['groq', 'gemini', 'openrouter', 'mistral', 'sambanova', 'zai', 'cloudflare'].includes(kind)) return 'free'
  if (['huggingface', 'cohere', 'nvidia', 'cerebras'].includes(kind)) return 'trial'
  if (['openai', 'anthropic', 'deepseek', 'grok', 'together', 'fireworks', 'perplexity', 'deepinfra', 'novita'].includes(kind)) return 'paid'
  return 'verify'
}
