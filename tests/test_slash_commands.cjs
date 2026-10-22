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


test('QA repair picks only enabled workers required by deterministic error paths',async()=>{
 const {chooseRepairWorkers}=await import('../static/chat-approvals.mjs');
 const agents=[
   {id:'a',name:'Frontend IA',specialty:'UI',resolved_role:'frontend',enabled:1},
   {id:'b',name:'Backend IA',specialty:'backend',resolved_role:'backend',enabled:1},
   {id:'c',name:'Testador IA',specialty:'testing',resolved_role:'testing',enabled:1}
 ];
 const front=['frontend/src/App.tsx: importação LoadingSpinner não existe em frontend/src/components/LoadingSpinner.tsx'];
 assert.deepEqual(chooseRepairWorkers(front,agents).map(a=>a.id),['a']);
 assert.deepEqual(chooseRepairWorkers(['backend/main.py:1: erro de sintaxe Python'],agents).map(a=>a.id),['b']);
 assert.deepEqual(chooseRepairWorkers([...front,'backend/main.py:1: erro de sintaxe Python'],agents).map(a=>a.id),['a','b']);
 assert.deepEqual(chooseRepairWorkers(['alerta genérico'],agents),[]);
 assert.deepEqual(chooseRepairWorkers(front,agents.map(a=>({...a,enabled:0}))),[]);
});

test('repair task limits diagnostics and requests safe reviewable central-files instead of running commands',async()=>{
 const {repairPrompt}=await import('../static/chat-approvals.mjs');
 const prompt=repairPrompt(['frontend/src/App.tsx: importação LoadingSpinner não existe'],[{id:'f'}]);
 assert.match(prompt,/central-files/);
 assert.match(prompt,/sem executar comandos/);
 assert.match(prompt,/arquivos COMPLETOS/i);
 assert.match(prompt,/fluxo de propostas e aprovação/i);
 assert.match(prompt,/LoadingSpinner/);
 assert.equal(repairPrompt(['frontend/a.tsx: erro'],[]),null);
 const payload=Array(40).fill('frontend/a.tsx: problema '+ 'X'.repeat(700));
 assert.ok(repairPrompt(payload,[{id:'f'}]).length<7000);
});

test('all permission questions live inside chat and cannot run before explicit click',()=>{
 const source=fs.readFileSync('static/app.js','utf8');
 assert.ok(source.includes('function askChatPermission('));
 assert.ok(source.includes('data-action="chat-consent-yes"'));
 assert.ok(source.includes('data-action="chat-consent-no"'));
 assert.ok(source.includes('function decideChatPermission(id,allowed)'));
 assert.ok(source.includes('await offerDependencyInstall(report,cid)'));
 assert.ok(source.includes('await proposeQaRepair(codeProblems)'));
 assert.ok(source.includes('await askChatPermission({'));
 assert.ok(source.includes("title:'Deseja que '+label+' execute a correção?'"));
 assert.ok(source.includes('if(!accepted)return'));
 assert.ok(source.includes("api('/conversations/'+encodeURIComponent(sourceConversation)+'/quality')"));
 assert.ok(source.includes("api('/runs','POST'"));
 assert.ok(source.includes("if(JSON.stringify(actual)!==JSON.stringify(issueSnapshot))"));
 const sender=source.slice(source.indexOf('async function sendMessage(){'),source.indexOf('function disconnect(){'));
 assert.ok(!sender.includes('window.confirm('));
 assert.ok(source.includes('cancelChatDecisions()'));
});


test('human workflow steps require inline consent and stale cards cannot decide stages',()=>{
 const source=fs.readFileSync('static/app.js','utf8');
 assert.ok(source.includes("if(msg.event==='approval_requested')"));
 assert.ok(source.includes('void offerStepApproval(d.step_id)'));
 assert.ok(source.includes('async function offerStepApproval(stepId)'));
 assert.ok(source.includes('if(approved===null || S.currentRun!==runId'));
 assert.ok(source.includes("entry.resolve(null);"));
 assert.ok(source.includes("data-action=\"chat-consent-yes\""));
 assert.ok(source.includes("data-action=\"chat-consent-no\""));
 assert.ok(!source.includes('if(!confirm(\'Conceder ao Arquiteto'));
 assert.ok(!source.includes('if(enabled&&!confirm(\'Autorizar a Central'));
 assert.ok(source.includes('Deseja abrir uma nova conversa para trocar de projeto?'));
});


