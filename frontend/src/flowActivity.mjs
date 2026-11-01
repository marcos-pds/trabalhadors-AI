import { activityLabel, compactActivityEvents } from './conversationActivity.mjs'

export function flowActivity(activity, agents = [], providers = [], stale = false) {
  const steps = activity.steps || []
  const log = compactActivityEvents(activity.events || [])
  const last = log.at(-1)
  const lastStepEvent = log.slice().reverse().find(item => item.step_id && steps.some(step => step.id === item.step_id))
  const current = steps.find(step => step.status === 'running') ||
    steps.find(step => ['awaiting_approval','awaiting_integration','paused_operator','paused_limit','failed'].includes(step.status)) ||
    steps.find(step => step.id === lastStepEvent?.step_id) || steps.find(step => step.status === 'queued') || steps.at(-1)
  const message = activity.agent_messages?.[0]
  const next = current && steps.find(step => step.status === 'queued' && (step.deps || []).includes(current.id))
  function person(id, name, step) {
    const agent = agents.find(item => item.id === id)
    const provider = providers.find(item => item.id === (step?.provider_id || agent?.provider_id))
    return { id, name: name || agent?.name || step?.name || 'Trabalhador', kind: provider?.kind,
      model: step?.model || '', working: !stale && activity.status === 'running' && step?.status === 'running' }
  }
  const sender = message
    ? person(message.sender_agent_id, message.sender_name, steps.find(step => step.agent_id === message.sender_agent_id))
    : person(current?.agent_id, null, current)
  const recipient = message
    ? person(message.recipient_agent_id, message.recipient_name, steps.find(step => step.agent_id === message.recipient_agent_id))
    : next ? person(next.agent_id, null, next) : null
  const labels = {running:'Em andamento',queued:'Na fila',awaiting_approval:'Aguardando aprovação',
    awaiting_integration:'Aguardando integração',paused_operator:'Pausada',paused_limit:'Pausada por limite',
    failed:'Execução com erro',cancelled:'Execução interrompida',completed:'Execução encerrada'}
  return { sender, recipient, current, message,
    label: stale ? 'Atualização indisponível' : labels[activity.status] || 'Estado não informado',
    moving: !stale && activity.status === 'running',
    done: steps.filter(step => step.status === 'completed').length, total: steps.length,
    text: message?.content || (last ? activityLabel(last) : 'Aguardando registros desta execução.'),
    logs: log.slice(-3).map(item => ({ seq:item.seq, text:activityLabel(item), failed:item.success === false || item.event === 'provider_error' })),
    verified: activity.status === 'completed' && activity.delivery_verified === true }
}
