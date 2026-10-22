const S={me:null,page:'dashboard',theme:localStorage.getItem('central-theme')||'dark',agents:[],providers:[],projects:[],conversations:[],workflows:[],runs:[],currentConvo:null,currentRun:null,source:null,runSteps:[],streams:{},lastSeq:0,mode:'auto',selectedAgent:'',selectedWorkflow:'',attached:[],loginMode:'register',workspaceProject:null,workspaceInfo:null,workspaceRunProject:null,skillProject:null,skills:[],packageAudit:[],delegation:null,chatSkills:[],chatSkillsLoading:false};
const $=sel=>document.querySelector(sel);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labelStatus=s=>({completed:'Concluído',running:'Executando',failed:'Falhou',cancelled:'Cancelado',queued:'Na fila',awaiting_approval:'Aguardando aprovação',disabled:'Desativado'}[s]||s);
const fmtDate=s=>s?new Date(s).toLocaleString('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'—';
const icon={dashboard:'◫',chat:'▣',agents:'◈',workflows:'⌁',projects:'▤',workspace:'▧',skills:'✦',history:'◷',monitoring:'⌁',providers:'⬡',settings:'⚙'};
const pages={dashboard:'Dashboard',chat:'Chat IA',agents:'Trabalhadores',workflows:'Fluxos',projects:'Projetos',workspace:'Arquivos',skills:'Skills UX/UI',history:'Histórico',monitoring:'Monitoramento',providers:'Provedores',settings:'Configurações'};
let toastTimer=0;
function toast(t){const el=document.createElement('div');el.className='toast';el.textContent=t;let root=$('.toasts');if(!root){root=document.createElement('div');root.className='toasts';document.body.append(root)}root.append(el);setTimeout(()=>el.remove(),5200)}
async function api(path,method='GET',data,opts={}){
 const headers={'X-Central-Request':'1',...(opts.headers||{})};
 let body;
 if(data instanceof FormData){body=data}else if(data!==undefined){headers['Content-Type']='application/json';body=JSON.stringify(data)}
 const res=await fetch('/api'+path,{method,headers,body,credentials:'same-origin'});
 let out;try{out=await res.json()}catch{out={detail:'Resposta inválida do servidor.'}}
 if(!res.ok)throw new Error(typeof out.detail==='string'?out.detail:JSON.stringify(out.detail||'Erro desconhecido'));
 return out;
}
function markdown(raw){
 const chunks=esc(raw).split(/```/g);let html='';
 chunks.forEach((chunk,i)=>{
   if(i%2){const x=chunk.replace(/^[a-zA-Z0-9+#-]+\n/,'');html+=`<pre><button class="btn btn-sm btn-quiet copy-code" style="float:right">Copiar</button><code>${x}</code></pre>`;return}
   const lines=chunk.split('\n');let acc=[];
   for(const line of lines){
     const fmt=t=>t.replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
     if(line.startsWith('### ')){acc.push('<h3>'+fmt(line.slice(4))+'</h3>')}
     else if(line.startsWith('## ')){acc.push('<h3>'+fmt(line.slice(3))+'</h3>')}
     else if(/^[-*] /.test(line)){acc.push('<p>• '+fmt(line.slice(2))+'</p>')}
     else if(line.trim()){acc.push('<p>'+fmt(line)+'</p>')}
   }
   html+=acc.join('');
 });return html;
}
function applyTheme(){document.body.classList.toggle('light',S.theme==='light')}
function authView(){
 $('#app').innerHTML=`<div class="auth-page"><div class="auth-card"><div class="brand-mark">✳</div><div class="eyebrow">Sua equipe de IA, reunida</div><h1>${S.loginMode==='register'?'Crie sua central.':'Bem-vindo de volta.'}</h1><p>Uma plataforma para trabalhar com múltiplos agentes e modelos em um só lugar.</p><form id="auth-form"><div class="form-row"><label class="form-label">E-mail</label><input class="field" type="email" name="email" autocomplete="email" required placeholder="voce@empresa.com" /></div><div class="form-row"><label class="form-label">Senha</label><input class="field" type="password" name="password" autocomplete="${S.loginMode==='register'?'new-password':'current-password'}" minlength="10" required placeholder="No mínimo 10 caracteres" /></div><div id="auth-error" class="form-error"></div><button class="btn btn-primary" type="submit">${S.loginMode==='register'?'Criar conta grátis':'Entrar na central'} →</button></form><div class="switch-auth">${S.loginMode==='register'?'Já possui conta?':'Ainda não possui conta?'} <button id="auth-switch">${S.loginMode==='register'?'Fazer login':'Criar conta'}</button></div></div></div>`;
 $('#auth-switch').onclick=()=>{S.loginMode=S.loginMode==='register'?'login':'register';authView()};
 $('#auth-form').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);const b=e.target.querySelector('button[type=submit]');b.disabled=true;try{S.me=await api('/'+S.loginMode,'POST',{email:f.get('email'),password:f.get('password')});await loadAll();shell()}catch(ex){$('#auth-error').textContent=ex.message}finally{b.disabled=false}};
}
function shell(){
 applyTheme();
 $('#app').innerHTML=`<div class="shell"><aside class="sidebar"><div class="brand"><div class="brand-mark">✳</div><div class="brand-label"><strong>Central IA</strong><small>WORKFORCE INTELLIGENCE</small></div></div><div class="side-label">PRINCIPAL</div>${nav('dashboard')}${nav('chat')}${nav('agents')}${nav('workflows')}${nav('projects')}${nav('workspace')}${nav('skills')}<div class="side-label">GESTÃO</div>${nav('history')}${nav('monitoring')}${nav('providers')}${nav('settings')}<div class="side-end"><div class="server-state"><span class="dot ${S.providers.length?'':'warning'}"></span>${S.providers.length?S.providers.filter(p=>p.enabled).length+' provedor(es) ativados':'Nenhum provedor conectado'}</div><div class="account"><span class="account-initial">${esc(S.me.email.charAt(0).toUpperCase())}</span><div class="email">${esc(S.me.email.split('@')[0])}<small>Minha conta</small></div><button class="icon-btn" data-action="logout" title="Sair">⎋</button></div></div></aside><main class="main"><header class="topbar"><div class="crumb">Workspace <span style="padding:0 9px">/</span> <strong id="top-title">${pages[S.page]}</strong></div><div class="top-actions"><span class="day">${new Date().toLocaleDateString('pt-BR',{weekday:'short',day:'numeric',month:'short'})}</span><span class="pill"><span class="dot"></span>Sistema online</span><button class="icon-btn" data-action="theme" title="Alternar tema">◐</button></div></header><div id="content" class="${S.page==='chat'?'chat-root':'container'}"></div></main></div>`;
 renderPage();
}
function nav(page){return `<button class="nav-link ${S.page===page?'active':''}" data-page="${page}"><span class="glyph">${icon[page]}</span><span>${pages[page]}</span>${page==='chat'?'<em>IA</em>':''}</button>`}
function goto(page){if(S.page==='chat'&&page!=='chat')disconnect();S.page=page;shell()}
async function loadAll(){
 const entries=await Promise.allSettled([api('/agents'),api('/providers'),api('/projects'),api('/conversations'),api('/workflows'),api('/runs')]);
 ['agents','providers','projects','conversations','workflows','runs'].forEach((key,i)=>{if(entries[i].status==='fulfilled')S[key]=entries[i].value});
}
function heading(kicker,title,description,button=''){return `<div class="page-head"><div><div class="eyebrow">${kicker}</div><h1 class="page-title">${title}</h1><p class="page-desc">${description}</p></div>${button}</div>`}
function stat(name,value,icon,foot){return `<div class="stat"><span class="stat-icon">${icon}</span><p class="stat-label">${name}</p><div class="stat-value">${value}</div><div class="stat-foot">${foot}</div></div>`}
async function renderPage(){let html='';const ct=$('#content');ct.className=S.page==='chat'?'chat-root':'container';
 if(S.page==='dashboard'||S.page==='monitoring'){let d;try{d=await api('/dashboard')}catch(ex){toast(ex.message);return}html=dashboard(d,S.page==='monitoring')}
 if(S.page==='providers')html=providers();
 if(S.page==='agents')html=agents();
 if(S.page==='workflows')html=workflows();
 if(S.page==='projects')html=projects();
 if(S.page==='workspace'){await refreshWorkspace();html=workspaceView()}
 if(S.page==='skills'){await refreshSkills();html=skillsView()}
 if(S.page==='history')html=history();
 if(S.page==='settings')html=settings();
 if(S.page==='chat')html=chat();
 ct.innerHTML=html;
 if(S.page==='chat')await enterChat();
}
function dashboard(d,monitoring=false){
 return `${heading(monitoring?'OBSERVABILIDADE':'VISÃO GERAL',monitoring?'Monitoramento em tempo real':'Seu centro de operações',monitoring?'Dados reais coletados durante suas execuções.':'Gerencie seus trabalhadores, acompanhe tarefas e conecte suas melhores IAs.',`<button class="btn btn-primary" data-page="chat">✦ Nova tarefa <span>→</span></button>`)}
 ${!monitoring?`<div class="hero"><div class="hero-kicker">✧ SEU WORKSPACE, MAIS INTELIGENTE</div><h2>Uma equipe inteira de IA.<br>Um só lugar para criar.</h2><p>Distribua tarefas entre especialistas, execute em paralelo e alterne modelos automaticamente quando necessário.</p><button class="btn btn-primary btn-sm" data-page="chat">Começar agora →</button></div>`:''}
 ${!S.providers.some(p=>p.enabled)?'<div class="hint">⚠ Nenhum modelo conectado. Os trabalhadores estão preparados, mas precisam de uma API configurada para executar tarefas. <button class="btn btn-sm" data-page="providers">Configurar provedor →</button></div>':''}
 <div class="stats">${stat('Trabalhadores disponíveis',d.agents,'◈','Agentes ativos')}${stat('Tarefas concluídas',d.completed,'✓','Execuções finalizadas')}${stat('Em execução',d.running+d.queued,'⌁',d.queued+' na fila')}${stat('Recuperações acionadas',d.failovers,'↻','Eventos de failover')}</div>
 <div class="grid2"><section class="panel"><div class="panel-head"><h3>Atividade recente</h3><button class="btn btn-sm btn-quiet" data-page="history">Ver histórico →</button></div><div class="panel-body">${d.recent.length?`<table class="activity">${d.recent.map(r=>`<tr><td><strong>${esc(r.prompt)}</strong><small style="color:var(--muted)">${fmtDate(r.created_at)}</small></td><td><span class="status ${r.status}">${labelStatus(r.status)}</span></td></tr>`).join('')}</table>`:'<div class="empty"><div class="empty-icon">◷</div><strong>Nenhuma execução ainda</strong>Suas tarefas aparecerão aqui.</div>'}</div></section><section class="panel"><div class="panel-head"><h3>Provedores conectados</h3><button class="btn btn-sm btn-quiet" data-page="providers">Gerenciar →</button></div><div class="panel-body">${S.providers.length?S.providers.map(p=>`<div class="provider-short"><div class="provider-mark">⬡</div><div style="flex:1"><strong>${esc(p.name)}</strong><small>${esc(p.model)}</small></div><span class="status ${p.enabled?'completed':'failed'}">${p.enabled?'Ativo':'Inativo'}</span></div>`).join(''):'<div class="empty"><div class="empty-icon">⬡</div><strong>Conecte sua primeira IA</strong>OpenAI, Claude, Gemini, DeepSeek e mais.</div>'}${monitoring?`<p style="color:var(--muted);font-size:11px">Custo estimado de requisições com preço configurado: US$ ${d.estimated_cost.toFixed(5)}. Não equivale ao faturamento oficial.</p>`:''}</div></section></div>${monitoring?`<section class="health-section"><div class="panel-head"><h3>Saúde e disponibilidade das conexões</h3><button class="btn btn-sm" data-action="refresh">↻ Atualizar</button></div>${healthTable()}</section>`:''}`;
}
function healthState(p){
 if(!p.enabled)return ['Pausado','failed'];
 const h=p.health||{};
 const states={healthy:['Saudável','completed'],degraded:['Instável','running'],suspended:['Suspenso','failed'],recovering:['Em recuperação','running'],untested:['Sem medições','']};
 return states[h.state]||['Sem medições',''];
}
function healthNote(p){
 const h=p.health||{};
 const rate=h.success_rate==null?'—':h.success_rate.toFixed(1)+'%';
 const latency=h.avg_latency_ms==null?'—':h.avg_latency_ms+' ms';
 return `${rate} sucesso (últimas ${h.samples||0} chamadas) · ${latency}`;
}
function healthTable(){
 if(!S.providers.length)return '<div class="empty">Cadastre um provedor para registrar medições reais.</div>';
 return `<div class="table-wrap"><table class="data-table provider-health-table"><thead><tr><th>Conexão / Modelo</th><th>Estado</th><th>Sucesso</th><th>Latência</th><th>Falhas seguidas</th><th class="right">Detalhes</th></tr></thead><tbody>${S.providers.map(p=>{
   const h=p.health||{}, status=healthState(p);const pct=h.success_rate==null?'—':h.success_rate.toFixed(1)+'%';
   const wait=h.state==='suspended'?`<small>Volta em ~${h.remaining_seconds}s</small>`:h.state==='recovering'?'<small>Aguardando teste na próxima tarefa</small>':'';
   return `<tr><td><strong>${esc(p.name)}</strong><small>${esc(p.model)}</small></td><td><span class="status ${status[1]}">${status[0]}</span>${wait}</td><td>${pct}<small>${h.samples||0} chamadas recentes</small></td><td>${h.avg_latency_ms==null?'—':h.avg_latency_ms+' ms'}</td><td>${h.consecutive_failures||0}${h.last_http_status?`<small>Último HTTP ${h.last_http_status}</small>`:''}</td><td class="right"><button class="btn btn-sm" data-action="health-history" data-id="${p.id}">Histórico</button></td></tr>`;
  }).join('')}</tbody></table></div><p class="page-desc health-footnote">Taxa e tempo médio calculados a partir das 20 últimas chamadas reais de cada modelo desde esta atualização. Sem testes artificiais de disponibilidade.</p>`;
}
async function openHealthHistory(pid){
 const provider=S.providers.find(p=>p.id===pid);if(!provider)return;
 try{
  const entries=await api(`/providers/${pid}/attempts`);
  const content=`<div class="table-wrap"><table class="data-table"><thead><tr><th>Data</th><th>Resultado</th><th>Código / Erro</th><th>Latência</th></tr></thead><tbody>${entries.map(a=>`<tr><td>${esc(fmtDate(a.created_at))}</td><td>${a.success?'<span class="status completed">Sucesso</span>':'<span class="status failed">Falhou</span>'}</td><td>${esc(a.http_status?'HTTP '+a.http_status:(a.category||'—'))}${a.category&&a.http_status?`<small>${esc(a.category)}</small>`:''}</td><td>${a.latency_ms} ms</td></tr>`).join('')||'<tr><td colspan="4">Nenhum teste ou execução registrada.</td></tr>'}</tbody></table></div>`;
  modal('Saúde: '+provider.name,'Últimas 30 chamadas reais, sem expor credenciais.',content,async()=>{});
 }catch(e){toast(e.message)}
}
function providers(){return `${heading('INTEGRAÇÕES','Provedores de inteligência artificial','Gerencie APIs, prioridades e disponibilidade medida das conexões.',`<button class="btn btn-primary" data-action="add-provider">＋ Conectar provedor</button>`)}<div class="hint">Estado "Ativo" significa habilitado. Os indicadores abaixo usam somente requisições reais. Suspensões temporárias não alteram suas credenciais e são retomadas com uma única chamada de recuperação após a espera.</div><div class="table-wrap"><table class="data-table"><thead><tr><th>Provedor</th><th>Modelo</th><th>Prioridade</th><th>Saúde</th><th class="right">Ações</th></tr></thead><tbody>${S.providers.map(p=>{const state=healthState(p);const h=p.health||{};return `<tr><td><strong>${esc(p.name)}</strong><small>${esc(p.kind)} · ${p.has_key?'Chave armazenada':'Sem chave'}</small></td><td>${esc(p.model)}</td><td>${p.priority}</td><td><span class="status ${state[1]}">${state[0]}</span><small>${healthNote(p)}${h.state==='suspended'?` · Retorno em ~${h.remaining_seconds}s`:''}</small></td><td><div class="action-group"><button class="btn btn-sm" data-action="test-provider" data-id="${p.id}">Testar</button><button class="btn btn-sm" data-action="health-history" data-id="${p.id}">Histórico</button><button class="btn btn-sm btn-quiet" data-action="edit-provider" data-id="${p.id}">Editar</button><button class="btn btn-sm btn-danger" data-action="delete-provider" data-id="${p.id}">Excluir</button></div></td></tr>`}).join('')||`<tr><td colspan="5"><div class="empty">Nenhum provedor cadastrado.</div></td></tr>`}</tbody></table></div>`}

function agents(){return `${heading('EQUIPE IA','Seus trabalhadores inteligentes','Dez especialidades já estão preparadas. Personalize as instruções e selecione os modelos.',`<button class="btn btn-primary" data-action="add-agent">＋ Criar trabalhador</button>`)}<div class="cards">${S.agents.map(a=>`<article class="agent-card"><div class="card-top"><div class="avatar">${esc(a.avatar)}</div><span class="status ${a.enabled?'completed':'failed'}">${a.enabled?'Disponível':'Desativado'}</span></div><h3>${esc(a.name)}</h3><p>${esc(a.instructions.slice(0,116))}${a.instructions.length>116?'…':''}</p><div class="chips"><span class="chip" title="Especialidade informada">${esc(a.specialty)}</span><span class="chip" title="Papel reconhecido pelo orquestrador">Papel: ${esc(({architecture:'Arquiteto',design:'Designer',frontend:'Frontend',backend:'Backend',code:'Programador',review:'Revisor'}[a.resolved_role]||a.resolved_role||'não reconhecido'))}${a.role_source==='name'?' · nome':''}</span><span class="chip">${esc(S.providers.find(p=>p.id===a.provider_id)?.name||'Modelo automático')}</span></div><div class="agent-actions"><span style="color:var(--muted);font-size:11px">${a.max_concurrency} tarefa(s)/agente*</span><button class="btn btn-sm" data-action="edit-agent" data-id="${a.id}">Configurar →</button></div></article>`).join('')}</div><p class="page-desc" style="margin-top:17px">* Os limites individuais estão salvos nas configurações; nesta versão, o executor aplica um limite global de concorrência.</p>`}
async function refreshWorkspace(){
 if(!S.workspaceProject)S.workspaceProject=S.projects[0]?.id||null;
 if(!S.workspaceProject){S.workspaceInfo=null;return}
 try{S.workspaceInfo=await api(`/projects/${S.workspaceProject}/workspace`)}
 catch(ex){if(ex.message.includes('Prepare primeiro'))S.workspaceInfo={needsSetup:true};else S.workspaceInfo={error:ex.message}}
}

async function refreshSkills(){
 if(!S.skillProject)S.skillProject=S.projects[0]?.id||null;
 if(!S.skillProject){S.skills=[];S.packageAudit=[];return}
 [S.skills,S.packageAudit]=await Promise.all([
  api('/skills?project_id='+encodeURIComponent(S.skillProject)),
  api('/projects/'+encodeURIComponent(S.skillProject)+'/package-installs')]);
}
function skillsView(){
 if(!S.projects.length)return heading('DESIGN','Skills UX/UI','Crie primeiro um projeto.');
 const options=S.projects.map(p=>'<option value="'+esc(p.id)+'" '+(p.id===S.skillProject?'selected':'')+'>'+esc(p.name)+'</option>').join('');
 let result=heading('FERRAMENTAS','Skills UX/UI','Padrões de design que orientam os agentes e catálogo seguro de bibliotecas.');
 result+='<div class="workspace-toolbar"><label for="skills-project">Projeto:</label><select id="skills-project" class="field">'+options+'</select></div>';
 result+=S.skills.map(skill=>'<section class="panel"><div class="panel-head"><h3>'+esc(skill.name)+'</h3><span class="status '+(skill.enabled?'completed':'failed')+'">'+(skill.enabled?'Ativa':'Desativada')+'</span></div><div class="panel-body"><p>'+esc(skill.description)+'</p><p class="page-desc">'+skill.tools.map(esc).join(' · ')+'</p><button class="btn btn-primary btn-sm" data-action="toggle-skill" data-id="'+esc(skill.id)+'" data-enabled="'+(!skill.enabled)+'">'+(skill.enabled?'Desativar Skill':'Ativar Skill neste projeto')+'</button><p class="page-desc">Inclui guias do shadcn/ui; não executa automaticamente sua CLI ou um servidor MCP.</p>'+skill.docs.map(u=>'<a href="'+esc(u)+'" target="_blank" rel="noopener noreferrer">'+esc(u)+'</a>').join(' · ')+'</div></section>').join('');
 result+='<section class="panel"><div class="panel-head"><h3>Instalações registradas</h3></div><div class="panel-body"><p class="page-desc">O Arquiteto precisa de autorização explícita nesta conversa. Somente pacotes do catálogo, sem scripts de instalação npm e sem comandos livres.</p>'+S.packageAudit.map(x=>'<p class="page-desc">'+esc(x.manager)+' '+esc(x.packages)+' — '+esc(x.status)+'</p>').join('')+'</div></section>';
 return result;
}
function workspaceView(){
 const options=S.projects.map(p=>`<option value="${esc(p.id)}" ${S.workspaceProject===p.id?'selected':''}>${esc(p.name)}</option>`).join('');
 const title=heading('ARQUIVOS LOCAIS','Estúdio de projetos','Criação e edição real no Windows com prévia e aprovação humana. Arquivos novos podem ser gravados automaticamente após você solicitar um projeto; substituições e exclusões exigem aprovação. Nenhum comando é executado.',`<button class="btn btn-sm" data-action="workspace-refresh">↻ Atualizar</button>`);
 if(!S.projects.length)return title+'<div class="hint">Primeiro crie um projeto na aba Projetos.</div>';
 const select=`<div class="workspace-toolbar"><label for="ws-project">Projeto:</label><select class="field" id="ws-project">${options}</select><button class="btn btn-sm" data-action="workspace-chat">✦ Trabalhar com agentes</button></div>`;
 const data=S.workspaceInfo||{};
 if(data.needsSetup)return title+select+`<section class="panel panel-body"><h3>Autorizar pasta para este projeto</h3><p class="page-desc">Ao confirmar, a Central criará uma subpasta nova e exclusiva dentro de C:\\Projetos\\Central-IA. Não terá permissão para modificar arquivos fora da raiz.</p><button class="btn btn-primary" data-action="workspace-create">Criar pasta autorizada</button></section>`;
 if(data.error)return title+select+`<div class="hint">${esc(data.error)}</div>`;
 return title+select+`<div class="hint">Pasta autorizada: <code>${esc(data.folder||'')}</code>. Os agentes podem enviar trechos dos arquivos deste projeto ao provedor de IA escolhido. Nunca armazene segredos aqui. Arquivos novos e completos gerados no chat podem ser gravados automaticamente. Substituições e exclusões exigem aprovação; nenhum comando é executado.</div><div class="workspace-columns"><section class="panel"><div class="panel-head"><h3>Explorador de arquivos</h3><button class="btn btn-sm btn-primary" data-action="workspace-new-file">＋ Arquivo</button></div><div class="ws-file-list">${(data.files||[]).map(f=>`<button class="ws-file" data-action="workspace-open-file" data-path="${esc(f.path)}"><span>◫</span><span>${esc(f.path)}</span><small>${f.bytes} B</small></button>`).join('')||'<div class="empty">Pasta vazia. Crie um arquivo manualmente ou peça aos agentes para gerar um projeto.</div>'}</div></section><section class="panel"><div class="panel-head"><h3>Alterações aguardando revisão</h3><span class="status running">${(data.proposals||[]).filter(x=>x.status==='pending').length} pendente(s)</span></div><div class="ws-proposals">${(data.proposals||[]).map(item=>`<div class="ws-proposal"><div><strong>${esc(item.agent||'Edição manual')}</strong><small>${esc(item.files.map(f=>(f.action==='delete'?'Excluir: ':'')+f.path).join(', '))}</small><small>${esc(item.status==='pending'?'Aguardando aprovação':item.status==='applied'?'Aplicada':'Rejeitada')}</small></div><button class="btn btn-sm ${item.status==='pending'?'btn-primary':''}" data-action="workspace-review" data-id="${esc(item.id)}">${item.status==='pending'?'Revisar':'Ver diff'}</button></div>`).join('')||'<div class="empty">Nenhuma proposta. Peça no chat para gerar os arquivos; novos arquivos completos aparecerão aqui automaticamente.</div>'}</div></section></div>`;
}
async function workspaceNewFile(path='',existing=''){
 const editing=!!path;
 const body=`${field('path','Caminho relativo',path,'text',`required ${editing?'readonly':''} placeholder="src/App.jsx"`)}<div class="form-row"><label class="form-label">Conteúdo completo (UTF-8)</label><textarea name="content" rows="12" class="field ws-editor" required maxlength="160000">${esc(existing)}</textarea></div><p class="page-desc">Salvar cria uma PROPOSTA, não grava o arquivo. A gravação exige aprovação posterior.</p>`;
 modal(editing?'Propor edição':'Propor novo arquivo','A edição manual prepara uma proposta: você a revisa e aprova antes da gravação.',body,async f=>{
  await api(`/projects/${S.workspaceProject}/workspace/proposals`,'POST',{files:[{path:f.get('path'),content:f.get('content'),action:'write'}]});
  await renderPage();toast('Proposta criada. Revise-a antes de aplicar.');
 },'Preparar proposta');
}
async function workspaceOpenFile(path){
 const file=await api(`/projects/${S.workspaceProject}/workspace/file?path=${encodeURIComponent(path)}`);
 const form=modal('Arquivo: '+path,'Visualização de texto. Você pode propor uma alteração ou exclusão, ambas exigirão aprovação.',
  `<div class="form-row"><textarea readonly rows="15" class="field ws-editor">${esc(file.content)}</textarea></div><button type="button" class="btn btn-danger" id="ws-delete">Propor exclusão</button>`,async()=>{workspaceNewFile(path,file.content)},'Propor edição');
 form.querySelector('#ws-delete').onclick=async()=>{
  if(!confirm('Preparar uma proposta de exclusão para '+path+'? Nenhum arquivo será excluído agora.'))return;
  try{await api(`/projects/${S.workspaceProject}/workspace/proposals`,'POST',{files:[{path,action:'delete'}]});form.remove();await renderPage();toast('Exclusão proposta: aguarda aprovação.')}catch(e){toast(e.message)}
 };
}
async function workspaceReview(id){
 const pid=S.workspaceProject;
 const preview=await api(`/projects/${pid}/workspace/proposals/${id}`);
 const pending=preview.status==='pending',danger=preview.files.some(x=>x.replace||x.action==='delete');
 const body=`<div class="ws-diff-list">${preview.files.map(f=>`<div class="ws-diff"><strong>${esc(f.path)}</strong><small>${f.action==='delete'?'Excluir arquivo':f.replace?'Substituir arquivo existente':'Criar novo arquivo'} ${f.stale?'<span class="ws-conflict">⚠ Modificado desde a proposta</span>':''}</small><pre>${esc(f.diff)}</pre></div>`).join('')}</div>${pending?`<p class="hint">${danger?'Atenção: esta proposta substitui ou remove arquivos existentes.':'Esta proposta cria novos arquivos.'} Compare o conteúdo antes de continuar.</p>${field('confirmation','Digite APLICAR para gravar os arquivos','','text','required autocomplete="off"')}`:''}`;
 const back=modal('Revisar alterações','O diff exibe o conteúdo que será modificado no seu Windows.',body,async f=>{
   if(!pending)return;
   if(f.get('confirmation')!=='APLICAR')throw new Error('Digite APLICAR exatamente para confirmar.');
   await api(`/projects/${pid}/workspace/proposals/${id}/decision`,'POST',{approved:true,confirmation:'APLICAR'});
   await renderPage();toast('Alterações aplicadas com aprovação.');
 },pending?'Aplicar arquivos':'Fechar');
 if(pending){
  const actions=back.querySelector('.modal-actions');
  const reject=document.createElement('button');reject.type='button';reject.className='btn btn-danger';reject.textContent='Rejeitar proposta';
  reject.onclick=async()=>{try{await api(`/projects/${pid}/workspace/proposals/${id}/decision`,'POST',{approved:false});back.remove();await renderPage();toast('Proposta rejeitada.')}catch(ex){toast(ex.message)}};
  actions.prepend(reject);
 }
}
function projects(){return `${heading('ORGANIZAÇÃO','Projetos','Agrupe conversas por iniciativa e mantenha o histórico acessível.',`<button class="btn btn-primary" data-action="add-project">＋ Criar projeto</button>`)}<div class="cards">${S.projects.map(p=>`<article class="agent-card"><div class="avatar">▤</div><h3>${esc(p.name)}</h3><p>${esc(p.description||'Sem descrição.')}</p><div class="agent-actions"><span style="color:var(--muted);font-size:11px">${fmtDate(p.created_at)}</span><button class="btn btn-sm" data-action="project-chat" data-id="${p.id}">Nova conversa →</button><button class="btn btn-sm btn-primary" data-action="project-files" data-id="${p.id}">▧ Arquivos →</button></div></article>`).join('')||'<div class="panel empty"><div class="empty-icon">▤</div><strong>Nenhum projeto criado</strong>Comece criando um workspace para suas tarefas.</div>'}</div>`}
function history(){return `${heading('REGISTROS','Histórico de execuções','Consulte resultados, erros e horários das tarefas persistidas.',`<button class="btn" data-action="refresh">↻ Atualizar</button>`)}<div class="table-wrap"><table class="data-table"><thead><tr><th>Tarefa</th><th>Data</th><th>Status</th><th>Custo estimado*</th><th class="right">Ações</th></tr></thead><tbody>${S.runs.map(r=>`<tr><td><strong>${esc(r.prompt.slice(0,85))}</strong><small>ID ${esc(r.id.slice(0,8))}</small></td><td>${fmtDate(r.created_at)}</td><td><span class="status ${r.status}">${labelStatus(r.status)}</span></td><td>US$ ${Number(r.total_cost).toFixed(5)}</td><td class="right">${['failed','cancelled'].includes(r.status)?`<button class="btn btn-sm btn-primary" data-action="resume-run" data-id="${r.id}">↻ Retomar</button>`:''}<button class="btn btn-sm" data-action="open-run" data-id="${r.id}" data-convo="${r.conversation_id}">Abrir chat →</button></td></tr>`).join('')||'<tr><td colspan="5" class="empty">Nenhuma tarefa registrada ainda.</td></tr>'}</tbody></table></div><p class="page-desc" style="margin-top:15px">* Estimativas locais, apenas quando o preço por token é informado. Não são valores oficiais de cobrança.</p>`}
function settings(){return `${heading('PREFERÊNCIAS','Configurações','Personalize a aparência e gerencie a sessão.')}
 <div class="grid2"><section class="panel"><div class="panel-head"><h3>Aparência</h3></div><div class="panel-body"><p class="page-desc" style="margin-bottom:15px">Alterne entre os temas da interface.</p><button class="btn" data-action="theme">◐ Mudar para tema ${S.theme==='dark'?'claro':'escuro'}</button></div></section><section class="panel"><div class="panel-head"><h3>Sua conta</h3></div><div class="panel-body"><p>${esc(S.me.email)}</p><p class="page-desc" style="margin-bottom:15px">Os dados ficam na instância em execução. Faça backup da pasta data/, incluindo a chave de criptografia.</p><button class="btn btn-danger" data-action="logout">Sair da conta</button></div></section></div>`}
function workflows(){return `${heading('AUTOMAÇÃO','Fluxos de trabalho','Monte grafos de agentes e aprovações. Execução serial ou paralela conforme as dependências.',`<button class="btn btn-primary" data-action="add-workflow">＋ Criar fluxo</button>`)}<div class="hint">Motor funcional: blocos de agente e aprovação humana, dependências, paralelismo e checkpoints. Condições avançadas, ferramentas externas e ações irreversíveis ainda não são executadas.</div><section class="panel"><div class="panel-head"><h3>Fluxos disponíveis</h3><small>${S.workflows.length} salvo(s)</small></div>${S.workflows.map(w=>`<div class="workflow-card"><div><strong>⌁ ${esc(w.name)}</strong><p>${esc(w.description||'Sem descrição')} · ${w.definition.nodes.length} blocos · v${w.version}</p></div><div class="action-group"><button class="btn btn-sm" data-action="edit-workflow" data-id="${w.id}">Editar</button><button class="btn btn-sm btn-primary" data-action="use-workflow" data-id="${w.id}">Usar no chat →</button></div></div>`).join('')||'<div class="empty"><div class="empty-icon">⌁</div><strong>Crie seu primeiro fluxo</strong>Conecte trabalhadores e adicione etapas de aprovação.</div>'}</section>`}

function chatProjectId(){
 return S.currentConvo
  ? S.conversations.find(c=>c.id===S.currentConvo)?.project_id||null
  : S.projectForNext||null;
}
function chatContextBar(){
 const pid=chatProjectId();
 const options=S.projects.map(p=>
  '<option value="'+esc(p.id)+'" '+(pid===p.id?'selected':'')+'>'+esc(p.name)+'</option>').join('');
 return '<div class="chat-context-bar" aria-label="Contexto da conversa">'
  +'<div class="chat-context-field"><label for="chat-project">▤ Projeto</label>'
  +'<select class="field" id="chat-project" aria-label="Projeto desta conversa">'
  +'<option value="">Sem projeto</option>'+options+'</select></div>'
  +'<div class="chat-context-field chat-context-skills"><span class="chat-context-label">✦ Skills do projeto</span>'
  +'<div id="chat-skill-list" class="chat-skill-list" aria-live="polite">'
  +(pid?'Carregando Skills…':'Selecione um projeto para usar Skills.')+'</div></div>'
  +'<span class="chat-context-note">Skills são compartilhadas por projeto. Trocar de projeto após iniciar o chat abre uma conversa nova e preserva o histórico.</span>'
  +'</div>';
}
function renderChatSkills(){
 const el=$('#chat-skill-list');if(!el)return;
 const pid=chatProjectId();
 if(!pid){el.innerHTML='<span class="chat-context-empty">Nenhum projeto selecionado</span>';return}
 if(!S.chatSkills.length){el.innerHTML='<span class="chat-context-empty">Nenhuma Skill disponível</span>';return}
 el.innerHTML=S.chatSkills.map(skill=>
    '<label class="chat-skill-chip '+(skill.enabled?'active':'')+'" title="'+esc(skill.description)+'">'
    +'<input type="checkbox" class="chat-skill-toggle" data-skill-id="'+esc(skill.id)+'" '
    +(skill.enabled?'checked ':'')+(S.currentRun?'disabled ':'')+'/>'
    +'<span>'+esc(skill.name)+'</span><small>'+(skill.enabled?'Ativa':'Inativa')+'</small></label>'
 ).join('');
}
async function refreshChatContext(){
 const cid=S.currentConvo,pid=chatProjectId();
 if(!pid){S.chatSkills=[];S.delegation=null;renderChatSkills();return}
 const requests=[api('/skills?project_id='+encodeURIComponent(pid))];
 if(cid)requests.push(api('/conversations/'+encodeURIComponent(cid)+'/architect-delegation'));
 const result=await Promise.all(requests);
 if(S.page!=='chat'||chatProjectId()!==pid||S.currentConvo!==cid)return;
 S.chatSkills=result[0];S.delegation=cid?result[1]:null;
 renderChatSkills();
 const btn=$('#architect-permission');if(btn)btn.textContent=S.delegation?.enabled?
   '✓ Arquiteto autorizado':'Arquiteto: autorizar';
}
async function selectChatProject(projectId){
 const old=chatProjectId();
 const select=$('#chat-project');
 if(projectId===old)return;
 if(S.currentRun){
   if(select)select.value=old||'';
   toast('Conclua ou cancele a execução antes de trocar de projeto.');
   return;
 }
 // Draft text is not part of the existing chat history.
 const draft=$('#chat-input')?.value||'';
 try{
   if(!S.currentConvo){
     S.projectForNext=projectId;
   }else{
     const cid=S.currentConvo;
     const messages=await api('/conversations/'+encodeURIComponent(cid)+'/messages');
     const hasRuns=S.runs.some(r=>r.conversation_id===cid);
     if(messages.length||hasRuns){
       if(!confirm('Esta conversa tem histórico. Criar uma NOVA conversa para o projeto escolhido? O histórico e a autorização do Arquiteto da conversa anterior permanecerão separados.')){
         if(select)select.value=old||'';
         return;
       }
       const created=await api('/conversations','POST',
         {title:'Nova conversa',project_id:projectId});
       S.conversations.unshift(created);
       S.currentConvo=created.id;
     }else{
       const updated=await api('/conversations/'+encodeURIComponent(cid)+'/project',
                          'POST',{project_id:projectId});
       const c=S.conversations.find(c=>c.id===cid);if(c)Object.assign(c,updated);
     }
     S.projectForNext=null;
   }
   S.delegation=null;S.chatSkills=[];S.lastSeq=0;S.runSteps=[];S.streams={};
   disconnect();
   await renderPage();
   const input=$('#chat-input');if(input){input.value=draft;input.focus()}
   toast(projectId?'Projeto selecionado para a conversa.':'Conversa sem projeto selecionado.');
 }catch(error){
   if(select)select.value=old||'';
   toast(error.message);
 }
}
async function toggleChatSkill(skillId,enabled){
 if(S.currentRun){toast('Não altere Skills durante uma execução.');renderChatSkills();return}
 const pid=chatProjectId();if(!pid){toast('Selecione um projeto primeiro.');return}
 const skill=S.chatSkills.find(s=>s.id===skillId);
 if(!skill)return;
 try{
   const result=await api('/projects/'+encodeURIComponent(pid)+'/skills/'+encodeURIComponent(skillId),
                     'POST',{enabled});
   skill.enabled=Boolean(result.enabled);
   renderChatSkills();
   toast(skill.name+(skill.enabled?' ativada':' desativada')+' para este projeto.');
 }catch(error){renderChatSkills();toast(error.message)}
}

function chat(){return `<div class="chat-layout"><aside class="chat-left"><button class="btn btn-primary" data-action="new-chat">＋ Nova conversa</button><div class="chat-section-label">Recentes</div><div id="convos">${S.conversations.map(c=>`<button class="conversation ${S.currentConvo===c.id?'active':''}" data-action="switch-convo" data-id="${c.id}">▧ <span>${esc(c.title)}</span></button>`).join('')||'<p style="color:var(--muted);font-size:11px;padding:12px">Suas conversas aparecerão aqui.</p>'}</div></aside><div class="chat-center"><div class="chat-toolbar"><div><strong id="chat-title">${esc(S.conversations.find(c=>c.id===S.currentConvo)?.title||'Nova conversa')}</strong><small>Equipe de especialistas IA</small></div><div class="composer-controls"><select id="chat-mode" class="field"><option value="auto" ${S.mode==='auto'?'selected':''}>✦ Seleção automática</option><option value="manual" ${S.mode==='manual'?'selected':''}>◇ Agente manual</option><option value="team" ${S.mode==='team'?'selected':''}>▣ Equipe de agentes</option></select><button class="btn btn-sm" data-action="architect-delegation" id="architect-permission" title="Permissão apenas nesta conversa e projeto">Arquiteto: autorizar</button><select id="chat-agent" class="field" title="Trabalhador preferido"><option value="">Qualquer trabalhador</option>${S.agents.filter(a=>a.enabled).map(a=>`<option value="${a.id}" ${S.selectedAgent===a.id?'selected':''}>${esc(a.name)}</option>`).join('')}</select></div></div>${chatContextBar()}<div class="chat-transcript" id="chat-transcript"></div><div class="chat-compose"><div class="composer-box"><textarea id="chat-input" rows="2" placeholder="Descreva a tarefa que deseja executar..."></textarea><div class="composer-footer"><div class="composer-controls"><label class="btn btn-sm btn-quiet" for="file-upload" title="Anexar arquivo de texto ou código">＋ Arquivo</label><input type="file" id="file-upload" style="display:none" accept=".txt,.md,.csv,.json,.py,.ts,.tsx,.jsx,.js,.html,.css,.sql,.yaml,.yml,.xml"><span id="attached-label" style="font-size:10px;color:var(--muted)">${S.attached.length?esc(S.attached.map(f=>f.name).join(', ')):'Sem anexos'}</span></div><div class="composer-controls"><button class="btn btn-sm btn-quiet" id="chat-cancel" data-action="cancel-run" hidden>■ Parar</button><button class="btn btn-primary btn-sm" id="chat-send">Enviar ↗</button></div></div></div><small>As tarefas usam suas próprias chaves de API e podem gerar cobranças dos provedores.</small></div></div><aside class="chat-right"><div class="right-head">◎ Painel de execução <span class="dot"></span></div><div id="chat-steps"><div class="right-tip">Nenhuma tarefa em execução. Selecione o modo de trabalho e envie uma solicitação para começar.</div></div><div class="right-tip"><strong>Roteamento inteligente</strong><br>O orquestrador divide solicitações por especialidade e tenta o próximo provedor ativo em caso de falha.</div></aside></div>`}
async function enterChat(){
 $('#chat-mode').onchange=e=>{S.mode=e.target.value;if(S.mode!=='manual'){S.selectedAgent='';$('#chat-agent').value=''}};$('#chat-agent').onchange=e=>{S.selectedAgent=e.target.value;S.mode=e.target.value?'manual':'auto';$('#chat-mode').value=S.mode};
 $('#chat-project').onchange=e=>selectChatProject(e.target.value||null);
 $('#chat-skill-list').onchange=e=>{const box=e.target.closest('.chat-skill-toggle');if(box)toggleChatSkill(box.dataset.skillId,box.checked)};
 $('#chat-send').onclick=sendMessage;$('#chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}};
 $('#file-upload').onchange=async e=>{const f=e.target.files[0];if(!f)return;const body=new FormData();body.append('file',f);try{const result=await api('/uploads/text','POST',body);S.attached.push(result);$('#attached-label').textContent=result.name+(result.truncated?' (trecho inicial)':'');toast('Anexo carregado: '+result.name)}catch(ex){toast(ex.message)}};
 try{await refreshChatContext()}catch(ex){S.chatSkills=[];renderChatSkills();toast(ex.message)}
 if(S.currentConvo)await showMessages(S.currentConvo);
 else showWelcome();
}
function showWelcome(){const root=$('#chat-transcript');if(!root)return;root.innerHTML=`<div class="chat-welcome"><div class="spark">✳</div><h2>O que vamos criar hoje?</h2><p>Converse com um especialista ou coordene uma equipe inteira de trabalhadores IA.</p><div class="starter-pills"><button data-suggest="Crie uma interface de dashboard responsiva e elegante">◈ Criar um dashboard</button><button data-suggest="Desenvolva uma API com autenticação e persistência">⌘ Desenvolver uma API</button><button data-suggest="Analise e melhore a arquitetura de um aplicativo">◎ Revisar arquitetura</button></div></div>`}
async function showMessages(cid){const root=$('#chat-transcript');if(!root)return;try{const messages=await api(`/conversations/${cid}/messages`);root.innerHTML=messages.length?messages.map(m=>messageHTML(m.role,m.agent_name||'Central IA',m.content)).join(''):'';if(!messages.length)showWelcome();scrollChat()}catch(ex){toast(ex.message)}}
function messageHTML(role,agent,content,stepId=''){return `<article class="chat-message ${role==='user'?'user':''}" ${stepId?`data-step="${esc(stepId)}"`:''}><div class="msg-avatar">${role==='user'?'☺':'✳'}</div><div class="message-content"><div class="msg-author">${esc(role==='user'?'Você':agent)}</div><div class="msg-body">${markdown(content)}</div></div></article>`}
function appendMessage(role,agent,content,stepId){let root=$('#chat-transcript');if(!root)return;const welcome=root.querySelector('.chat-welcome');if(welcome)welcome.remove();root.insertAdjacentHTML('beforeend',messageHTML(role,agent,content,stepId));scrollChat()}
function scrollChat(){const root=$('#chat-transcript');if(root)root.scrollTop=root.scrollHeight}
async function ensureConvo(){if(S.currentConvo)return S.currentConvo;const c=await api('/conversations','POST',{title:'Nova conversa',project_id:S.projectForNext||null});S.projectForNext=null;S.conversations.unshift(c);S.currentConvo=c.id;const list=$('#convos');if(list)list.insertAdjacentHTML('afterbegin',`<button class="conversation active" data-action="switch-convo" data-id="${c.id}">▧ <span>Nova conversa</span></button>`);return c.id}
async function sendMessage(){const input=$('#chat-input');let prompt=input?.value.trim();if(!prompt)return;
 if(S.currentRun){toast('Aguarde ou cancele a tarefa atual.');return}
 const attachments=S.attached.map(f=>`\n\nArquivo: ${f.name}\n\`\`\`\n${f.content}\n\`\`\``).join('');
 prompt+=attachments;
 const send=$('#chat-send');if(send)send.disabled=true;
 try{
   const cid=await ensureConvo();
   const data={conversation_id:cid,prompt,mode:S.mode,agent_ids:S.mode==='manual'&&S.selectedAgent?[S.selectedAgent]:[],workflow_id:S.selectedWorkflow||null};
   const res=await api('/runs','POST',data,{headers:{'Idempotency-Key':crypto.randomUUID()}});
   // Only show a user bubble after the server accepted the run.
   appendMessage('user','Você',prompt);
   if(input)input.value='';S.attached=[];$('#attached-label').textContent='Sem anexos';
   S.workspaceRunProject=S.conversations.find(c=>c.id===cid)?.project_id||null;
   S.selectedWorkflow='';S.currentRun=res.id;renderChatSkills();S.lastSeq=0;S.streams={};S.runSteps=[];
   $('#chat-cancel').hidden=false;if(send)send.disabled=true;
   const convo=S.conversations.find(c=>c.id===cid);
   if(convo&&convo.title==='Nova conversa'){
     convo.title=prompt.slice(0,60);$('#chat-title').textContent=convo.title;
     const b=$(`[data-action="switch-convo"][data-id="${cid}"] span`);if(b)b.textContent=convo.title
   }
   watchRun(res.id);
 }catch(ex){
   // Preserve typed prompt and attachments for editing/resubmission.
   toast(ex.message);if(send)send.disabled=false;
   if(/Fluxo UX\/UI não iniciado|Trabalhadores/.test(ex.message)){
     appendEvent('⚠ '+ex.message+' Abra a aba Trabalhadores para corrigir o agente mencionado.');
   }
 }
}
function disconnect(){S.source?.close();S.source=null}
async function watchRun(rid){disconnect();try{const run=await api(`/runs/${rid}`);S.runSteps=run.steps||[];showSteps()}catch{};
 const src=new EventSource(`/api/runs/${rid}/events?after=${S.lastSeq}`);S.source=src;
 src.onmessage=async e=>{
  let msg;try{msg=JSON.parse(e.data)}catch{return}
  if(msg.seq<=S.lastSeq)return;S.lastSeq=msg.seq;
  const d=msg.data;
  if(msg.event==='token'){
   if(S.workspaceRunProject){
     if(!S.streams[d.step_id]){S.streams[d.step_id]={agent:d.agent,text:'',hidden:true};appendEvent('✦ '+d.agent+': preparando arquivos e resultados para o projeto...')}
     return;
   }
   let root=$('#chat-transcript');if(!root)return;
   if(!S.streams[d.step_id]){S.streams[d.step_id]={agent:d.agent,text:''};appendMessage('assistant',d.agent,'',d.step_id)}
   S.streams[d.step_id].text+=d.text;
   const el=Array.from(root.querySelectorAll('[data-step]')).find(x=>x.getAttribute('data-step')===d.step_id);
   if(el){el.querySelector('.msg-body').innerHTML=markdown(S.streams[d.step_id].text);scrollChat()}
  }
  if(msg.event==='step_reset'){if(S.streams[d.step_id]){S.streams[d.step_id].text='';const el=$(`[data-step="${CSS.escape(d.step_id)}"] .msg-body`);if(el)el.innerHTML='<span style="color:var(--muted)">↻ Retentativa do modelo...</span>'}}
  if(msg.event==='run_created'){S.runSteps=d.plan.map(p=>({id:p.id,name:p.name,status:'queued',kind:p.kind}));showSteps();if(d.ui_implementation)appendEvent('🎨 Fluxo UX/UI Studio Pro ativado: Arquiteto, Designer e três tarefas de Frontend, com revisão final.')}
  if(msg.event==='step_status'){const s=S.runSteps.find(s=>s.id===d.id);if(s)Object.assign(s,d);showSteps()}
  if(msg.event==='model_selected'){const s=S.runSteps.find(s=>s.id===d.step_id);if(s){s.model=d.model;s.provider=d.provider;showSteps()}}
  if(msg.event==='approval_requested'){const s=S.runSteps.find(s=>s.id===d.step_id);if(s){s.status='awaiting_approval';showSteps()}}
  if(msg.event==='provider_error')appendEvent('⚠ '+d.provider+': '+d.message);
  if(msg.event==='failover')appendEvent('↻ '+d.message);
  if(msg.event==='provider_suspended')appendEvent('⏸ '+d.provider+': temporariamente suspenso ('+d.category+').');
  if(msg.event==='provider_recovered')appendEvent('✓ '+d.provider+': recuperado com sucesso.');
  if(msg.event==='provider_probe')appendEvent('↻ Verificando recuperação de '+d.provider+'...');
  if(msg.event==='run_failed'){appendEvent('Falha: '+d.error);finishRun(false)}
  if(msg.event==='ui_skill_activated'){
   appendEvent('✓ Skill UI/UX Studio Pro ativada para este projeto a pedido do usuário.');
   try{if(chatProjectId()===d.project_id){S.chatSkills=await api('/skills?project_id='+encodeURIComponent(d.project_id));renderChatSkills()}}catch{}
  }
  if(msg.event==='workspace_prepared'){S.workspaceRunProject=d.project_id;appendEvent('📁 Pasta criada/autorizada: '+d.folder+(d.starter_files?' · '+d.starter_files+' arquivos iniciais gravados.':''))}
  if(msg.event==='workspace_files_created'){appendEvent('✓ Novos arquivos dos trabalhadores gravados automaticamente. Abra Arquivos para conferir.')}
  if(msg.event==='workspace_proposals'){appendEvent('⚠ Alterações em arquivos existentes exigem aprovação. Confira Projetos → Arquivos.')}
  if(msg.event==='workspace_retry_started'){appendEvent('↻ '+d.agent+': tentando entregar um arquivo completo em formato estruturado...')}
  if(msg.event==='workspace_retry_succeeded'){appendEvent('✓ '+d.agent+': arquivo estruturado validado. Aguardando gravação segura.')}
  if(msg.event==='workspace_retry_failed'){appendEvent('⚠ '+d.agent+': nova tentativa sem arquivo válido ('+d.message+').')}
  if(msg.event==='workspace_stage_error'){appendEvent('⚠ Arquivos não aplicados: '+d.message)}
  if(msg.event==='workspace_summary_warning'){appendEvent('⚠ Relatório do projeto: '+d.message+' ('+d.code+' / '+d.type+').')}
  if(msg.event==='architect_approved'){appendEvent('✓ Arquiteto autorizado aprovou '+d.count+' alteração(ões) após revisão.')}
  if(msg.event==='architect_package_install'){appendEvent((d.ok?'✓':'⚠')+' Pacotes: '+(d.manager||'')+' '+(d.packages||[]).join(', ')+(d.ok?' instalados.':' não instalados.'))}
  if(msg.event==='architect_delegation_changed'){S.delegation=d;appendEvent(d.enabled?'Autonomia delegada ao Arquiteto nesta conversa.':'Autonomia do Arquiteto revogada.');const b=$('#architect-permission');if(b)b.textContent=d.enabled?'✓ Arquiteto autorizado':'Arquiteto: autorizar'}
  if(msg.event==='run_completed'){await loadAll();appendEvent('Tarefa concluída. Confira os arquivos reais em Projetos → Arquivos.');await finishRun(true)}
  if(msg.event==='run_status'&&d.status==='cancelled'){appendEvent('Execução cancelada.');finishRun(false)}
 };
 src.onerror=()=>{if(S.currentRun===rid)toast('A conexão de eventos foi interrompida; tentando reconectar...')};
}
function appendEvent(message){const root=$('#chat-transcript');if(!root)return;root.insertAdjacentHTML('beforeend',`<div class="chat-event">${esc(message)}</div>`);scrollChat()}
async function finishRun(ok){disconnect();S.currentRun=null;renderChatSkills();const send=$('#chat-send');if(send)send.disabled=false;const cancel=$('#chat-cancel');if(cancel)cancel.hidden=true;
 // The final consolidated answer is persisted; use it as canonical conversation history.
 if(ok&&S.currentConvo){await showMessages(S.currentConvo)}
}
function showSteps(){const root=$('#chat-steps');if(!root)return;root.innerHTML=S.runSteps.map(s=>`<div class="step-line ${esc(s.status)}"><div><strong>${esc(s.name)}</strong><small>${labelStatus(s.status)}${s.model?' · '+esc(s.model):''}</small>${s.status==='awaiting_approval'?`<div class="approval-card"><p>Este bloco requer confirmação explícita.</p><button class="btn btn-primary" data-action="approve" data-id="${esc(s.id)}">Aprovar</button><button class="btn" data-action="reject" data-id="${esc(s.id)}">Rejeitar</button></div>`:''}</div></div>`).join('')||'<div class="right-tip">Aguardando nova tarefa.</div>'}
function modal(title,description,content,onSubmit,saveLabel='Salvar alterações'){
 const back=document.createElement('div');back.className='modal-back';back.innerHTML=`<div class="modal"><h2>${esc(title)}</h2><p>${esc(description)}</p><form id="modal-form">${content}<div id="modal-error" class="form-error"></div><div class="modal-actions"><button class="btn" type="button" data-close>Cancelar</button><button class="btn btn-primary" type="submit">${esc(saveLabel)}</button></div></form></div>`;
 document.body.append(back);back.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>back.remove());back.onclick=e=>{if(e.target===back)back.remove()};
 const form=back.querySelector('form');form.onsubmit=async e=>{e.preventDefault();const submit=form.querySelector('[type=submit]');submit.disabled=true;try{await onSubmit(new FormData(form),form,back);back.remove()}catch(ex){back.querySelector('#modal-error').textContent=ex.message}finally{submit.disabled=false}};
 return back;
}
function field(name,label,value='',type='text',extra=''){return `<div class="form-row"><label class="form-label">${label}</label><input class="field" name="${name}" type="${type}" value="${esc(value)}" ${extra} /></div>`}
function addProvider(id){const p=S.providers.find(x=>x.id===id);const opts=['openai','anthropic','gemini','deepseek','grok','mistral','ollama','compatible'];
 const body=`<div class="form-grid">${field('name','Nome',p?.name||'', 'text','required minlength="2"')}<div class="form-row"><label class="form-label">Provedor</label><select class="field" name="kind">${opts.map(t=>`<option ${p?.kind===t?'selected':''} value="${t}">${t.toUpperCase()}</option>`).join('')}</select></div></div>
 ${field('model','Identificador real do modelo',p?.model||'','text','required placeholder="ex.: modelo-disponivel-na-api"')}${field('api_key',p?'Nova chave (deixe vazio para manter)':'Chave de API', '', 'password', 'autocomplete="off"')}${field('base_url','URL base da API (opcional nos provedores oficiais)',p?.base_url||'','url','placeholder="Usar endereço padrão"')}
 <div class="form-grid">${field('priority','Prioridade (1 = primeira)',p?.priority||5,'number','min="1" max="99"')}${field('input_price','US$ por milhão de tokens de entrada*',p?.input_price??'','number','step="0.000001" min="0"')}</div>${field('output_price','US$ por milhão de tokens de saída*',p?.output_price??'','number','step="0.000001" min="0"')}<label class="checkbox-row"><input type="checkbox" name="enabled" ${p?.enabled===false?'':'checked'}> Provedor habilitado</label><p style="margin-top:12px">* Opcional. Necessário para limitar orçamento de uma tarefa. Valores estimados, não preços oficiais.</p>`;
 modal(p?'Editar provedor':'Conectar provedor','Configure somente provedores aos quais você possui acesso autorizado.',body,async f=>{
  const n=x=>f.get(x);const payload={name:n('name'),kind:n('kind'),model:n('model'),api_key:n('api_key'),base_url:n('base_url'),priority:+n('priority'),enabled:!!n('enabled'),input_price:n('input_price')===''?null:+n('input_price'),output_price:n('output_price')===''?null:+n('output_price')};
  if(p)await api(`/providers/${p.id}`,'PUT',payload);else await api('/providers','POST',payload);await loadAll();renderPage();toast('Provedor salvo com segurança.')
 },p?'Salvar provedor':'Conectar API');
}
function addAgent(id){const a=S.agents.find(x=>x.id===id);const options=`<option value="">Automático — qualquer provedor ativo</option>${S.providers.map(p=>`<option value="${p.id}" ${a?.provider_id===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}`;
 const body=`<div class="form-grid">${field('name','Nome do trabalhador',a?.name||'','text','required minlength="2"')}${field('avatar','Avatar (caractere)',a?.avatar||'✦')}</div>${field('specialty','Especialidade (código ou descrição)',a?.specialty||'custom')}<small class="page-desc">Para coordenar agentes, use <code>architecture</code>, <code>frontend</code> ou <code>design</code>. Os nomes padrão também são reconhecidos quando a especialidade é descritiva.</small>
 <div class="form-row"><label class="form-label">Instruções de sistema</label><textarea class="field" name="instructions" required minlength="4" rows="5">${esc(a?.instructions||'Você é um assistente especialista. Entregue resultados concretos e verificáveis.')}</textarea></div>
 <div class="form-grid"><div class="form-row"><label class="form-label">Provedor preferencial</label><select class="field" name="provider_id">${options}</select></div>${field('model','Modelo específico (opcional)',a?.model||'')}</div><label class="checkbox-row"><input type="checkbox" name="enabled" ${a?.enabled===false?'':'checked'}> Ativo</label>`;
 modal(a?'Configurar trabalhador':'Novo trabalhador','A identidade do agente é definida pelas instruções e pela especialidade.',body,async f=>{
  const x=k=>f.get(k);const payload={name:x('name'),specialty:x('specialty'),instructions:x('instructions'),avatar:x('avatar')||'✦',provider_id:x('provider_id')||null,model:x('model')||null,enabled:!!x('enabled')};
  if(a)await api(`/agents/${a.id}`,'PUT',payload);else await api('/agents','POST',payload);await loadAll();renderPage();toast('Trabalhador salvo.')
 },a?'Salvar agente':'Criar trabalhador');
}
function addProject(){modal('Novo projeto','Organize suas conversas em um workspace.',`${field('name','Nome do projeto','','text','required') }<div class="form-row"><label class="form-label">Descrição</label><textarea class="field" name="description" rows="3"></textarea></div>`,async f=>{await api('/projects','POST',{name:f.get('name'),description:f.get('description')});await loadAll();renderPage();toast('Projeto criado.')},'Criar projeto')}
function flowEditor(id){const original=S.workflows.find(w=>w.id===id);let nodes=original?structuredClone(original.definition.nodes):[];
 const choices=()=>S.agents.filter(a=>a.enabled).map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('');
 const back=modal(original?'Editar fluxo':'Criar fluxo','Monte etapas dependentes ou paralelas, com aprovação opcional.',`${field('name','Nome do fluxo',original?.name||'Fluxo multiagente','text','required')}<div class="form-row"><label class="form-label">Descrição</label><input class="field" name="description" value="${esc(original?.description||'')}"></div><div class="form-row"><label class="form-label">Adicionar bloco</label><div class="form-grid"><select class="field" id="flow-kind"><option value="agent">Trabalhador IA</option><option value="approval">Aprovação humana</option></select><select class="field" id="flow-agent">${choices()}</select></div><div style="display:flex;gap:9px;margin-top:10px"><button type="button" class="btn btn-sm" id="flow-sequential">＋ Sequencial</button><button type="button" class="btn btn-sm" id="flow-parallel">＋ Paralelo</button></div></div><div class="form-label">Pré-visualização do grafo</div><div id="flow-canvas" class="flow-board"></div>`,async f=>{
  if(!nodes.length)throw new Error('Adicione pelo menos uma etapa ao fluxo.');
  const definition={nodes};const payload={name:f.get('name'),description:f.get('description'),definition};
  if(original)await api(`/workflows/${original.id}`,'PUT',payload);else await api('/workflows','POST',payload);
  await loadAll();renderPage();toast('Fluxo salvo.')
 },original?'Atualizar fluxo':'Salvar fluxo');
 const paint=()=>{back.querySelector('#flow-canvas').innerHTML=nodes.map((n,i)=>`${i?'<span class="flow-arrow">→</span>':''}<div class="flow-node ${n.kind}"><strong>${esc(n.name)}</strong><small>${n.kind==='approval'?'Aprovação humana':nodes.find(x=>x.id===n.deps[0])?'Após: '+esc(nodes.find(x=>x.id===n.deps[0])?.name):'Início / Paralelo'}</small><button type="button" class="icon-btn" data-node-remove="${esc(n.id)}" style="float:right">✕</button></div>`).join('')||'<span style="color:var(--muted)">Adicione blocos para iniciar seu fluxo.</span>';back.querySelectorAll('[data-node-remove]').forEach(b=>b.onclick=()=>{nodes=nodes.filter(n=>n.id!==b.dataset.nodeRemove).map(n=>({...n,deps:n.deps.filter(x=>x!==b.dataset.nodeRemove)}));paint()})};
 const add=parallel=>{const kind=back.querySelector('#flow-kind').value,aid=back.querySelector('#flow-agent').value,agent=S.agents.find(a=>a.id===aid);if(kind==='agent'&&!agent){toast('Selecione um trabalhador.');return};const last=nodes.at(-1),deps=last?(parallel?last.deps:[last.id]):[];nodes.push({id:crypto.randomUUID(),kind,agent_id:kind==='agent'?aid:null,name:kind==='agent'?agent.name:'Aprovação humana',deps,instructions:''});paint()};
 back.querySelector('#flow-kind').onchange=e=>back.querySelector('#flow-agent').disabled=e.target.value==='approval';back.querySelector('#flow-sequential').onclick=()=>add(false);back.querySelector('#flow-parallel').onclick=()=>add(true);paint();
}
async function handleAction(action,id,el){
 if(action==='theme'){S.theme=S.theme==='dark'?'light':'dark';localStorage.setItem('central-theme',S.theme);applyTheme();if(S.page==='settings')renderPage()}
 if(action==='logout'){disconnect();await api('/logout','POST');S.me=null;authView()}
 if(action==='refresh'){await loadAll();renderPage();toast('Informações atualizadas.')}
 if(action==='add-provider')addProvider();if(action==='edit-provider')addProvider(id);
 if(action==='test-provider'){el.disabled=true;el.textContent='Testando...';try{const res=await api(`/providers/${id}/test`,'POST');toast(res.ok?'Conexão validada: '+res.response:'Falha: '+res.error);await loadAll();await renderPage()}catch(ex){toast(ex.message);el.disabled=false;el.textContent='Testar'}}
  if(action==='health-history')await openHealthHistory(id);
 if(action==='delete-provider'){if(!confirm('Excluir este provedor? As credenciais serão apagadas.'))return;await api(`/providers/${id}`,'DELETE');await loadAll();renderPage()}
 if(action==='add-agent')addAgent();if(action==='edit-agent')addAgent(id);
 if(action==='add-project')addProject();
 if(action==='project-chat'){S.projectForNext=id;S.currentConvo=null;S.delegation=null;goto('chat')}
 if(action==='project-files'){S.workspaceProject=id;goto('workspace')}
 if(action==='workspace-refresh'){await renderPage()}
 if(action==='toggle-skill'){
   await api('/projects/'+S.skillProject+'/skills/'+id,'POST',{enabled:el.dataset.enabled==='true'});
   await renderPage();toast('Skill atualizada neste projeto.');
 }
 if(action==='architect-delegation'){
   if(!S.currentConvo && chatProjectId())await ensureConvo();
   if(!S.currentConvo || !chatProjectId()){toast('Selecione primeiro um projeto nesta conversa.');return}
   const enabled=!(S.delegation?.enabled);
   if(enabled&&!confirm('Conceder ao Arquiteto IA, NESTA conversa, autorização para aprovar mudanças comuns de código e instalar somente pacotes permitidos via npm/pip? Instalar software de terceiros envolve riscos. Exclusões, arquivos sensíveis, scripts e comandos livres continuam bloqueados.'))return;
   S.delegation=await api('/conversations/'+S.currentConvo+'/architect-delegation','POST',{enabled});
   const b=$('#architect-permission');if(b)b.textContent=enabled?'✓ Arquiteto autorizado':'Arquiteto: autorizar';
   toast(enabled?'Autonomia registrada nesta conversa.':'Autonomia revogada.');
 }
 if(action==='workspace-create'){await api(`/projects/${S.workspaceProject}/workspace`,'POST');await renderPage();toast('Pasta do projeto criada.')}
 if(action==='workspace-chat'){S.projectForNext=S.workspaceProject;S.currentConvo=null;S.delegation=null;goto('chat');toast('Chat vinculado ao projeto. Peça aos agentes para criar arquivos e depois revise as propostas.')}
 if(action==='workspace-new-file')await workspaceNewFile();
 if(action==='workspace-open-file')await workspaceOpenFile(el.dataset.path);
 if(action==='workspace-review')await workspaceReview(id);
 if(action==='add-workflow')flowEditor();if(action==='edit-workflow')flowEditor(id);
 if(action==='use-workflow'){S.selectedWorkflow=id;S.currentConvo=null;S.projectForNext=null;S.delegation=null;goto('chat');toast('Fluxo selecionado. Envie a tarefa para executá-lo.')}
 if(action==='new-chat'){S.projectForNext=chatProjectId();disconnect();S.currentRun=null;S.currentConvo=null;S.delegation=null;S.lastSeq=0;S.runSteps=[];goto('chat')}
 if(action==='switch-convo'){disconnect();S.currentRun=null;S.currentConvo=id;S.projectForNext=null;S.delegation=null;S.runSteps=[];S.lastSeq=0;goto('chat')}
 if(action==='open-run'){disconnect();S.currentConvo=el.dataset.convo;S.currentRun=null;goto('chat');const r=await api(`/runs/${id}`);if(['running','queued','awaiting_approval'].includes(r.status)){S.currentRun=id;watchRun(id);$('#chat-send').disabled=true;$('#chat-cancel').hidden=false}}
 if(action==='resume-run'){await api(`/runs/${id}/resume`,'POST');await loadAll();renderPage();toast('Execução retomada a partir dos checkpoints concluídos.')}
 if(action==='approve'||action==='reject'){if(!S.currentRun)return;await api(`/runs/${S.currentRun}/steps/${id}/approval`,'POST',{approved:action==='approve'});toast(action==='approve'?'Etapa aprovada.':'Etapa rejeitada.')}
}
document.addEventListener('click',e=>{const node=e.target.closest('[data-page],[data-action],[data-suggest],.copy-code');if(!node)return;
 if(node.hasAttribute('data-page')){goto(node.dataset.page);return}
 if(node.hasAttribute('data-suggest')){const input=$('#chat-input');if(input){input.value=node.dataset.suggest;input.focus()}return}
 if(node.classList.contains('copy-code')){const code=node.parentElement.querySelector('code')?.textContent||'';navigator.clipboard.writeText(code).then(()=>toast('Código copiado.'));return}
 if(node.dataset.action)handleAction(node.dataset.action,node.dataset.id,node).catch(ex=>toast(ex.message))
});
(async()=>{applyTheme();try{S.me=await api('/me');await loadAll();shell()}catch{authView()}})();

document.addEventListener('change',e=>{if(e.target.id==='ws-project'){S.workspaceProject=e.target.value;renderPage().catch(ex=>toast(ex.message))}
 if(e.target.id==='skills-project'){S.skillProject=e.target.value;renderPage().catch(ex=>toast(ex.message))}});
