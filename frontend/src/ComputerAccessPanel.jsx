import { useEffect, useState } from 'react'

const modeLabels = {
  blocked: 'Bloqueado',
  ask: 'Solicitar permissão',
  full: 'Acesso total à pasta',
}
const control = 'mt-2 w-full rounded-xl border border-white/10 bg-[#17171a] px-3 py-3 text-xs text-copy outline-none focus:border-lilac/60'
const button = 'rounded-xl border border-white/15 bg-white/[.04] px-3 py-2 text-xs font-medium text-copy hover:bg-white/[.09] disabled:cursor-not-allowed disabled:opacity-40'

export default function ComputerAccessPanel({ api, onClose, onSaved, onAttach }) {
  const [saved, setSaved] = useState(null)
  const [mode, setMode] = useState('blocked')
  const [folder, setFolder] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(null)
  const [path, setPath] = useState('')
  const [listing, setListing] = useState(null)
  const [preview, setPreview] = useState(null)

  useEffect(() => {
    let active = true
    api('/computer-access').then(policy => {
      if (!active) return
      setSaved(policy); setMode(policy.mode); setFolder(policy.folder || '')
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [api])

  async function save(e) {
    e.preventDefault()
    if (busy) return
    if (mode === 'full' && !window.confirm(
      'Atenção: os agentes poderão editar arquivos e executar builds/testes/instaladores de pacotes dentro desta pasta quando Autonomia estiver ligada. Esses comandos executam código real do projeto e NÃO estão isolados do Windows. Continuar?')) return
    setBusy('saving'); setError(''); setPending(null)
    try {
      const result = await api('/computer-access', 'PUT', { mode, folder: mode === 'blocked' ? '' : folder.trim() })
      setSaved(result); setMode(result.mode); setFolder(result.folder || '')
      setListing(null); setPreview(null); setPath('')
      onSaved(result)
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }

  async function action(type, relativePath = '') {
    setBusy('action'); setError(''); setPending(null)
    try {
      const result = await api('/computer-access/action', 'POST', {
        action: type, relative_path: relativePath,
      })
      if (result.status === 'approval_required') {
        setPending(result)
      } else {
        showResult(result.result)
      }
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }

  function showResult(result) {
    if (!result) return
    if (result.action === 'list') {
      setPath(result.path || ''); setListing(result); setPreview(null)
    } else if (result.action === 'read') {
      setPreview(result)
    }
  }

  async function decision(approve) {
    if (!pending) return
    setBusy('approving'); setError('')
    try {
      const result = await api('/computer-access/approvals/' +
        encodeURIComponent(pending.request_id) + '/decision', 'POST', { approve })
      setPending(null)
      if (result.status === 'completed') showResult(result.result)
    } catch (e) { setError(e.message); setPending(null) } finally { setBusy('') }
  }

  const configured = saved && saved.mode !== 'blocked'
  const unsaved = saved && (saved.mode !== mode || saved.folder !== (mode === 'blocked' ? '' : folder.trim()))
  const join = (a, b) => a ? a + '/' + b : b

  return <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/75 p-3 backdrop-blur-sm sm:p-5" onKeyDown={e => { if (e.key === 'Escape' && !busy) onClose() }}>
    <section role="dialog" aria-modal="true" aria-labelledby="computer-access-title"
      className="my-auto max-h-[94vh] w-full max-w-xl overflow-y-auto rounded-3xl border border-white/15 bg-[#212125] p-5 shadow-2xl sm:p-7">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 id="computer-access-title" className="text-lg font-semibold">Acesso ao computador</h2>
          <p className="mt-2 text-xs leading-5 text-muted">
            Configure a permissão para uma pasta específica deste Windows. Padrão: bloqueado.
          </p>
        </div>
        <button type="button" aria-label="Fechar" className={button} onClick={onClose}>✕</button>
      </header>

      <form onSubmit={save} className="mt-5 space-y-3">
        <fieldset>
          <legend className="mb-2 text-xs font-semibold">Modo de autorização</legend>
          {[
            { id: 'blocked', icon: '🔒', help: 'Impede leitura, edição e execução de ferramentas locais.' },
            { id: 'ask', icon: '🛡', help: 'Cada leitura, edição ou comando solicitado pelos agentes exige sua aprovação.' },
            { id: 'full', icon: '📁', help: 'Os agentes com Autonomia ativada podem editar código, instalar pacotes e testar sem pedir novamente dentro do workspace.' },
          ].map(item => <label key={item.id} className={'mb-2 flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-3 transition ' +
            (mode === item.id ? 'border-lilac/60 bg-lilac/[.08]' : 'border-white/10 hover:bg-white/[.04]')}>
            <input type="radio" name="computer-mode" checked={mode === item.id}
              onChange={() => setMode(item.id)} className="mt-1 accent-violet-400"/>
            <span className="text-base">{item.icon}</span>
            <span className="min-w-0">
              <strong className="block text-xs text-copy">{modeLabels[item.id]}</strong>
              <small className="mt-1 block text-[11px] leading-4 text-muted">{item.help}</small>
            </span>
          </label>)}
        </fieldset>

        {mode !== 'blocked' && <label className="block text-xs text-muted">
          Pasta autorizada (caminho completo no computador)
          <input value={folder} onChange={e => setFolder(e.target.value)} className={control}
            placeholder="C:\Users\...\Documents\MeuProjeto" autoComplete="off" spellCheck={false}/>
          <small className="mt-2 block leading-4 text-muted">
            No Explorador de Arquivos ou VS Code, copie o caminho de uma pasta específica e cole aqui.
            O navegador não concede acesso a todo o disco automaticamente.
          </small>
          <button type="button" className={button + ' mt-3'} disabled={!!busy}
            onClick={async () => {
              setBusy('folder'); setError('')
              try {
                const suggestion = await api('/computer-access/default-folder')
                setFolder(suggestion.folder)
              } catch (e) { setError(e.message) } finally { setBusy('') }
            }}>Usar pasta da Central IA</button>
        </label>}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-[11px] text-muted">Permissão atual: <strong className="text-lilac">{modeLabels[saved?.mode] || 'Carregando...'}</strong></span>
          <button type="submit" disabled={!saved || !!busy || !unsaved} className={button + ' border-lilac/50 text-lilac'}>
            {busy === 'saving' ? 'Salvando...' : mode === 'blocked' ? 'Bloquear acesso' : 'Salvar permissão'}
          </button>
        </div>
      </form>

      <section className="mt-5 rounded-2xl border border-white/10 bg-black/10 p-4">
        <h3 className="text-xs font-semibold">Arquivos da pasta autorizada</h3>
        <p className="mt-2 text-[11px] leading-5 text-muted">
          Aqui você pode listar pastas e visualizar textos/código de até 64 KB. Com a opção Autonomia
          do chat ativada, os trabalhadores também podem criar e editar código, instalar dependências na pasta e executar
          builds e testes. Mouse, janelas, comandos irrestritos e exclusão de arquivos continuam bloqueados.
          Execução de scripts de projetos e pacotes não é um sandbox de segurança do Windows.
        </p>
        {configured && <div className="mt-3 break-all rounded-lg bg-black/20 p-2 font-mono text-[10px] text-muted">{saved.folder}</div>}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="button" disabled={!configured || !!busy || !!unsaved} className={button}
            onClick={() => action('list', '')}>📂 Explorar pasta</button>
          {listing && <button type="button" disabled={!!busy} className={button}
            onClick={() => action('list', path.split('/').slice(0, -1).join('/'))}>↑ Voltar</button>}
        </div>

        {listing && <div className="mt-3 max-h-44 space-y-1 overflow-y-auto rounded-xl border border-white/10 p-2">
          <p className="px-1 text-[10px] text-muted">{listing.path || 'Pasta raiz'} · {listing.items.length} item(ns) exibido(s)</p>
          {listing.items.map(item => <button key={item.name} type="button" className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs hover:bg-white/[.07]"
            disabled={!!busy} onClick={() => action(item.type === 'folder' ? 'list' : 'read', join(path, item.name))}>
            <span>{item.type === 'folder' ? '📁' : '📄'}</span><span className="truncate">{item.name}</span>
          </button>)}
          {!listing.items.length && <p className="px-2 py-3 text-xs text-muted">Pasta vazia ou sem arquivos visualizáveis.</p>}
        </div>}

        {pending && <div role="alertdialog" aria-label="Solicitação de acesso" className="mt-3 rounded-xl border border-amber-300/30 bg-amber-300/[.05] p-3">
          <strong className="block text-xs text-amber-200">Permissão necessária para esta ação</strong>
          <p className="mt-2 break-all text-xs text-muted">{pending.action === 'read' ? 'Ler arquivo' : 'Listar pasta'}: {pending.path || 'Pasta autorizada'}</p>
          <p className="mt-1 text-[10px] text-muted">A autorização expira em 5 minutos e serve somente para esta operação.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className={button} disabled={!!busy} onClick={() => decision(false)}>Negar</button>
            <button type="button" className={button + ' border-emerald-300/30 text-emerald-200'} disabled={!!busy} onClick={() => decision(true)}>Permitir uma vez</button>
          </div>
        </div>}

        {preview && <div className="mt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <strong className="break-all text-xs">📄 {preview.path}</strong>
            <button className={button} type="button" onClick={() => {
              onAttach({name: preview.path, content: preview.content})
              onClose()
            }}>＋ Anexar ao chat</button>
          </div>
          <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-[#141416] p-3 text-[11px] text-muted">{preview.content}</pre>
          <p className="mt-2 text-[10px] text-muted">Somente ao anexar e enviar sua mensagem esse conteúdo será encaminhado ao modelo de IA.</p>
        </div>}
      </section>
      {error && <p role="alert" className="mt-4 rounded-xl border border-rose-300/20 bg-rose-400/[.05] p-3 text-xs text-rose-300">{error}</p>}
    </section>
  </div>
}
