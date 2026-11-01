import { ReferenceProviderIcon } from './ReferenceIcons.jsx'
import { CommandIcon } from './LiquidGlassUI.jsx'
import { flowActivity } from './flowActivity.mjs'

export default function FlowActivity({ activity, agents, providers, stale, onOpenExecution }) {
  const view = flowActivity(activity, agents, providers, stale)
  function worker(person) {
    return <div className={'flow-person' + (person.working ? ' is-working' : '')}>
      <span className="flow-avatar" aria-hidden="true"><ReferenceProviderIcon kind={person.kind}
        className="h-9 w-9" state={person.working ? 'working' : 'idle'}/></span>
      <strong>{person.name}</strong>{person.model && <small>{person.model}</small>}
    </div>
  }
  return <section className={'flow-activity' + (view.moving ? ' is-running' : '')}
    aria-label="Fluxo dos trabalhadores no chat" data-status={activity.status} data-stale={stale || undefined}>
    <header className="flow-heading"><span className="flow-state"><i aria-hidden="true"/>{view.label}</span>
      <span>{view.done}/{view.total} etapas concluídas</span></header>
    {view.current && <p className="flow-stage">Etapa: <strong>{view.current.name}</strong></p>}
    <div className="flow-agents">
      {worker(view.sender)}
      {view.recipient && <><div className="flow-connection" aria-hidden="true"><span/><CommandIcon name="send"/></div>{worker(view.recipient)}</>}
    </div>
    {view.recipient && <p className="flow-relation">{view.message ? 'Última mensagem registrada entre trabalhadores' : 'Próxima etapa dependente · aguardando sua vez'}</p>}
    <div className="flow-panels"><div className="flow-speech"><CommandIcon name="message"/>
      <div><small>{view.message ? 'Mensagem registrada' : 'Atividade registrada'}</small><p>{view.text}</p></div></div>
      <div className="flow-terminal" role="log" aria-label="Últimos registros da execução" aria-live="off">
        <header><CommandIcon name="activity"/><span>Registro da execução</span></header>
        {view.logs.length ? view.logs.map(item => <p key={item.seq} className={item.failed ? 'is-error' : ''}><b aria-hidden="true">›</b>{item.text}</p>) : <p>Aguardando registros...</p>}
        {view.moving && <span className="flow-cursor" aria-hidden="true"/>}
      </div>
    </div>
    <footer>{view.verified && <span>Entrega verificada</span>}
      <button type="button" onClick={onOpenExecution}>Ver execução e prévia <span aria-hidden="true">↗</span></button></footer>
  </section>
}
