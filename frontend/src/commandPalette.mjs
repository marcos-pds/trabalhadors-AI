// The chat is the primary navigation surface. These commands route to REAL
// Central screens/actions; this list never fabricates agent/model activity.
export const chatCommands = Object.freeze([
  { command: '/novo', label: 'Nova conversa', description: 'Iniciar um chat limpo', icon: 'plus', group: 'Chat' },
  { command: '/chat', label: 'Voltar ao chat', description: 'Tela principal da Central', icon: 'message', group: 'Chat' },
  { command: '/ajuda', label: 'Ajuda e comandos', description: 'Ver comandos disponíveis', icon: 'sparkles', group: 'Chat' },
  { command: '/previa', label: 'Prévia e execução', description: 'Abrir o painel real de execução', icon: 'play', group: 'Chat' },
  { command: '/memoria', label: 'Memória do projeto', description: 'Consultar contexto e conversas', icon: 'brain', group: 'Chat' },
  { command: '/computador', label: 'Acesso ao computador', description: 'Permissões de pasta e operações', icon: 'monitor', group: 'Chat' },
  { command: '/automatico', label: 'Modo automático', description: 'Usar a seleção automática de trabalhadores', icon: 'zap', group: 'Agentes' },
  { command: '/equipe', label: 'Modo equipe', description: 'Distribuir tarefas para a equipe', icon: 'users', group: 'Agentes' },
  { command: '/agentes', label: 'Trabalhadores', description: 'Gerenciar agentes e especialidades', icon: 'users', group: 'Agentes' },
  { command: '/provedores', label: 'Modelos e provedores', description: 'Conexões e seleção de modelos', icon: 'sparkles', group: 'Agentes' },
  { command: '/fluxos', label: 'Fluxos de trabalho', description: 'Organizar execuções multiagente', icon: 'git', group: 'Agentes' },
  { command: '/painel', label: 'Visão geral', description: 'Abrir painel de operações', icon: 'layout', group: 'Workspace' },
  { command: '/projetos', label: 'Projetos', description: 'Conversas e workspaces por projeto', icon: 'folder', group: 'Workspace' },
  { command: '/historico', label: 'Histórico', description: 'Retomar uma execução anterior', icon: 'clock', group: 'Workspace' },
  { command: '/monitoramento', label: 'Monitoramento', description: 'Saúde e métricas reais', icon: 'activity', group: 'Workspace' },
  { command: '/tokens', label: 'Uso de tokens', description: 'Consultar consumo real', icon: 'chart', group: 'Workspace' },
  { command: '/skills', label: 'Skills', description: 'Listar ou ativar skills com escopo', icon: 'puzzle', group: 'Integrações' },
  { command: '/plugins', label: 'Plugins e MCP', description: 'Listar recursos e conexões', icon: 'puzzle', group: 'Integrações' },
  { command: '/integracoes', label: 'Gerenciar integrações', description: 'Skills, VSIX e servidores MCP', icon: 'puzzle', group: 'Integrações' },
  { command: '/github', label: 'GitHub', description: 'Conexão de repositórios e revisões', icon: 'git', group: 'Integrações' },
  { command: '/configuracoes', label: 'Configurações', description: 'Conta e preferências', icon: 'settings', group: 'Workspace' },
  { command: '/menu', label: 'Navegação alternativa', description: 'Abrir menu lateral completo', icon: 'menu', group: 'Workspace' },
  { command: '/aprovar', label: 'Aprovar etapa', description: 'Confirmação explícita de etapa pendente', icon: 'check', group: 'Execução' },
  { command: '/rejeitar', label: 'Rejeitar etapa', description: 'Negar uma etapa pendente', icon: 'x', group: 'Execução' },
])

export function matchingChatCommands(value) {
  if (typeof value !== 'string' || !value.startsWith('/')) return []
  const term = value.slice(1).trim().toLocaleLowerCase('pt-BR')
  // Resource commands with arguments (/skill ativar, /plugin ativar) continue
  // through the original guarded backend handler, not the palette.
  if (/\s/.test(term)) return []
  return chatCommands.filter(item => item.command.slice(1).includes(term) ||
    item.label.toLocaleLowerCase('pt-BR').includes(term))
}