test('chat review supports /revisar and always surfaces pending project proposals',async()=>{
 const {parseSlashCommand,findSlashCommands}=await moduleUnderTest();
 assert.equal(parseSlashCommand('/revisar').command,'revisar');
 assert.equal(parseSlashCommand('/revisão').command,'revisar');
 assert.ok(findSlashCommands('/rev').some(c=>c.name==='revisar'));
 const js=fs.readFileSync('static/app.js','utf8');
 assert.ok(js.includes('id="chat-pending-banner"'));
 assert.ok(js.includes('async function loadChatPendingReviews()'));
 assert.ok(js.includes("api('/projects/'+encodeURIComponent(pid)+'/workspace/pending')"));
 assert.ok(js.includes("data-action=\"chat-review-open\""));
 assert.ok(js.includes("case 'revisar':await loadChatPendingReviews();await openChatProposalReview();return;"));
 assert.ok(js.includes("if(msg.event==='workspace_proposals')"));
 assert.ok(js.includes("await loadChatPendingReviews();"));
 assert.ok(js.includes('async function openChatProposalReview(id)'));
 assert.ok(js.includes('renderChatProposalReview()'));
 assert.ok(js.includes("async function decideChatProposal(approved)"));
});

test('the inline reviewer refuses stale or incomplete diff and requires APLICAR',()=>{
 const s=fs.readFileSync('static/app.js','utf8');
 const begin=s.indexOf('async function decideChatProposal(approved){');
 const part=s.slice(begin,s.indexOf('async function enterChat(){',begin));
 assert.ok(part.includes("if(typed!=='APLICAR')"));
 assert.ok(part.includes("JSON.stringify(latest.files)!==JSON.stringify(preview.files)"));
 assert.ok(part.includes("f.stale||f.diff_truncated"));
 assert.ok(part.includes("if(S.currentRun)"));
 assert.ok(part.includes("confirmation:approved?'APLICAR':''"));
 assert.ok(part.includes("await loadChatPendingReviews()"));
 assert.ok(part.includes("if(S.chatPendingReviews.length)await openChatProposalReview()"));
 assert.ok(s.includes('data-action="chat-review-approve"'));
 assert.ok(s.includes('data-action="chat-review-reject"'));
 assert.ok(s.includes("chatProposalDiffHtml(file.diff)"));
 assert.ok(s.includes("esc(line)"));
 assert.ok(s.includes("preview.files.length>1"));
 assert.ok(s.includes("Esta proposta contém"));
 assert.ok(s.includes("S.page!=='chat'||chatProjectId()!==pid"));
});


test('pasted Vite missing module log triggers safe local QA, not a shell or arbitrary agent run',()=>{
 const source=fs.readFileSync('static/app.js','utf8');
 assert.ok(source.includes('function isLocalBuildDiagnostic(message)'));
 assert.ok(source.includes("if(chatProjectId()&&isLocalBuildDiagnostic(prompt))"));
 assert.ok(source.includes("appendEvent('⊙ Erro de compilação reconhecido."));
 assert.ok(source.includes('await runQualityChecks();return;'));
 assert.ok(source.includes("title:'Deseja instalar '+candidate+' para corrigir a Loja Virtual?'"));
 assert.ok(source.includes("await askChatPermission({"));
 assert.ok(source.includes("'/dependencies/install','POST',{package:candidate}"));
 assert.ok(source.includes("if(!(fresh.missing_packages||[]).includes(candidate))"));
 assert.ok(source.includes("await runQualityChecks()"));
 assert.ok(source.includes("const DIRECT_NPM_ALLOWLIST=new Set(["));
 assert.ok(source.includes("'lucide-react'"));
});
