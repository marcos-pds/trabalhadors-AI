import { useEffect, useRef, useState } from 'react'
import { providerCategory, providerFilters } from './providerFilters'
import { connectCatalogStream } from './catalogConnectionStream'

const control = 'min-h-11 rounded-xl border border-white/10 bg-[#191919] px-3 text-sm text-copy outline-none focus:border-lilac/60 disabled:opacity-50'
const button = 'min-h-10 rounded-xl border border-white/10 px-4 text-xs font-semibold transition hover:bg-white/10 disabled:opacity-50 disabled:cursor-wait'
const primary = button + ' border-lilac/30 bg-lilac/15 text-lilac'

export default function ProviderCatalog({ api, providers, onConnected, onManual, presets = [], filter, onFilter }) {
  const [catalog, setCatalog] = useState(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setError('')
    api('/provider-catalog').then(items => { if (active) setCatalog(items) })
      .catch(e => { if (active) setError(e.message === 'Not Found'
        ? 'O servidor em execução ainda não tem a rota do catálogo. Encerre a Central com Ctrl + C, execute iniciar_windows.bat novamente e atualize esta página com Ctrl + F5.'
        : e.message) })
    return () => { active = false }
  }, [api, retry])
  const online = catalog?.filter(p => p.quick && p.kind !== 'ollama') || []
  const verified = p => providers.some(c => c.kind === p.kind && c.enabled && c.health?.state === 'healthy')
  const done = online.filter(verified).length
  const next = online.find(p => !verified(p))
  const services = [...(catalog || []), ...presets.filter(p => !(catalog || []).some(c => c.kind === p.kind))]
  const visible = services.filter(p =>
    (filter === 'all' || providerCategory(p) === filter) &&
    `${p.name} ${p.access} ${p.note}`.toLocaleLowerCase('pt-BR').includes(query.toLocaleLowerCase('pt-BR')))
  return <>
    <section className="mb-6 rounded-3xl border border-lilac/20 bg-gradient-to-br from-lilac/[.08] to-transparent p-6">
      <span className="text-[10px] font-bold uppercase tracking-widest text-lilac">Conexão simplificada</span>
      <h2 className="mt-2 text-2xl font-semibold">Sua chave. O restante é automático.</h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">Escolha um serviço, cole a chave e clique em Conectar. A Central consulta o catálogo oficial, seleciona um modelo de chat elegível e valida uma resposta antes de salvar.</p>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <span className="rounded-xl border border-white/10 px-3 py-2 text-xs">{done}/{online.length} serviços online com conexão ativa e teste aprovado</span>
        {next && <button className={primary} onClick={() => setSelected(next)}>Próximo: {next.name}</button>}
      </div>
      <p className="mt-3 text-[11px] leading-5 text-muted">Use contas nos planos gratuitos. Listar um modelo não confirma saldo, cota ou plano de cobrança. Créditos e avaliações aparecem separados. O Ollama continua como único serviço local sugerido.</p>
    </section>
    <div className="mb-4 flex flex-wrap items-center gap-2">
      {providerFilters.map(([id, label]) =>
        <button key={id} onClick={() => onFilter(id)} aria-pressed={filter === id} className={filter === id ? primary : button}>{label} ({services.filter(p => id === 'all' || providerCategory(p) === id).length})</button>)}
      <input aria-label="Buscar serviço no catálogo" placeholder="Buscar serviço ou condição..." value={query} onChange={e => setQuery(e.target.value)} className={control + ' w-full sm:ml-auto sm:w-64'} />
    </div>
    <p className="mb-4 text-[11px] leading-5 text-muted">O filtro também se aplica às conexões abaixo. Gratuitos reúne serviços com faixa ou modelos gratuitos; confirme o plano da conta e o modelo. Créditos promocionais e avaliações ficam separados.</p>
    {error && <p role="alert" className="mb-4 text-sm text-rose-300">{error} <button className={button} onClick={() => setRetry(n => n + 1)}>Tentar novamente</button></p>}
    {!catalog && !error && <p role="status" className="py-6 text-sm text-muted">Carregando catálogo de serviços...</p>}
    <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {visible.map((p) => <article key={p.kind} className="flex flex-col rounded-2xl border border-white/10 bg-panel p-5">
        <div className="flex items-start justify-between gap-3"><h3 className="text-sm font-semibold">{p.name}</h3><span className="rounded-full bg-white/5 px-2 py-1 text-[9px] text-muted">{p.access}</span></div>
        <p className="mt-3 flex-1 text-xs leading-5 text-muted">{p.note}</p>
        <p className={'mt-3 text-[11px] ' + (verified(p) ? 'text-emerald-300' : 'text-muted')}>{verified(p) ? 'Conexão ativa · teste aprovado' : providers.some(c => c.kind === p.kind) ? 'Cadastro existente · validar conexão' : 'Ainda não conectado'}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className={primary} onClick={() => p.quick ? setSelected(p) : onManual(p.kind)}>{p.quick ? (p.kind === 'ollama' ? 'Conectar local' : 'Conectar') : 'Configurar manualmente'}</button>
          <a className={button + ' inline-flex items-center'} href={p.keys_url} target="_blank" rel="noopener noreferrer">{p.kind === 'ollama' ? 'Ollama' : 'Obter chave'}</a>
        </div>
        <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="mt-3 text-[10px] text-muted underline">Condições oficiais · revisão {p.checked_at}</a>
      </article>)}
    </div>
    {catalog && !visible.length && <p className="mb-6 text-sm text-muted">Nenhum serviço encontrado para esta busca.</p>}
    {selected && <ConnectDialog key={selected.kind} service={selected} api={api}
      saved={providers.find(p => p.kind === selected.kind && p.has_key)}
      onClose={() => setSelected(null)} onConnected={onConnected} />}
  </>
}

