const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');

const app=fs.readFileSync('static/app.js','utf8');
const css=fs.readFileSync('static/style.css','utf8');

test('chat is initial page and visual workspace is only one chat column',()=>{
 assert.ok(app.includes("page:'chat'"));
 const start=app.indexOf('function chat(){');
 const end=app.indexOf('/* Fast project-scoped review inbox',start);
 assert.ok(start>=0 && end>start);
 const chat=app.slice(start,end);
 assert.match(chat,/class="chat-center"/);
 assert.match(chat,/id="chat-transcript"/);
 assert.match(chat,/id="chat-slash-menu"/);
 assert.match(chat,/aria-controls="chat-slash-menu"/);
 assert.ok(!chat.includes('chat-left'));
 assert.ok(!chat.includes('chat-right'));
 assert.ok(!chat.includes('chatContextBar()'));
 assert.ok(!chat.includes('id="chat-pending-banner"'));
});

test('hamburger menu contains all existing navigation and project tools',()=>{
 const shell=app.slice(app.indexOf('function shell(){'),app.indexOf('function nav(page)'));
 for(const tag of ['id="workspace-menu"','id="menu-toggle"','id="convos"',
                   'id="chat-project"','id="chat-steps"']){
  if(tag==='id="chat-project"')continue; // provided by chatContextBar()
  assert.ok(shell.includes(tag),tag);
 }
 assert.ok(shell.includes('chatContextBar()'));
 assert.ok(shell.includes('id="chat-pending-banner"'));
 for(const route of ['chat','dashboard','agents','workflows','projects','workspace',
                     'skills','history','monitoring','providers','settings']){
  assert.ok(shell.includes("nav('"+route+"')"),route);
 }
 assert.ok(shell.includes('data-action="close-menu"'));
 assert.match(css,/\.shell\.menu-open \.sidebar/);
 assert.match(css,/\.chat-root \.chat-layout\{display:block/);
});

test('slash commands cover running and navigation without arbitrary execution',async()=>{
 const {SLASH_COMMANDS,normalizeSlash,parseSlashCommand,findSlashCommands}=
   await import('../static/slash-commands.mjs');
 const required=['ajuda','testar','revisar','iniciar','previa','parar','autorizar',
                 'revogar','diagnostico','status','arquiteto','projeto','skills',
                 'nova','conversas','dashboard','trabalhadores','fluxos',
                 'projetos','arquivos','historico','monitoramento','provedores',
                 'configuracoes','tema'];
 assert.deepEqual(SLASH_COMMANDS.map(x=>x.name),required);
 const names=new Map();
 for(const item of SLASH_COMMANDS){
  for(const alias of [item.name,...item.aliases]){
   const normal=normalizeSlash(alias);
   if(names.has(normal))assert.equal(names.get(normal),item.name,
     'Alias '+normal+' não pode apontar para comandos diferentes');
   names.set(normal,item.name);
   assert.equal(parseSlashCommand('/'+alias).command,item.name);
  }
 }
 assert.ok(findSlashCommands('/').length===SLASH_COMMANDS.length);
 assert.equal(parseSlashCommand('/iniciar npm install').command,null);
 assert.equal(parseSlashCommand('/autorizar qualquer coisa').command,null);
 assert.equal(parseSlashCommand('/exec').command,null);
});

test('slash dispatcher routes safely and opens drawer for project and skills',()=>{
 const dispatcher=app.slice(app.indexOf('async function executeSlashCommand(command){'));
 assert.ok(dispatcher.includes("case 'projeto':{\n   setMenuOpen(true)"));
 assert.ok(dispatcher.includes("case 'skills':{\n   setMenuOpen(true)"));
 for(const [command,page] of [['dashboard','dashboard'],['trabalhadores','agents'],
   ['fluxos','workflows'],['projetos','projects'],['arquivos','workspace'],
   ['historico','history'],['monitoramento','monitoring'],
   ['provedores','providers'],['configuracoes','settings']]){
  assert.ok(dispatcher.includes("case '"+command+"':goto('"+page+"');return;"));
 }
 assert.ok(dispatcher.includes("case 'tema':await handleAction('theme',null,null);return;"));
 assert.ok(dispatcher.includes("case 'nova':await handleAction('new-chat',null,null);return;"));
 assert.ok(dispatcher.includes("default:throw Error('Comando não reconhecido.')"));
 assert.ok(app.includes('if(action===\'toggle-menu\')'));
 assert.ok(app.includes('if(action===\'close-menu\')'));
 assert.ok(app.includes("if(e.key==='Escape'&&S.menuOpen)"));
 assert.ok(app.includes('const draft=$(\'#chat-input\')?.value||\'\''));
 assert.ok(app.includes('   await shell();'));
});
