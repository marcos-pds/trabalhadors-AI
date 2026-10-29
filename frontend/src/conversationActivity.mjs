export function activityLabel(item) {
  const action = {read:'Leitura', list:'Arquivos consultados', write:'Arquivo criado', replace:'Arquivo alterado', command:'Comando', browser_tool:'Navegador', reference_search:'Pesquisa'}[item.action] || 'Ferramenta'
  if (item.event === 'workspace_action_result') return `${item.success === false ? 'Falha' : action}${item.path || item.command ? ': ' + (item.path || item.command) : item.description ? ' · ' + item.description : ''}`
  if (item.event === 'workspace_action_requested') return item.description || 'Executando ferramenta'
  if (item.event === 'workspace_validation') return item.success === false ? 'Validação falhou' : 'Validação concluída'
  if (item.event === 'skill_context_selected') return 'Skills: ' + [...new Set((item.selected_skills || []).map(s => s.name))].join(', ')
  if (item.event === 'model_selected') return 'Modelo: ' + (item.model || 'selecionado')
  if (item.event === 'provider_error') return 'Erro no provedor'
  if (item.event === 'failover') return 'Tentando outro provedor'
  if (item.event === 'workspace_approval_required') return 'Aguardando aprovação'
  if (item.event === 'workspace_feedback_applied') return 'Ajuste recebido pelo trabalhador'
  if (item.event === 'worker_checkpoint_restored') return 'Trabalho retomado'
  if (item.event === 'worker_budget_warning') return 'Limite de ciclos próximo'
  if (item.event === 'run_paused_limit') return 'Pausado · progresso salvo'
  if (item.event === 'run_failed') return 'Execução com erro'
  if (item.event === 'run_completed') return 'Execução concluída'
  if (item.event === 'step_status') return 'Etapa: ' + ({running:'em andamento',completed:'concluída',failed:'com erro',queued:'na fila',paused_limit:'pausada'}[item.status] || item.status || 'atualizada')
  return item.stage || 'Trabalhador em atividade'
}

export function mergeActivityEvents(previous, incoming) {
  return [...new Map([...previous, ...incoming].map(item => [item.seq, item])).values()]
    .sort((a,b) => a.seq - b.seq).slice(-200)
}

export function compactActivityEvents(events) {
  const visible = new Set(['model_selected','workspace_action_result','workspace_validation',
    'provider_error','failover','workspace_approval_required','workspace_feedback_applied',
    'worker_checkpoint_restored','worker_budget_warning','run_paused_limit','run_failed',
    'run_completed','step_status','skill_context_selected','workspace_action_requested'])
  const skills = new Set()
  return events.filter((item, index) => {
    if (!visible.has(item.event)) return false
    if (item.event === 'skill_context_selected') {
      const names = [...new Set((item.selected_skills || []).map(s => s.name))].sort().join(',')
      if (!names || skills.has(names)) return false
      skills.add(names)
    }
    if (item.event === 'workspace_action_requested' && events.slice(index + 1).some(next =>
      next.event === 'workspace_action_result' && next.step_id === item.step_id &&
      next.action === item.action && next.path === item.path && next.description === item.description)) return false
    return true
  })
}
