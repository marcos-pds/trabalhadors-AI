"""Verify a Central-generated full-stack application with real HTTP + Playwright.

Lab-only, operator-invoked, read-only on Central's SQLite. Creates test users
and tasks ONLY in the generated app. Does not run or install generated code.
"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from urllib.parse import urlsplit

from central.fullstack_acceptance import AcceptanceError, evaluate

SCRIPT = r"""
import {chromium, request} from '@playwright/test';
import {randomUUID} from 'node:crypto';
import {writeFile} from 'node:fs/promises';

const [uiURL,apiURL,folder]=process.argv.slice(1);
const names=['health','anonymous_denied','register','login','team_create',
 'task_create','task_update','task_list_persisted','task_filter'];
const api=Object.fromEntries(names.map(n=>[n,false]));
const devices={};const errors=[];
const email='test-'+randomUUID()+'@example.invalid';
const password='AcceptanceTest!2468';
const title='Card-'+randomUUID().slice(0,8);
const client=await request.newContext({baseURL:apiURL,timeout:12000,ignoreHTTPSErrors:false});
let browser=null;
async function send(method,path,data,token) {
 return await client[method](path,{data,maxRedirects:0,
  headers:token?{'Authorization':'Bearer '+token}:{}});
}
async function body(res) {try{return await res.json()}catch{return {}}}
try {
 let res=await send('get','/api/health');
 api.health=res.ok()&&(await body(res)).ok===true;
 res=await send('get','/api/tasks');
 api.anonymous_denied=[401,403].includes(res.status());
 res=await send('post','/api/auth/register',{email,password});
 api.register=[200,201].includes(res.status());
 res=await send('post','/api/auth/login',{email,password});
 const tokenObject=await body(res);
 const token=tokenObject.access_token;
 api.login=res.ok()&&typeof token==='string'&&token.length>10;
 if(api.login){
   res=await send('post','/api/teams',{name:'Acceptance Team'},token);
   const team=await body(res),teamId=team.id;
   api.team_create=[200,201].includes(res.status())&&typeof teamId==='string';
   if(api.team_create){
     res=await send('post','/api/tasks',{title,team_id:teamId,status:'todo'},token);
     const task=await body(res),taskId=task.id;
     api.task_create=[200,201].includes(res.status())&&typeof taskId==='string';
     if(api.task_create){
       res=await send('patch','/api/tasks/'+encodeURIComponent(taskId),{status:'doing'},token);
       api.task_update=res.ok()&&(await body(res)).status==='doing';
       res=await send('get','/api/tasks',undefined,token);
       const listed=await body(res);
       api.task_list_persisted=res.ok()&&Array.isArray(listed)&&
         listed.some(t=>t.id===taskId&&t.title===title&&t.status==='doing');
       res=await send('get','/api/tasks?status=doing',undefined,token);
       const filtered=await body(res);
       api.task_filter=res.ok()&&Array.isArray(filtered)&&
         filtered.some(t=>t.id===taskId)&&filtered.every(t=>t.status==='doing');
     }
   }
 }
 if(api.login){
   browser=await chromium.launch({headless:true});
   for(const [device,viewport] of [['desktop',{width:1440,height:900}],
                                    ['mobile',{width:390,height:844}]]){
     const flags=Object.fromEntries(['login','task_visible','task_created',
       'no_console_errors','no_request_errors','no_overflow'].map(k=>[k,false]));
     const logs=[],requests=[];
     const page=await browser.newPage({viewport});
     await page.route('**/*',route=>{
       const host=new URL(route.request().url()).hostname;
       if(['localhost','127.0.0.1','[::1]','::1'].includes(host))
         return route.continue();
       return route.abort('blockedbyclient');
     });
     page.on('pageerror',e=>logs.push(e.message));
     page.on('console',msg=>{if(msg.type()==='error')logs.push(msg.text())});
     page.on('requestfailed',req=>requests.push(req.url()));
     page.on('response',res=>{if(res.status()>=400)requests.push(String(res.status()))});
     try {
       await page.goto(uiURL,{waitUntil:'networkidle',timeout:30000});
       await page.getByTestId('login-email').fill(email);
       await page.getByTestId('login-password').fill(password);
       await page.getByTestId('login-button').click();
       await page.getByTestId('task-card').filter({hasText:title}).waitFor({timeout:15000});
       flags.login=true;flags.task_visible=true;
       const fresh='Browser-'+randomUUID().slice(0,8);
       await page.getByTestId('create-task-title').fill(fresh);
       await page.getByTestId('create-task-button').click();
       await page.getByTestId('task-card').filter({hasText:fresh}).waitFor({timeout:15000});
       flags.task_created=true;
       flags.no_overflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);
       await page.screenshot({path:folder+'/'+device+'.png',fullPage:true});
     }catch(e){errors.push(device+': '+String(e.message).slice(0,240))}
     flags.no_console_errors=logs.length===0;
     flags.no_request_errors=requests.length===0;
     devices[device]=flags;
     await page.close();
   }
 }
}catch(e){errors.push('api: '+String(e.message).slice(0,240))}
finally{await client.dispose();if(browser)await browser.close()}
const report={schema_version:1,api,devices,errors};
await writeFile(folder+'/independent.json',JSON.stringify(report,null,2));
console.log(JSON.stringify({api,devices,error_count:errors.length}));
if(errors.length)process.exitCode=1;
"""


def local_url(raw):
    try:
        parsed = urlsplit(raw)
        if (parsed.scheme != "http" or parsed.hostname not in
                ("localhost", "127.0.0.1", "::1") or
                not parsed.port or parsed.username or parsed.password or
                parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("not local")
    except ValueError as exc:
        raise AcceptanceError("URL deve ser HTTP loopback com porta.") from exc
    return raw.rstrip("/") + "/"


class ReadOnlyDatabase:
    def __init__(self, path):
        self.conn = sqlite3.connect(Path(path).resolve(strict=True).as_uri() + "?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row

    def one(self, sql, args=()):
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def all(self, sql, args=()):
        return [dict(row) for row in self.conn.execute(sql, args)]

    def close(self):
        self.conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-id", "user-id", "ui-url", "api-url"):
        parser.add_argument("--" + name, required=True)
    for name in ("db", "workspace", "kit", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    ui, api = local_url(args.ui_url), local_url(args.api_url)
    kit = args.kit.resolve(strict=True)
    if not (kit / "node_modules" / "@playwright" / "test").is_dir():
        parser.error("Kit Playwright inexistente; o script nao instala ferramentas.")
    node = shutil.which("node")
    if not node:
        parser.error("Node.js inexistente.")
    db = ReadOnlyDatabase(args.db)
    try:
        run = db.one("SELECT id FROM runs WHERE id=? AND user_id=?",
                     (args.run_id, args.user_id))
        bound = db.one("SELECT folder FROM run_workspace_bindings "
                       "WHERE run_id=? AND user_id=?", (args.run_id, args.user_id))
        if not run or not bound or (Path(bound["folder"]).resolve(strict=True)
                                   != args.workspace.resolve(strict=True)):
            raise AcceptanceError("Conta, execucao e pasta nao correspondem.")
        args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        completed = subprocess.run([node, "--input-type=module", "-e",
                                    SCRIPT, ui, api, str(args.output.resolve())],
                                   cwd=kit, capture_output=True, text=True,
                                   encoding="utf-8", timeout=180)
        path = args.output / "independent.json"
        independent = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        report = evaluate(db, args.user_id, args.run_id, args.workspace, independent)
        report["browser_exit_code"] = completed.returncode
        report["passed"] = report["passed"] and completed.returncode == 0
        if completed.returncode:
            report["failed"].append("independent_verifier_process")
        report["collected_by"] = "operator_invoked_playwright_local_only"
        output = args.output / "acceptance.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed":report["passed"], "failed":report["failed"],
                          "report":str(output)}, ensure_ascii=False))
        return 0 if report["passed"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
