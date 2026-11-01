'use strict'
// Real Electron acceptance; creates only scratch users/data/projects. No models.
const { _electron: electron, expect } = require('@playwright/test')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const net = require('node:net')

const FIXTURE = `const http=require('node:http');
const args=process.argv.slice(2);const port=Number(args[args.indexOf('--port')+1]);
http.createServer((req,res)=>{res.setHeader('Cache-Control','no-store');
if(req.url==='/probe'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({cookie:!!req.headers.cookie,authorization:!!req.headers.authorization}));return;}
res.setHeader('Content-Type','text/html');res.end('<!doctype html><html><body><h1>Desktop preview</h1><button id="add">Count</button><output id="count">0</output><script>document.querySelector("#add").onclick=()=>document.querySelector("#count").textContent=Number(document.querySelector("#count").textContent)+1</script></body></html>');
}).listen(port,'127.0.0.1');`

function closedPort(port) {
  return new Promise(resolve => {
    const socket = net.createConnection({host:'127.0.0.1',port})
    socket.once('connect',()=>{socket.destroy();resolve(false)})
    socket.once('error',()=>resolve(true))
    socket.setTimeout(2000,()=>{socket.destroy();resolve(false)})
  })
}

async function main() {
  const packaged = process.argv[2]
  const directory = await fs.mkdtemp(path.join(os.tmpdir(),'central-desktop-ui-'))
  const data = path.join(directory,'profile')
  const fixture = path.join(directory,'project')
  const evidence = process.env.CENTRAL_DESKTOP_EVIDENCE || path.join(__dirname,'test-results')
  await fs.mkdir(data)
  await fs.mkdir(fixture)
  await fs.mkdir(evidence,{recursive:true})
  await fs.writeFile(path.join(data,'desktop-dependencies-reviewed-v1'),'v1\n')
  await fs.writeFile(path.join(fixture,'package.json'),JSON.stringify({name:'desktop-preview-proof',scripts:{dev:'node server.cjs'}}))
  await fs.writeFile(path.join(fixture,'server.cjs'),FIXTURE)
  const env={...process.env,CENTRAL_DESKTOP_USER_DATA:data,CENTRAL_DESKTOP_SKIP_WELCOME:'1'}
  delete env.ELECTRON_RUN_AS_NODE
  let app
  let backendPort
  let previewPort
  const report={packaged:!!packaged,isolated_profile:directory,checks:[]}
  async function launch() {
    app=await electron.launch({
      executablePath:packaged || require('electron'),
      args:packaged?[]:[path.join(__dirname,'main.cjs')],env,timeout:90000,
    })
    const page=await app.firstWindow({timeout:90000})
    await page.waitForLoadState('domcontentloaded')
    const opening=page.locator('.cia-intro')
    await expect(opening).toHaveCount(1,{timeout:10000})
    await expect(page.locator('#root')).toHaveJSProperty('inert',true)
    if(!report.checks.includes('opening_seven_seconds_and_return')) {
      await page.waitForTimeout(2000)
      await opening.screenshot({path:path.join(evidence,'glass-cascade-opening.png')})
      await expect(opening).toHaveCount(0,{timeout:10000})
      await expect(page.locator('#root')).toHaveJSProperty('inert',false)
      report.checks.push('opening_seven_seconds_and_return')
      await page.reload()
      await expect(opening).toHaveCount(1)
      await opening.getByRole('button',{name:/Pular abertura/}).click()
      await expect(opening).toHaveCount(0)
      await expect(page.locator('#root')).toHaveJSProperty('inert',false)
      report.checks.push('opening_skip_restores_app')
      await page.reload()
      await expect(opening).toHaveCount(1)
      await page.keyboard.press('Escape')
      await expect(opening).toHaveCount(0)
      report.checks.push('opening_escape_restores_app')
    } else {
      await opening.getByRole('button',{name:/Pular abertura/}).click()
      await expect(opening).toHaveCount(0)
      report.checks.push('opening_reappears_after_restart')
    }
    return page
  }
  async function api(page,endpoint,method='GET',body) {
    return page.evaluate(async ({endpoint,method,body})=>{
      const r=await fetch('/api'+endpoint,{method,headers:{'X-Central-Request':'1','Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
      const value=await r.json()
      if(!r.ok)throw new Error(JSON.stringify(value))
      return value
    },{endpoint,method,body})
  }
  try {
    let page=await launch()
    const errors=[]
    page.on('pageerror',error=>errors.push(error.message))
    await expect(page.getByLabel('E-mail')).toBeVisible({timeout:30000})
    backendPort=Number(new URL(page.url()).port)
    const createMode=page.getByRole('button',{name:'Criar conta',exact:true})
    if(await createMode.isVisible())await createMode.click()
    await page.getByLabel('E-mail').fill('desktop-acceptance@example.test')
    await page.getByLabel('Senha').fill('Desktop-acceptance-only-2026!')
    await page.getByRole('button',{name:/Criar conta grátis/}).click()
    await expect(page.getByRole('button',{name:'Abrir menu'})).toBeVisible({timeout:30000})
    report.checks.push('registration_and_authenticated_ui')
    await expect(page.locator('.desktop-titlebar')).toBeVisible()
    await expect(page.locator('.desktop-titlebar')).toHaveCSS('background-color','rgb(255, 255, 255)')
    await expect(page.locator('.desktop-titlebar')).toHaveCSS('-webkit-app-region','drag')
    const caption=await page.evaluate(()=>({visible:navigator.windowControlsOverlay?.visible,rect:navigator.windowControlsOverlay?.getTitlebarAreaRect().toJSON()}))
    if(!caption.visible || caption.rect.height<30)throw new Error('Native window overlay missing')
    const windowControls=await app.evaluate(({BrowserWindow})=>{
      const w=BrowserWindow.getAllWindows()[0]
      return {minimize:w.isMinimizable(),maximize:w.isMaximizable(),close:w.isClosable()}
    })
    if(!windowControls.minimize || !windowControls.maximize || !windowControls.close)throw new Error('Native caption controls disabled')
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].maximize())
    await expect.poll(()=>app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].isMaximized())).toBe(true)
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].unmaximize())
    await expect.poll(()=>app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].isMaximized())).toBe(false)
    await page.locator('.desktop-titlebar').screenshot({path:path.join(evidence,'white-titlebar.png')})
    report.checks.push('white_draggable_native_caption_and_maximize_restore')

    await expect(page.locator('.central-root')).toHaveAttribute('data-theme','light')
    await page.getByRole('button',{name:'Abrir menu'}).click()
    await expect(page.getByText('Modelos de IA',{exact:true})).toHaveCount(0)
    await page.locator('.central-drawer').screenshot({path:path.join(evidence,'minimal-sidebar.png')})
    await page.getByRole('button',{name:'Fechar menu',exact:true}).click()
    report.checks.push('minimal_sidebar_without_model_gallery')

    const composer=page.getByRole('textbox',{name:'Mensagem ou comando da Central'})
    await page.keyboard.press('Control+k')
    await expect(page.getByRole('listbox',{name:'Comandos',exact:true})).toBeVisible()
    await composer.press('ArrowDown')
    await composer.press('Escape')
    await expect(page.getByRole('listbox',{name:'Comandos',exact:true})).toHaveCount(0)
    await composer.fill('/provedores')
    await composer.press('Enter')
    await expect(page.getByRole('heading',{name:'Conecte sua equipe de IA'})).toBeVisible()
    const search=page.getByRole('textbox',{name:'Buscar servi\u00e7o no cat\u00e1logo'})
    await expect(search).toHaveCSS('background-color','rgb(255, 255, 255)')
    await expect(page.locator('.provider-brand-icon svg').first()).toBeVisible()
    const providerMotion=await page.getByRole('heading',{name:'Google AI Studio / Gemini',exact:true}).locator('..').locator('svg').evaluate(el=>({name:getComputedStyle(el).animationName,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches}))
    if(!providerMotion.reduced && providerMotion.name==='none')throw new Error('Provider icon is not animated')

    await page.screenshot({path:path.join(evidence,'animated-providers.png'),fullPage:true})
    report.checks.push('provider_cards_with_brand_icons')

    await page.getByRole('button',{name:'Abrir menu'}).click()
    await page.getByTitle('Chat IA',{exact:true}).click()
    await page.screenshot({path:path.join(evidence,'ice-white-desktop.png'),fullPage:true})
    await page.setViewportSize({width:390,height:844})
    await expect(composer).toBeVisible()
    const mobile=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}))
    if(mobile.scroll>mobile.viewport+1)throw new Error('Mobile horizontal overflow')
    await composer.fill('/')
    await expect(page.getByRole('listbox',{name:'Comandos',exact:true})).toBeVisible()
    await composer.press('Escape')
    await expect(composer).toHaveCSS('outline-style','none')
    await expect(composer).toHaveCSS('resize','none')
    await expect(page.locator('.liquid-chat-composer')).toHaveCSS('outline-style','none')
    const rim=await page.locator('.liquid-chat-composer').evaluate(el=>getComputedStyle(el).borderTopColor)
    if(!rim.includes('255, 255, 255'))throw new Error('Dark composer rim returned')
    report.checks.push('transparent_composer_without_dark_rim')

    await page.screenshot({path:path.join(evidence,'ice-white-mobile.png'),fullPage:true})
    await page.emulateMedia({reducedMotion:'reduce'})
    await expect(page.locator('.reference-core-icon g').first()).toHaveCSS('animation-iteration-count','1')
    report.checks.push('reduced_motion_stops_repeated_core_animation')
    await page.getByRole('button',{name:'Alternar tema'}).click()
    await expect(page.locator('.central-root')).toHaveAttribute('data-theme','dark')
    await page.getByRole('button',{name:'Alternar tema'}).click()
    await page.setViewportSize({width:1440,height:900})
    report.checks.push('ice_white_slash_keyboard_light_controls_mobile_and_theme')

    await page.getByRole('button',{name:'Abrir menu'}).click()
    await page.getByTitle('Monitoramento',{exact:true}).click()
    const motion=page.getByTestId('motion-studio-panel')
    await expect(motion.getByRole('button',{name:'Recarregar diagnóstico'})).toBeEnabled({timeout:20000})
    await expect(motion.locator('article')).toHaveCount(4)
    await expect(motion.getByText('Execução indisponível',{exact:true})).toHaveCount(4)
    await motion.getByRole('button',{name:'Recarregar diagnóstico'}).click()
    await expect(motion.getByRole('button',{name:'Recarregar diagnóstico'})).toBeEnabled()
    await expect(motion.getByRole('alert')).toHaveCount(0)
    await motion.scrollIntoViewIfNeeded()
    await motion.screenshot({path:path.join(evidence,packaged?'motion-packaged.png':'motion-development.png')})
    report.checks.push('motion_real_capability_diagnostics_and_reload')
    await page.getByRole('button',{name:'Abrir menu'}).click()
    await page.getByTitle('Provedores',{exact:true}).click()
    const runtimes=page.getByRole('region',{name:'Runtimes externos'})
    await runtimes.getByRole('button',{name:'Verificar runtimes externos'}).click()
    await expect(runtimes.getByLabel('Runtime externo',{exact:true})).toBeVisible()
    await expect(runtimes.getByLabel('Runtime externo',{exact:true}).locator('option')).toHaveCount(4)
    await expect(runtimes.getByLabel('Chave API do runtime')).toHaveAttribute('type','password')
    await expect(runtimes.getByRole('button',{name:/Conectar runtime/})).toBeDisabled()
    await runtimes.screenshot({path:path.join(evidence,packaged?'runtimes-packaged.png':'runtimes-development.png')})
    report.checks.push('external_runtime_profiles_and_explicit_connection')
    const runtimeInventory=await api(page,'/runtimes/execution')
    if(runtimeInventory.gemini.status==='configured') {
      // Deterministic catalog fixture; real provider discovery is tested separately.
      let catalogRequests=0
      await page.route('**/api/runtimes/external/gemini/models',async route => {
        catalogRequests++
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({models:[{id:'smoke-no-generation',name:'Smoke'},{id:'smoke-alternative',name:'Alternative'}]})})
      })
      await runtimes.getByLabel('Chave API do runtime').fill('smoke-placeholder-not-a-real-api-key')
      await expect(runtimes.getByLabel('Modelo do runtime externo').locator('option')).toHaveCount(3,{timeout:10000})
      await runtimes.getByLabel('Modelo do runtime externo').selectOption('smoke-no-generation')
      if(catalogRequests!==1)throw new Error('Automatic catalog request duplicated or missing')
      await runtimes.getByRole('button',{name:'Atualizar modelos'}).click()
      await expect.poll(()=>catalogRequests).toBe(2)
      await expect(runtimes.getByLabel('Modelo do runtime externo')).toBeEnabled()
      report.checks.push('automatic_model_catalog_and_refresh_fixture')
      await runtimes.getByRole('button',{name:/Conectar runtime/}).click()
      await expect(runtimes.getByRole('status')).toContainText('Gemini CLI conectado',{timeout:20000})
      const providers=await api(page,'/providers')
      if(!providers.some(p=>p.kind==='gemini_cli' && p.model==='smoke-no-generation'))throw new Error('Runtime provider not persisted')
      report.checks.push('frozen_backend_real_cli_version_and_connection_without_inference')
    }



    const delegator=await api(page,'/agents','POST',{name:'Delegation Architect',specialty:'architecture',instructions:'Plan and delegate real subtasks.'})
    const reviewer=await api(page,'/agents','POST',{name:'Delegation Reviewer',specialty:'review',instructions:'Review independently.'})
    await page.reload()
    await page.getByRole('button',{name:'Abrir menu'}).click()
    await page.getByTitle('Fluxos',{exact:true}).click()
    await page.getByRole('button',{name:/Criar fluxo/}).click()
    const workflow=page.getByRole('dialog')
    await workflow.locator('[name="name"]').fill('Delegation acceptance')
    await workflow.locator('[name="node-agent"]').selectOption(delegator.id)
    await workflow.getByRole('button',{name:/Sequencial/}).click()
    await workflow.getByLabel('Exigir delega\u00e7\u00e3o de Delegation Architect').check()
    await workflow.getByLabel('Instru\u00e7\u00f5es de Delegation Architect').fill('Delegate one concrete task before finishing.')
    await workflow.locator('[name="node-agent"]').selectOption(reviewer.id)
    await workflow.getByRole('button',{name:/Sequencial/}).click()
    await expect(workflow.getByLabel('Exigir delega\u00e7\u00e3o de Delegation Reviewer')).toBeDisabled()
    await workflow.getByRole('button',{name:'Salvar fluxo',exact:true}).click()
    await expect(workflow).toBeHidden()
    const flows=await api(page,'/workflows')
    const savedFlow=flows.find(f=>f.name==='Delegation acceptance')
    if(savedFlow?.definition.nodes[0].required_actions?.[0]!=='delegate_task')throw new Error('Delegation contract not saved')
    await page.getByRole('button',{name:'Editar',exact:true}).last().click()
    await expect(workflow.getByLabel('Exigir delega\u00e7\u00e3o de Delegation Architect')).toBeChecked()
    await expect(workflow.getByLabel('Instru\u00e7\u00f5es de Delegation Architect')).toHaveValue('Delegate one concrete task before finishing.')
    await workflow.screenshot({path:path.join(evidence,'workflow-delegation-packaged.png')})
    await workflow.getByRole('button',{name:'Cancelar',exact:true}).click()
    report.checks.push('workflow_required_delegation_saved_reloaded_and_reviewer_guarded')
    await page.getByRole('button',{name:'Abrir menu'}).click()
    await page.getByTitle('Chat IA',{exact:true}).click()
    const project=await api(page,'/projects','POST',{name:'Desktop acceptance',description:'Scratch project'})
    if(!project.id)throw new Error('No persisted project')
    await expect.poll(async()=>await api(page,'/projects')).toContainEqual(expect.objectContaining({id:project.id}))
    report.checks.push('authenticated_project_creation')
    const security=await app.evaluate(({BrowserWindow})=>{
      const prefs=BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences()
      return {nodeIntegration:prefs.nodeIntegration,contextIsolation:prefs.contextIsolation,sandbox:prefs.sandbox}
    })
    if(security.nodeIntegration || !security.contextIsolation || !security.sandbox)throw new Error('Renderer isolation missing')
    report.checks.push('sandbox_context_isolation_no_node')
    await api(page,'/computer-access','PUT',{mode:'full',folder:fixture})
    const preview=await api(page,'/preview/start','POST',{cwd:''})
    previewPort=Number(new URL(preview.url).port)
    await page.getByRole('button',{name:'Abrir pr\u00e9via',exact:true}).click()
    const frame=page.frameLocator('iframe[title="Navegador embutido: prévia local do aplicativo"]')
    await expect(frame.getByRole('heading',{name:'Desktop preview'})).toBeVisible({timeout:20000})
    await frame.locator('#add').click()
    await expect(frame.locator('#count')).toHaveText('1')
    const previewFrame=page.frames().find(f=>f.url().startsWith(preview.url))
    const probe=await previewFrame.evaluate(async()=>await(await fetch('/probe')).json())
    if(probe.cookie || probe.authorization)throw new Error('Application credentials leaked to preview')
    report.checks.push('authorized_preview_interaction_without_credentials')
    await page.screenshot({path:path.join(evidence,packaged?'desktop-packaged.png':'desktop-development.png'),fullPage:true})
    await api(page,'/preview/stop','POST',{})
    await expect.poll(()=>closedPort(previewPort),{timeout:10000}).toBe(true)
    report.checks.push('preview_shutdown')
    // Controlled HTTP fixtures exercise presentation, not model inference.
    const flowConversation=await api(page,'/conversations','POST',{title:'Flow UI acceptance'})
    let historyRevision=0
    const historyRoute='**/api/conversations/'+flowConversation.id+'/messages'
    await page.route(historyRoute,route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(
      Array.from({length:18},(_,i)=>({role:i%2?'assistant':'user',content:'Registro de leitura '+i+' revisao '+historyRevision+'\n'+('Conteudo anterior para conferir a rolagem. '.repeat(20))}))
    )}))
    const actualProviders=await api(page,'/providers')
    const actualAgents=await api(page,'/agents')
    const flowSteps=[
      {id:'flow-architecture',agent_id:delegator.id,provider_id:'ui-flow-gemini',model:'fixture-gemini',name:'Arquitetura',status:'completed',deps:[]},
      {id:'flow-review',agent_id:reviewer.id,provider_id:'ui-flow-claude',model:'fixture-claude',name:'Revisao',status:'running',deps:['flow-architecture']},
    ]
    const flowData={run_id:'flow-fixture',status:'running',delivery_verified:false,steps:flowSteps,
      agent_messages:[{id:'fixture-message',sender_agent_id:delegator.id,recipient_agent_id:reviewer.id,sender_name:delegator.name,recipient_name:reviewer.name,content:'Fixture: contrato da interface registrado para revisao.'}],
      events:[{seq:1,event:'workspace_action_result',step_id:'flow-architecture',action:'write',path:'exemplo/App.tsx',success:true},
        {seq:2,event:'step_status',step_id:'flow-architecture',status:'completed'},
        {seq:3,event:'workspace_validation',step_id:'flow-review',success:false}],checkpoints:[],native_sessions:[]}
    const flowRun=()=>({id:'flow-fixture',conversation_id:flowConversation.id,status:flowData.status,prompt:'Fixture de apresentacao do fluxo',created_at:new Date().toISOString(),steps:flowSteps})
    const jsonRoute=(route,value)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(value)})
    await page.route('**/api/providers',route=>jsonRoute(route,[...actualProviders,
      {id:'ui-flow-gemini',kind:'gemini',name:'Gemini fixture',model:'fixture',enabled:true},
      {id:'ui-flow-claude',kind:'anthropic',name:'Claude fixture',model:'fixture',enabled:true}]))
    await page.route('**/api/agents',route=>jsonRoute(route,actualAgents.map(a=>a.id===delegator.id?{...a,provider_id:'ui-flow-gemini'}:a.id===reviewer.id?{...a,provider_id:'ui-flow-claude'}:a)))
    await page.route('**/api/runs',route=>jsonRoute(route,[flowRun()]))
    await page.route('**/api/runs/flow-fixture**',route=>{
      const endpoint=new URL(route.request().url()).pathname
      return jsonRoute(route,endpoint.endsWith('/activity')?flowData:endpoint.endsWith('/approvals')?[]:endpoint.endsWith('/flow-fixture')?flowRun():{enabled:false,steps:[],controls:[]})
    })
    await page.reload()
    await expect(page.locator('.cia-intro')).toHaveCount(1)
    await page.locator('.cia-intro').getByRole('button',{name:/Pular abertura/}).click()
    await page.getByRole('button',{name:'Abrir menu'}).click()
    await page.getByTitle('Flow UI acceptance',{exact:true}).click()
    const flowCard=page.getByRole('region',{name:'Fluxo dos trabalhadores no chat'})
    await expect(flowCard).toBeVisible({timeout:15000})
    const executionPanel=page.getByRole('complementary',{name:'Painel da execu\u00e7\u00e3o e pr\u00e9via'})
    if(await executionPanel.isVisible())await page.getByRole('button',{name:'Abrir pr\u00e9via',exact:true}).click()
    await expect(executionPanel).toHaveCount(0)
    const tools=page.locator('.reference-tools')
    await tools.locator('summary').click()
    await expect(tools).toHaveAttribute('open','')
    await tools.locator('.reference-tools-menu p').click()
    await expect(tools).toHaveAttribute('open','')
    await flowCard.locator('.flow-state').click()
    await expect(tools).not.toHaveAttribute('open','')
    await tools.locator('summary').click()
    await page.keyboard.press('Escape')
    await expect(tools).not.toHaveAttribute('open','')
    const transcript=page.locator('div.scrollbar-soft').filter({has:flowCard})
    await transcript.evaluate(el=>{el.scrollTop=200;el.dispatchEvent(new Event('scroll'))})
    const readingPosition=await transcript.evaluate(el=>el.scrollTop)
    flowSteps[1].name='Revisao atualizada 1'
    await expect(page.getByText('Revisao atualizada 1',{exact:true})).toHaveCount(2,{timeout:10000})
    expect(await transcript.evaluate(el=>el.scrollTop)).toBeCloseTo(readingPosition,0)
    await transcript.evaluate(el=>{el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event('scroll'))})
    flowSteps[1].name='Revisao atualizada 2'
    await expect(page.getByText('Revisao atualizada 2',{exact:true})).toHaveCount(2,{timeout:10000})
    expect(await transcript.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(64)
    report.checks.push('chat_preserves_reading_position_and_resumes_follow_at_bottom')
    report.checks.push('tools_preserve_inside_click_and_dismiss_outside_and_escape')
    await expect(flowCard.getByText('Fixture: contrato da interface registrado para revisao.',{exact:true})).toBeVisible()
    await expect(flowCard.getByText('Entrega verificada',{exact:true})).toHaveCount(0)
    await flowCard.screenshot({path:path.join(evidence,'chat-worker-flow-fixture.png')})
    await page.setViewportSize({width:390,height:844})
    await flowCard.scrollIntoViewIfNeeded()
    await expect(flowCard).toBeVisible()
    await flowCard.evaluate(el=>{el.parentElement.scrollTop=el.offsetTop-20})
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
    await page.screenshot({path:path.join(evidence,'chat-worker-flow-mobile-fixture.png')})
    const flowWidth=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}))
    if(flowWidth.scroll>flowWidth.width+1)throw new Error('Flow card mobile overflow')
    flowData.status='paused_operator'
    flowSteps[1].status='paused_operator'
    await expect(flowCard).toHaveAttribute('data-status','paused_operator',{timeout:10000})
    await expect(flowCard.locator('.flow-cursor')).toHaveCount(0)
    await page.setViewportSize({width:1440,height:900})
    report.checks.push('chat_worker_flow_messages_logs_and_mobile_fixture')
    report.checks.push('paused_flow_stops_animation_without_claiming_delivery')
    await page.getByRole('textbox',{name:'Mensagem ou comando da Central'}).fill('/novo')
    await page.getByRole('textbox',{name:'Mensagem ou comando da Central'}).press('Enter')
    await expect(flowCard).toHaveCount(0)
    await page.unroute('**/api/providers')
    await page.unroute('**/api/agents')
    await page.unroute('**/api/runs')
    await page.unroute('**/api/runs/flow-fixture**')
    await page.unroute(historyRoute)

    if(errors.length)throw new Error('Renderer errors: '+errors.join(';'))
    await app.close()
    app=null
    await expect.poll(()=>closedPort(backendPort),{timeout:15000}).toBe(true)
    report.checks.push('owned_backend_shutdown')
    page=await launch()
    backendPort=Number(new URL(page.url()).port)
    await expect(page.getByRole('button',{name:'Abrir menu'})).toBeVisible({timeout:30000})
    const projects=await api(page,'/projects')
    if(!projects.some(p=>p.id===project.id))throw new Error('Project lost after restart')
    report.checks.push('login_and_project_persist_after_restart')
    report.passed=true
  } finally {
    if(app)await app.close()
    if(backendPort)report.final_backend_closed=await closedPort(backendPort)
    if(previewPort)report.final_preview_closed=await closedPort(previewPort)
    await fs.writeFile(path.join(evidence,packaged?'packaged.json':'development.json'),JSON.stringify(report,null,2))
  }
  console.log(JSON.stringify(report,null,2))
}
main().catch(error=>{console.error(error);process.exitCode=1})
