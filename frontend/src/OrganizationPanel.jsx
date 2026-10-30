import { useEffect, useState } from 'react'

const field = 'w-full rounded-xl border border-white/15 bg-[#19191e] px-3 py-2 text-xs text-copy outline-none focus:border-violet-400'
const button = 'rounded-xl border border-white/15 px-3 py-2 text-xs text-copy hover:bg-white/[.08] disabled:opacity-40'

export default function OrganizationPanel({ api, onProjectCreate, onUpdated }) {
  const [organizations, setOrganizations] = useState([])
  const [selected, setSelected] = useState('')
  const [members, setMembers] = useState([])
  const [usage, setUsage] = useState(null)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const [newName, setNewName] = useState('')
  const [memberEmail, setMemberEmail] = useState('')
  const [memberRole, setMemberRole] = useState('operator')
  const [hostConfirm, setHostConfirm] = useState('')
  const [budget, setBudget] = useState('')
  const [daily, setDaily] = useState(100)
  const [active, setActive] = useState(4)

  async function load() {
    const orgs = await api('/organizations')
    setOrganizations(orgs)
    setSelected(old => orgs.some(o => o.id === old) ? old : (orgs[0]?.id || ''))
  }
  useEffect(() => { load().catch(e => setError(e.message)) }, [api])
  const current = organizations.find(o => o.id === selected)

  useEffect(() => {
    if (!selected) return
    let mounted = true
    Promise.all([api('/organizations/' + selected + '/members'),
                 api('/organizations/' + selected + '/usage')])
      .then(([m,u]) => {
        if (!mounted) return
        setMembers(m); setUsage(u)
        setDaily(u.limits.daily_run_limit)
        setActive(u.limits.active_run_limit)
        setBudget(u.limits.estimated_budget_usd == null ? '' : String(u.limits.estimated_budget_usd))
      }).catch(e => { if (mounted) setError(e.message) })
    return () => { mounted = false }
  }, [api, selected, organizations.length])

  async function action(fn, success) {
    if (busy) return
    setBusy(true); setError(''); setInfo('')
    try {
      await fn()
      await load()
      if (selected) {
        const [m,u] = await Promise.all([
          api('/organizations/' + selected + '/members'),
          api('/organizations/' + selected + '/usage')])
        setMembers(m); setUsage(u)
      }
      onUpdated?.()
      setInfo(success)
    } catch(e) { setError(e.message) }
    finally { setBusy(false) }
  }

  return <section className="mb-6 space-y-3 rounded-2xl border border-white/10 bg-panel p-5"
      aria-label="Organizações e membros">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-sm font-semibold">Organizações e permissões</h2>
        <p className="mt-1 text-[11px] text-muted">Projetos por empresa; chaves, agentes e conversas privadas permanecem pessoais.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <select aria-label="Organização selecionada" value={selected}
          onChange={e => setSelected(e.target.value)} className={field + ' max-w-[240px]'}>
          {organizations.map(org => <option key={org.id} value={org.id}>{org.name} · {org.role}</option>)}
        </select>
        <button className={button} onClick={()=>onProjectCreate(selected)} disabled={!selected}>＋ Projeto nesta organização</button>
      </div>
    </div>
    <form className="flex flex-wrap gap-2" onSubmit={e => {
      e.preventDefault()
      if (newName.trim().length < 2) return
      action(async () => {
        const org = await api('/organizations','POST',{name:newName.trim()})
        setNewName(''); setSelected(org.id)
      }, 'Organização criada.')
    }}>
      <input className={field + ' max-w-xs flex-1'} value={newName} onChange={e=>setNewName(e.target.value)}
        placeholder="Nome da nova organização" minLength={2} maxLength={90} aria-label="Nome da organização"/>
      <button className={button} disabled={busy || newName.trim().length < 2}>Criar organização</button>
    </form>
    {current && <div className="border-t border-white/10 pt-4">
      <p className="mb-3 text-xs font-semibold">{current.name}
        <span className="ml-2 text-[10px] text-muted">{current.is_personal ? 'Espaço privado' : 'Workspace de equipe'} · {current.role}</span>
      </p>
      {usage && <p className="mb-4 text-[11px] text-muted">Tarefas nas últimas 24h: {usage.daily_runs}/{usage.limits.daily_run_limit}
        {' · '}Ativas: {usage.active_runs}/{usage.limits.active_run_limit}
        {' · '}Custo registrado (estimado): US$ {Number(usage.estimated_spend_usd).toFixed(4)}
      </p>}
      <div className="space-y-2">
        {members.map(person => <div key={person.id} className="flex flex-wrap items-center gap-2 border-b border-white/[.06] pb-2 text-xs">
          <span className="min-w-0 flex-1 truncate">{person.email}</span>
          <span className="text-muted">{person.role}</span>
          {current.role==='admin' && !current.is_personal &&
            <button type="button" className={button} disabled={busy}
              onClick={()=>action(()=>api('/organizations/'+selected+'/members/'+person.id,'DELETE'),
                                'Membro removido.')} title="Remover membro da organização">Remover</button>}
        </div>)}
      </div>
      {current.role==='admin' && !current.is_personal && <>
        <section className="mt-4 rounded-xl border border-amber-300/25 bg-amber-300/[.04] p-3">
          <p className="text-xs font-semibold text-amber-200">Execução de comandos no Windows</p>
          <p className="mt-1 text-[11px] leading-5 text-muted">Por padrão, organizações de equipe não podem executar scripts npm/pip ou testes locais. Habilitar esta opção concede execução com os privilégios do servidor, sem isolamento de sistema operacional. Use apenas projetos confiáveis e pastas dedicadas. Instalações ainda exigem aprovação específica.</p>
          <p className="mt-2 text-[11px] text-muted">Estado: {current.host_commands_enabled ? 'Habilitado (sem sandbox)' : 'Bloqueado'}</p>
          {!current.host_commands_enabled && <input aria-label="Confirmação de execução local" placeholder="Digite AUTORIZO EXECUCAO LOCAL" value={hostConfirm}
            onChange={e => setHostConfirm(e.target.value)} className={field + ' mt-2'} />}
          <button type="button" disabled={busy || (!current.host_commands_enabled && hostConfirm !== 'AUTORIZO EXECUCAO LOCAL')}
            className={button + ' mt-2'} onClick={() => action(async () => {
              await api('/organizations/'+selected+'/host-commands','PUT',
                        {enabled:!current.host_commands_enabled,
                         confirmation:current.host_commands_enabled?'':hostConfirm})
              setHostConfirm('')
            },current.host_commands_enabled?'Comandos locais bloqueados.':'Execução local autorizada.')}>
            {current.host_commands_enabled ? 'Bloquear comandos locais' : 'Autorizar execução local'}
          </button>
        </section>
        <form className="mt-4 flex flex-wrap gap-2" onSubmit={e=>{
          e.preventDefault()
          action(async ()=>{
            await api('/organizations/'+selected+'/members','PUT',
                      {email:memberEmail.trim(),role:memberRole})
            setMemberEmail('')
          },'Membro atualizado.')
        }}>
          <input className={field + ' min-w-[170px] flex-1'} type="email" value={memberEmail}
            onChange={e=>setMemberEmail(e.target.value)} required placeholder="Conta já cadastrada"
            aria-label="Email do membro"/>
          <select className={field + ' max-w-[140px]'} value={memberRole}
            onChange={e=>setMemberRole(e.target.value)} aria-label="Papel do membro">
            <option value="operator">Operador</option><option value="analyst">Analista</option>
            <option value="admin">Administrador</option>
          </select>
          <button className={button} disabled={busy}>Adicionar / atualizar</button>
        </form>
        <form className="mt-4 space-y-2" onSubmit={e=>{
          e.preventDefault()
          action(()=>api('/organizations/'+selected+'/limits','PUT',{
            daily_run_limit:Number(daily),active_run_limit:Number(active),
            estimated_budget_usd:budget.trim()===''?null:Number(budget)
          }),'Limites atualizados.')
        }}>
          <p className="text-xs font-semibold">Limites desta organização</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <label className="text-[11px] text-muted">Tarefas por 24h
              <input className={field + ' mt-1'} type="number" min="1" max="100000" required
                value={daily} onChange={e=>setDaily(e.target.value)}/></label>
            <label className="text-[11px] text-muted">Tarefas ativas
              <input className={field + ' mt-1'} type="number" min="1" max="100000" required
                value={active} onChange={e=>setActive(e.target.value)}/></label>
            <label className="text-[11px] text-muted">Orçamento estimado US$ (opcional)
              <input className={field + ' mt-1'} type="number" min="0" step="0.01"
                value={budget} onChange={e=>setBudget(e.target.value)} placeholder="Sem limite"/></label>
          </div>
          <button className={button} disabled={busy}>Salvar limites</button>
          <p className="text-[10px] text-muted">Valores de API são estimados; isso não garante limite absoluto de cobrança.</p>
        </form>
      </>}
    </div>}
    {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
    {info && <p role="status" className="text-xs text-emerald-300">{info}</p>}
  </section>
}
