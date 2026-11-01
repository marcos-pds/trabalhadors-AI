export default function WorkflowStages({ nodes, agents, onChange }) {
  function update(id, changes) {
    onChange(nodes.map(node => node.id === id ? { ...node, ...changes } : node))
  }
  function remove(id) {
    onChange(nodes.filter(node => node.id !== id).map(node => ({ ...node, deps: node.deps.filter(dep => dep !== id) })))
  }
  return nodes.length ? nodes.map((node, index) => {
    const required = node.required_actions?.includes('delegate_task') || false
    const canDelegate = node.kind === 'agent' && agents.find(agent => agent.id === node.agent_id)?.can_delegate === true
    return <div key={node.id} className="mb-3 rounded-xl border border-white/10 bg-card p-3 text-xs">
      <div className="flex items-center justify-between gap-3"><strong>{index + 1}. {node.name}</strong>
        <button type="button" onClick={() => remove(node.id)} className="text-muted hover:text-rose-300">Remover</button></div>
      {node.kind === 'agent' && <>
        <label className="mt-3 block text-muted">Instruções da etapa
          <textarea aria-label={`Instruções de ${node.name}`} value={node.instructions || ''} maxLength={2000} rows={3}
            onChange={event => update(node.id, { instructions: event.target.value })}
            className="mt-1 w-full rounded-lg border border-white/10 bg-panel p-2 text-copy"/></label>
        <label className="mt-3 flex items-center gap-2">
          <input type="checkbox" aria-label={`Exigir delegação de ${node.name}`} checked={required}
            disabled={!canDelegate && !required} onChange={event => update(node.id, { required_actions: event.target.checked ? ['delegate_task'] : [] })}/>
          Exigir criação de subtarefa antes de concluir
        </label>
        <p className="mt-1 text-[11px] leading-4 text-muted">{canDelegate || required
          ? 'Requer execução autônoma. O trabalhador deve registrar uma delegação real; uma promessa em texto não é suficiente. As permissões da pasta continuam sendo exigidas.'
          : 'Este papel não pode delegar. O revisor deve manter a independência do aceite.'}</p>
      </>}
    </div>
  }) : <p className="text-xs text-muted">Adicione uma etapa para começar.</p>
}