function ConnectDialog({ service, api, saved, onClose, onConnected }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [models, setModels] = useState(null)
  const [model, setModel] = useState('')
  const [confirmCharges, setConfirmCharges] = useState(false)
  const [search, setSearch] = useState('')
  const [result, setResult] = useState(null)
  const [attempts, setAttempts] = useState([])
  const input = useRef(null)
  useEffect(() => { input.current?.focus() }, [])
  const payload = () => ({ kind: service.kind, api_key: key, provider_id: saved?.id, model })
  const allowed = service.kind === 'ollama' || !!key.trim() || !!saved
  const hasNewModels = !models || models.some(m => m.eligible && !m.connected)
  const chosen = models?.find(m => m.id === model)
  const manualAllowed = !!chosen && !chosen.connected && (chosen.billing === 'free' || chosen.billing === 'local' || confirmCharges)
  const changeKey = value => { setKey(value); setModels(null); setModel(''); setConfirmCharges(false); setAttempts([]); setError('') }
  async function discover() {
    setBusy('Buscando modelos disponíveis...'); setError(''); setAttempts([])
    try { const data = await api('/provider-catalog/models', 'POST', payload()); setModels(data.models); setModel(''); setConfirmCharges(false) }
    catch (e) { setError(e.message) }
    finally { setBusy('') }
  }
  async function connect(e) {
    e.preventDefault()
    if (model && !manualAllowed) return
    setBusy('Testando modelos e registrando cada tentativa...')
    setError('')
    setAttempts([])
    try {
      const data = await connectCatalogStream(payload(), event => {
        if (event.type === 'testing') {
          setBusy('Testando ' + event.model_name + '...')
          setAttempts(history => [...history, {
            id: event.model_id, name: event.model_name,
            status: 'testing', position: event.position, total: event.total,
          }])
        } else if (event.type === 'failed') {
          setAttempts(history => history.map(entry => entry.id === event.model_id ? {
            ...entry, status: 'failed', reason: event.message,
            category: event.category, httpStatus: event.http_status,
            nextModel: event.next_model,
          } : entry))
          setBusy(event.next_model ? 'Próximo modelo: ' + event.next_model.name : 'Finalizando tentativa...')
        } else if (event.type === 'passed') {
          setAttempts(history => history.map(entry => entry.id === event.model_id ? {
            ...entry, status: 'passed', latency: event.latency_ms,
          } : entry))
          setBusy('Modelo validado. Salvando conexão...')
        }
      })
      setKey('')
      setModels(data.models)
      setResult(data)
      try { await onConnected() } catch { setError('Conexão salva. Atualize a página para recarregar a lista.') }
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }
  const visible = (models || []).filter(m => `${m.id} ${m.name}`.toLocaleLowerCase('pt-BR').includes(search.toLocaleLowerCase('pt-BR')))
  const accessLabel = m => m.billing === 'paid' ? 'Pago' : m.billing === 'free' ? (service.kind === 'sambanova' ? 'Free Tier documentado' : 'Gratuito elegível') : m.billing === 'local' ? 'Local' : 'Preço não confirmado'
  return <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" onKeyDown={e => { if (e.key === 'Escape' && !busy) onClose() }}>
    <section role="dialog" aria-modal="true" aria-labelledby="connect-title" className="my-auto max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-3xl border border-white/10 bg-[#1f1f1f] p-6 shadow-2xl">
      <div className="flex items-center justify-between gap-4"><h2 id="connect-title" className="text-xl font-semibold">Conectar {service.name}</h2><button className={button} onClick={onClose} disabled={!!busy} aria-label="Fechar">×</button></div>
      {result ? <>
        <div role="status" className="mt-5 rounded-2xl border border-emerald-400/20 bg-emerald-400/5 p-4">
          <h3 className="font-semibold text-emerald-300">Conectado e testado</h3>
          <p className="mt-2 text-sm">{result.provider.name}</p><p className="mt-1 break-all font-mono text-xs text-muted">{result.model.id}</p>
          <p className="mt-3 text-xs text-muted">{result.models.length} modelos de chat encontrados. A chave foi armazenada com criptografia.</p>
        </div>
        <AttemptHistory attempts={attempts} />
        <button className={primary + ' mt-5 w-full'} onClick={onClose}>Concluir e conectar o próximo</button>
      </> : <form onSubmit={connect}>
        <p className="mt-4 text-xs leading-5 text-muted">{service.note}</p>
        {service.kind !== 'ollama' && <>
          <label className="mt-5 block text-xs text-muted" htmlFor="connection-key">Chave API {saved ? '(em branco usa a chave salva)' : ''}</label>
          <input ref={input} id="connection-key" type="password" value={key} onChange={e => changeKey(e.target.value)} autoComplete="new-password" spellCheck={false} disabled={!!busy} className={control + ' mt-2 w-full'} placeholder={saved ? 'Chave já armazenada' : 'Cole sua chave aqui'} />
          <a className="mt-2 inline-block text-xs text-lilac underline" href={service.keys_url} target="_blank" rel="noopener noreferrer">Obter chave no site oficial</a>
        </>}
        <details className="mt-5 rounded-2xl border border-white/10 p-4">
          <summary className="cursor-pointer text-xs text-muted">Ver catálogo e escolher um modelo específico (grátis ou pago)</summary>
          <button type="button" className={button + ' mt-4'} disabled={!allowed || !!busy} onClick={discover}>Buscar catálogo oficial</button>
          {models && <>
            <p className="mt-3 text-xs text-muted">{models.length} modelos de chat · {models.filter(m => m.eligible && !m.connected).length} candidatos à conexão automática de acordo com a documentação, sem garantia de saldo. Todos os modelos de chat não cadastrados podem ser escolhidos manualmente. Acesso e cobrança dependem da sua conta.</p>
            <input aria-label="Buscar modelo" value={search} onChange={e => setSearch(e.target.value)} placeholder="Buscar nome ou identificador..." className={control + ' mt-3 w-full'} />
            <label htmlFor="catalog-model" className="mt-3 block text-xs text-muted">Modelo para conexão</label>
            <select id="catalog-model" value={model} onChange={e => { setModel(e.target.value); setConfirmCharges(false) }} disabled={!!busy} className={control + ' mt-2 w-full'}>
              <option value="">Automático · testar até 3 opções ainda não cadastradas</option>
              {models.map(m => <option key={m.id} value={m.id} disabled={m.connected}>{m.name} · {m.id} · {accessLabel(m)}{m.connected ? ' · Já cadastrado' : ''}</option>)}
            </select>
            {chosen && <p className="mt-3 text-xs text-lilac">Selecionado: {chosen.name} · {chosen.access}</p>}
            {chosen && !['free', 'local'].includes(chosen.billing) && <label className="mt-3 flex items-start gap-2 text-xs leading-5 text-amber-200"><input type="checkbox" checked={confirmCharges} onChange={e => setConfirmCharges(e.target.checked)} className="mt-1 accent-violet-400"/> Entendo que este modelo pode gerar cobranças e que minha conta precisa ter acesso autorizado.</label>}
            <div className="mt-3 max-h-52 overflow-y-auto">{visible.map(m => <div key={m.id} className="border-t border-white/10 py-3 text-xs"><strong>{m.name}</strong><span className="ml-2 text-[10px] text-lilac">{accessLabel(m)}</span><span className="mt-1 block break-all font-mono text-muted">{m.id}</span><small className="mt-1 block text-muted">{m.connected ? "Já cadastrado" : m.access}{m.context_length ? ` · Contexto: ${m.context_length.toLocaleString('pt-BR')} tokens` : ''}</small><small className="mt-1 block text-muted">{m.source}</small></div>)}</div>
          </>}
        </details>
        <AttemptHistory attempts={attempts} />
        {error && <div role="alert" className="mt-4 rounded-xl border border-rose-400/20 bg-rose-400/5 p-3">
          <p className="text-sm text-rose-300">{error}</p>
          {service.kind === 'sambanova' && /crédit|saldo|cobrança/i.test(error) &&
            <a href="https://cloud.sambanova.ai/plans/billing" target="_blank" rel="noopener noreferrer"
              className="mt-2 inline-block text-xs font-semibold text-lilac underline">Conferir saldo e cobrança na SambaNova ↗</a>}
        </div>}
        {busy && <p role="status" className="mt-4 text-xs text-lilac">{busy}</p>}
        {!hasNewModels && <p role="status" className="mt-4 text-xs text-muted">Nenhum modelo novo elegível. Os modelos já cadastrados podem ser gerenciados em Editar.</p>}
        <div className="mt-5 flex flex-col gap-2 sm:flex-row"><button type="submit" className={primary + ' flex-1'} disabled={!allowed || !!busy || (model ? !manualAllowed : !hasNewModels)}>{busy ? 'Conectando...' : model ? 'Conectar modelo selecionado' : 'Conectar automaticamente'}</button>{model && <button type="button" className={button} disabled={!!busy} onClick={() => { setModel(''); setConfirmCharges(false) }}>Voltar ao automático</button>}</div>
        <p className="mt-3 text-[10px] leading-4 text-muted">A validação faz uma chamada real e pode consumir créditos ou gerar cobrança. No automático, apenas modelos elegíveis são testados; na seleção manual, somente o modelo escolhido será testado.</p>
      </form>}
    </section>
  </div>
}


const connectionErrorLabels = {
  authentication: 'Autenticação ou permissão',
  credits: 'Créditos / faturamento',
  request: 'Requisição rejeitada',
  response: 'Resposta inválida',
  rate_limit: 'Limite de requisições',
  timeout: 'Tempo limite',
  unavailable: 'Provedor indisponível',
  network: 'Erro de rede',
  validation: 'Falha na validação',
}

function AttemptHistory({ attempts }) {
  if (!attempts.length) return null
  return <section aria-label="Histórico de tentativas de conexão" className="mt-5 rounded-2xl border border-white/10 bg-black/15 p-4">
    <div className="mb-3 flex items-center justify-between gap-3">
      <h3 className="text-sm font-semibold">Histórico de tentativas</h3>
      <span className="text-[11px] text-muted">{attempts.length} modelo(s) testado(s)</span>
    </div>
    <ol className="space-y-3">
      {attempts.map(attempt => <li key={attempt.id} className="rounded-xl border border-white/10 bg-white/[.03] p-3 text-xs">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <strong className="break-words text-copy">{attempt.position}. {attempt.name}</strong>
            <span className="mt-1 block break-all font-mono text-[10px] text-muted">{attempt.id}</span>
          </div>
          <span className={'shrink-0 rounded-lg px-2 py-1 text-[10px] ' +
            (attempt.status === 'passed' ? 'bg-emerald-400/10 text-emerald-300' :
              attempt.status === 'failed' ? 'bg-rose-400/10 text-rose-300' :
                'bg-lilac/15 text-lilac')}>
            {attempt.status === 'passed' ? 'Aprovado' : attempt.status === 'failed' ? 'Falhou' : 'Testando...'}
          </span>
        </div>
        {attempt.status === 'failed' && <>
          <p className="mt-2 break-words leading-5 text-rose-200">{attempt.reason}</p>
          <p className="mt-1 text-[10px] text-muted">Categoria: {connectionErrorLabels[attempt.category] || attempt.category || 'Desconhecida'}{attempt.httpStatus ? ' · HTTP ' + attempt.httpStatus : ''}</p>
          <p className="mt-2 text-[11px] text-muted">
            {attempt.nextModel ? <>Próximo modelo: <strong className="text-lilac">{attempt.nextModel.name}</strong></> :
              'Sem nova tentativa automática após este erro.'}
          </p>
        </>}
        {attempt.status === 'passed' && <p className="mt-2 text-emerald-200">Resposta validada{attempt.latency != null ? ' · ' + attempt.latency + ' ms' : ''}.</p>}
      </li>)}
    </ol>
  </section>
}
