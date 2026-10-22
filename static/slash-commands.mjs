/** Comandos locais seguros do Chat IA. Não são instruções para modelos de IA. */
export const SLASH_COMMANDS = Object.freeze([
  {name:'ajuda',description:'Ver os comandos disponíveis',icon:'?',aliases:['help']},
  {name:'testar',description:'Verificar imports React e sintaxe Python sem executar código',icon:'⊙',aliases:['teste']},
  {name:'revisar',description:'Revisar e aprovar propostas de arquivos sem sair do chat',icon:'▧',aliases:['revisao','revisão']},
  {name:'iniciar',description:'Iniciar React/Vite e FastAPI com autorização',icon:'▶',aliases:['start']},
  {name:'previa',description:'Visualizar a aplicação local em execução',icon:'◉',aliases:['prévia','preview']},
  {name:'parar',description:'Parar os servidores iniciados pela Central',icon:'■',aliases:['stop']},
  {name:'autorizar',description:'Autorizar execução local nesta conversa',icon:'✓',aliases:[]},
  {name:'revogar',description:'Revogar a autorização e encerrar servidores',icon:'⊘',aliases:[]},
  {name:'diagnostico',description:'Consultar o último erro de inicialização',icon:'⚠',aliases:['diagnóstico','logs']},
  {name:'status',description:'Verificar autorização e execução local',icon:'◎',aliases:[]},
  {name:'arquiteto',description:'Autorizar ou revogar a autonomia do Arquiteto IA',icon:'◇',aliases:[]},
  {name:'projeto',description:'Escolher o projeto da conversa',icon:'▤',aliases:[]},
  {name:'skills',description:'Acessar as Skills do projeto',icon:'✦',aliases:['skill']},
  {name:'nova',description:'Criar uma nova conversa',icon:'＋',aliases:['novo','new']},
  {name:'conversas',description:'Abrir o histórico de conversas',icon:'▣',aliases:['chats']},
  {name:'dashboard',description:'Abrir o painel geral',icon:'◫',aliases:['painel']},
  {name:'trabalhadores',description:'Gerenciar os trabalhadores IA',icon:'◈',aliases:['agentes']},
  {name:'fluxos',description:'Gerenciar os fluxos de trabalho',icon:'⌁',aliases:[]},
  {name:'projetos',description:'Gerenciar os projetos',icon:'▤',aliases:[]},
  {name:'arquivos',description:'Abrir os arquivos do projeto',icon:'▧',aliases:['files']},
  {name:'historico',description:'Consultar o histórico de execuções',icon:'◷',aliases:['histórico']},
  {name:'monitoramento',description:'Ver as métricas e execução dos provedores',icon:'◎',aliases:[]},
  {name:'provedores',description:'Gerenciar provedores e modelos de IA',icon:'⬡',aliases:['modelos']},
  {name:'configuracoes',description:'Abrir as configurações da Central',icon:'⚙',aliases:['configurações']},
  {name:'tema',description:'Alternar entre tema claro e escuro',icon:'◐',aliases:[]}
]);

export function normalizeSlash(value){
  return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR');
}

/** The first slash token is reserved for the host; never forward it to LLM. */
export function parseSlashCommand(value){
  const text=String(value||'').trim();
  if(!text.startsWith('/'))return {isSlash:false,command:null};
  const parts=text.split(/\s+/);
  const name=normalizeSlash(parts[0].slice(1));
  const found=SLASH_COMMANDS.find(c=>normalizeSlash(c.name)===name ||
    c.aliases.some(a=>normalizeSlash(a)===name));
  if(parts.length!==1)return {isSlash:true,command:null,reason:'Comandos não aceitam argumentos. Digite /ajuda para ver as opções.'};
  if(!found)return {isSlash:true,command:null,reason:'Comando desconhecido. Digite /ajuda para ver as opções.'};
  return {isSlash:true,command:found.name};
}

/** Menu only appears for a single slash token at the start of the composer. */
export function findSlashCommands(value){
  const text=String(value||'').trimStart();
  if(!/^\/[^\s]*$/.test(text))return [];
  const query=normalizeSlash(text.slice(1));
  return SLASH_COMMANDS.filter(c=>normalizeSlash(c.name).startsWith(query) ||
    c.aliases.some(a=>normalizeSlash(a).startsWith(query))).slice(0,30);
}
