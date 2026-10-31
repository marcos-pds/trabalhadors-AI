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
      await runtimes.getByLabel('Chave API do runtime').fill('smoke-placeholder-not-a-real-api-key')
      await runtimes.getByLabel('Modelo do runtime externo').fill('smoke-no-generation')
      await runtimes.getByRole('button',{name:/Conectar runtime/}).click()
      await expect(runtimes.getByRole('status')).toContainText('Gemini CLI conectado',{timeout:20000})
      const providers=await api(page,'/providers')
      if(!providers.some(p=>p.kind==='gemini_cli' && p.model==='smoke-no-generation'))throw new Error('Runtime provider not persisted')
      report.checks.push('frozen_backend_real_cli_version_and_connection_without_inference')
    }


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
    await page.getByTitle('Abrir prévia do projeto').click()
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
