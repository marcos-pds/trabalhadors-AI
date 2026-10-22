const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');

async function moduleUnderTest(){return import('../static/slash-commands.mjs')}

test('a normal request remains a normal AI request',async()=>{
 const {parseSlashCommand,findSlashCommands}=await moduleUnderTest();
 assert.equal(parseSlashCommand('Modernize o frontend')['isSlash'],false);
 assert.deepEqual(findSlashCommands('Crie uma loja'),[]);
});

test('slash menu searches canonical commands and aliases with or without accents',async()=>{
 const {findSlashCommands}=await moduleUnderTest();
 assert.equal(findSlashCommands('/')[0].name,'ajuda');
 assert.ok(findSlashCommands('/te').some(c=>c.name==='testar'));
 assert.equal(findSlashCommands('/PRÉ')[0].name,'previa');
 assert.equal(findSlashCommands('/diag')[0].name,'diagnostico');
 assert.deepEqual(findSlashCommands('/iniciar outro'),[]);
 assert.deepEqual(findSlashCommands('texto /testar'),[]);
});

test('only exact allowed slash commands resolve, including Portuguese aliases',async()=>{
 const {SLASH_COMMANDS,parseSlashCommand}=await moduleUnderTest();
 for(const item of SLASH_COMMANDS){
   assert.deepEqual(parseSlashCommand('/'+item.name),{isSlash:true,command:item.name});
   for(const alias of item.aliases)
     assert.equal(parseSlashCommand('/'+alias).command,item.name);
 }
 assert.equal(parseSlashCommand('/testar   ').command,'testar');
 assert.equal(parseSlashCommand('/executar-rm-rf').command,null);
 assert.equal(parseSlashCommand('/iniciar npm install').command,null);
 assert.equal(parseSlashCommand('/testar\nimporte os arquivos').command,null);
 assert.match(parseSlashCommand('/desconhecido').reason,/desconhecido/i);
});

test('composer handles slash commands before scheduling AI runs',()=>{
 const s=fs.readFileSync('static/app.js','utf8');
 const entry=s.slice(s.indexOf('async function sendMessage(){'),
                     s.indexOf('function disconnect(){'));
 assert.ok(entry.includes('parseSlashCommand(prompt)'));
 assert.ok(entry.indexOf('parseSlashCommand(prompt)')<entry.indexOf("api('/runs'"));
 assert.ok(entry.includes('if(local.isSlash)'));
 assert.ok(entry.includes('await executeSlashCommand(local.command)'));
 assert.ok(entry.includes('S.attached.length'));
 assert.ok(s.includes('aria-controls="chat-slash-menu"'));
 assert.ok(s.includes("event.key==='ArrowDown'"));
 assert.ok(s.includes("event.key==='ArrowUp'"));
 assert.ok(s.includes("event.key==='Escape'"));
 assert.ok(s.includes("event.key==='Tab'"));
 assert.ok(!s.includes('id="chat-runtime-tools"'));
 assert.ok(!s.includes('data-action="runtime-start"'));
});

test('slash dispatcher contains only known host actions and preserves consent flow',()=>{
 const s=fs.readFileSync('static/app.js','utf8');
 const code=s.slice(s.indexOf('async function executeSlashCommand(command){'));
 for(const name of ['testar','iniciar','previa','parar','autorizar','revogar',
                    'diagnostico','arquiteto','projeto','skills','ajuda','status'])
   assert.ok(code.includes("case '"+name+"'"));
 assert.ok(code.includes('await authorizeRuntime()'));
 assert.ok(code.includes('await startRuntime()'));
 assert.ok(code.includes("await handleAction('architect-delegation'"));
 assert.ok(code.includes("default:throw Error('Comando não reconhecido.')"));
});
