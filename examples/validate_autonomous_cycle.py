"""Real Central + Codex creation, injected UI defect, repair and browser retest.

Uses a NEW isolated data directory and real installed CLI authentication. Model
inferences consume the connected account quota. No production DB or grants.
Approvals are decided by the test operator's fixed local-only policy; the model
cannot approve itself. Generated project files are never repaired by this script.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from central.database import Database, uid, utcnow
from central.engine import Engine
from central.security import Security
from central.computer_access import set_policy
from central.organizations import ensure_personal
from central.task_contract import delivery_evidence


BRIEF = '''Crie um pequeno site responsivo chamado Laboratório Central, um contador
de cliques com visual caprichado, campo Nome, botão Contar e botão Zerar. O contador
começa em zero, aumenta um por clique e volta a zero com Zerar. Use HTML/CSS/JS e
somente módulos nativos do Node, sem dependências nem CDN. IDs públicos de teste:
name no campo, increment no botão Contar, reset no botão Zerar, count no elemento
que mostra SOMENTE o número. Use app.js como módulo JS principal.
Crie package.json com type module, scripts build (checagem de sintaxe JS), test
(node --test com testes reais da lógica) e dev (servidor Node local). O servidor
deve aceitar --host 127.0.0.1 --port NUMERO --strictPort passados por npm run dev,
servir os arquivos atuais sem cache, /api/health com JSON {"ok":true} e favicon
sem 404. Forneça robots.txt válido e llms.txt Markdown descritivo com título,
links locais e mais de 150 caracteres; a auditoria verifica estes arquivos.
Depois de criar, execute build/test, use preview start para iniciar a aplicação,
abra a URL retornada no Chrome DevTools, preencha Nome e teste Contar e Zerar
com cliques reais. Confira números e console, execute Lighthouse desktop e
mobile e corrija tudo que reprovar. O revisor deve ler os arquivos, testar a
interface e confirmar as evidências. Não finalize apenas com um plano.'''

REPAIR = 'Verifique o site deste projeto, teste os botões no navegador e corrija o que estiver quebrado.'

INJECTED = '''
// Deliberate acceptance-test defect, introduced by the test operator.
window.addEventListener('load', () => {
  document.getElementById('increment').onclick = () => {
    document.getElementById('count').textContent = 'Erro';
    console.error('Falha ao incrementar contador');
  };
});
'''

VERIFIER = '''
import {chromium} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
const [url,out]=process.argv.slice(1);
const browser=await chromium.launch({headless:true});
const checks=[];
try {
 for (const [device,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]) {
  const page=await browser.newPage({viewport}); const errors=[]; const failures=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  page.on('requestfailed',r=>failures.push(r.url()));
  page.on('response',r=>{if(r.status()>=400)failures.push(r.status()+' '+r.url())});
  await page.goto(url,{waitUntil:'networkidle'});
  const health=await page.request.get(new URL('/api/health',url).href);
  const healthOK=health.ok() && (await health.json()).ok===true;
  await page.locator('#name').fill('Teste Central');
  await page.locator('#reset').click();
  for(let n=0;n<5;n++)await page.locator('#increment').click();
  const count=(await page.locator('#count').innerText()).trim();
  await page.screenshot({path:out+'/'+device+'.png',fullPage:true});
  await page.locator('#reset').click();
  const reset=(await page.locator('#count').innerText()).trim();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  checks.push({device,count,reset,healthOK,errors,failures,overflow,
    passed:count==='5'&&reset==='0'&&healthOK&&!errors.length&&!failures.length&&!overflow});
  await page.close();
 }
} finally {await browser.close()}
const report={passed:checks.every(c=>c.passed),checks};
await writeFile(out+'/report.json',JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
'''


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def independent_check(url, destination, kit):
    destination.mkdir(exist_ok=False)
    result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', VERIFIER,
                             url, str(destination)], cwd=kit, capture_output=True,
                            text=True, encoding='utf-8', timeout=120)
    if result.returncode:
        raise RuntimeError('Independent browser verifier failed: ' + result.stderr[-2000:])
    report = json.loads(result.stdout.strip().splitlines()[-1])
    print(json.dumps({'independent_check': destination.name, **report}, ensure_ascii=False), flush=True)
    return report


def setup(destination, model):
    from central.addon_catalog import Catalog
    data, workspace = destination / 'data', destination / 'workspace'
    data.mkdir(parents=True)
    workspace.mkdir()
    db = Database(data / 'central.sqlite3')
    security = Security(db, data)
    now, user, project, chat = utcnow(), 'cycle-operator', uid(), uid()
    db.execute('INSERT INTO users VALUES(?,?,?,?)', (user, 'cycle@example.test', 'no-login', now))
    org = ensure_personal(db, user)
    db.execute('INSERT INTO projects(id,user_id,name,description,created_at) VALUES(?,?,?,?,?)',
               (project, user, 'Laboratório Central — ciclo autônomo', 'Ensaio isolado real', now))
    db.execute('INSERT INTO organization_projects VALUES(?,?)', (project, org))
    db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?)', (chat, user, 'Ciclo autônomo', project, now, now))
    db.execute('INSERT INTO providers(id,user_id,name,kind,base_url,model,created_at) VALUES(?,?,?,?,?,?,?)',
               ('codex', user, 'Codex local', 'codex_cli', 'codex://local', model, now))
    for role, name in [('code', 'Codex implementador'), ('review', 'Codex revisor')]:
        db.execute('INSERT INTO agents(id,user_id,name,specialty,instructions,provider_id,model,created_at) '
                   'VALUES(?,?,?,?,?,?,?,?)', (role, user, name, role,
                    'Inspecione os arquivos e a aplicação. Use preview para iniciar o site. '
                    'Confira funcionalidade real antes de finalizar; corrija erros usando as ferramentas.',
                    'codex', model, now))
    set_policy(db, user, 'full', str(workspace))
    manifest = {'$schema': 'https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json',
                'name': 'io.github.ChromeDevTools/chrome-devtools-mcp', 'title': 'Chrome DevTools MCP',
                'description': 'MCP server for Chrome DevTools', 'version': '1.0.1',
                'repository': {'url': 'https://github.com/ChromeDevTools/chrome-devtools-mcp', 'source': 'github'},
                'packages': [{'registryType': 'npm', 'registryBaseUrl': 'https://registry.npmjs.org',
                              'identifier': 'chrome-devtools-mcp', 'version': '1.0.1', 'transport': {'type': 'stdio'}}]}
    catalog = Catalog(db, security)
    preview = catalog.preview(user, 'mcp', 'server.json', json.dumps(manifest).encode())
    resource = catalog.confirm(user, preview['preview_id'], preview['confirmation'])
    catalog.state(user, resource['id'], 'active', resource['sha256'])
    db.close()
    state = {'user_id': user, 'project_id': project, 'chat_id': chat, 'model': model,
             'creation_run': None, 'repair_run': None, 'injected': False, 'completed': False}
    save(destination / 'state.json', state)
    return state


async def run_cycle(destination, model, kit, resume=False):
    from central import live_preview, browser_mcp, worker_preview
    from central.approval_engine import decide
    if not resume:
        destination.mkdir(parents=True, exist_ok=False)
        os.environ['CENTRAL_DATA_DIR'] = str(destination / 'data')
        state = setup(destination, model)
    else:
        state = json.loads((destination / 'state.json').read_text(encoding='utf-8'))
        os.environ['CENTRAL_DATA_DIR'] = str(destination / 'data')
        if state.get('completed'):
            print(json.dumps({'already_completed': True, 'final_report': state['final_report']},
                             ensure_ascii=False), flush=True)
            return
    os.environ['CENTRAL_JOB_MODE'] = 'api'
    db = Database(destination / 'data' / 'central.sqlite3')
    engine = Engine(db, Security(db, destination / 'data'))
    original_emit = engine.emit
    current_run = None
    preview_urls = {}
    audit_preview = None

    def emit(run_id, kind, payload):
        original_emit(run_id, kind, payload)
        if (kind == 'workspace_action_result' and payload.get('success') is True
                and payload.get('summary', {}).get('action') == 'preview'):
            try:
                status = json.loads(payload.get('output', '{}'))
                if status.get('status') == 'running' and status.get('url'):
                    preview_urls[run_id] = status['url']
            except ValueError:
                pass
        if kind in ('step_status', 'run_status', 'run_failed', 'worker_message', 'workspace_validation'):
            print(json.dumps({'run_id': run_id, 'event': kind, **payload}, ensure_ascii=False), flush=True)
        if kind == 'workspace_approval_required':
            row = db.one('SELECT request_json FROM workspace_action_approvals WHERE id=?', (payload['approval_id'],))
            request = json.loads(row['request_json'])
            allowed = run_id == current_run
            if request['action'] == 'browser_tool':
                arguments = request.get('arguments', {})
                if 'url' in arguments:
                    base = live_preview.info(state['user_id']).get('url', '')
                    allowed = allowed and bool(base) and arguments['url'].startswith(base)
            elif request['action'] == 'preview':
                allowed = allowed and request.get('operation') == 'start' and request.get('cwd', '') == ''
            else:
                allowed = False  # No installs, external research or other critical actions.
            decide(db, state['user_id'], run_id, payload['approval_id'], allowed)
            original_emit(run_id, 'test_operator_approval', {
                'approval_id': payload['approval_id'], 'approved': allowed,
                'policy': 'isolated_test_local_browser_and_preview_only'})

    engine.emit = emit

    async def stage(key, prompt):
        nonlocal current_run
        run_id = state.get(key)
        if not run_id:
            run_id = engine.create_run(state['user_id'], state['chat_id'], prompt, 'manual',
                                       agent_ids=['code', 'review'], autonomous=True)
            state[key] = run_id
            save(destination / 'state.json', state)
        current_run = run_id
        existing = db.one('SELECT status FROM runs WHERE id=?', (run_id,))
        if existing['status'] in ('failed', 'paused_limit'):
            engine.resume_run(run_id)
        if existing['status'] != 'completed':
            await asyncio.wait_for(engine.process(run_id), timeout=1500)
        result = db.one('SELECT status,error FROM runs WHERE id=?', (run_id,))
        save(destination / (key + '-evidence.json'), delivery_evidence(db, run_id))
        print(json.dumps({'stage': key, 'run_id': run_id, **result}, ensure_ascii=False), flush=True)
        if result['status'] != 'completed':
            raise RuntimeError('Stage failed; journal/checkpoint preserved: ' + str(result))
        return run_id

    async def clean(run_id):
        await browser_mcp.close_run(run_id)
        await worker_preview.close_run(run_id)

    try:
        if not state['injected']:
            created = await stage('creation_run', BRIEF)
            url = preview_urls.get(created)
            if not url:
                # On a harness restart, its process-local preview is gone. A
                # separate operator preview is only for independent acceptance;
                # first demand proof that the worker started one itself.
                starts = db.all("SELECT payload FROM events WHERE run_id=? AND event='workspace_action_result'", (created,))
                proved = any((p := json.loads(row['payload'])).get('success') is True
                             and p.get('summary', {}).get('action') == 'preview'
                             and p['summary'].get('operation') == 'start' for row in starts)
                assert proved, 'Worker did not start its preview'
                result = await asyncio.to_thread(live_preview.start, db, state['user_id'], '')
                audit_preview = live_preview._SESSIONS[state['user_id']]
                url = result['url']
                original_emit(created, 'test_operator_preview_restarted', {
                    'purpose': 'independent_acceptance_after_harness_restart', 'url': url})
            # process() is called directly: the operator holds cleanup until its
            # independent acceptance checks finish. Worker authorization is not
            # extended beyond completion; no worker tools run during this check.
            baseline = independent_check(url, destination / 'baseline', kit)
            assert baseline['passed'], baseline
            path = destination / 'workspace' / 'app.js'
            before = path.read_bytes()
            path.write_bytes(before + INJECTED.encode())
            save(destination / 'defect.json', {'path': 'app.js', 'before_sha256': hashlib.sha256(before).hexdigest(),
                                               'injected_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                               'operator_injected_only': True})
            original_emit(created, 'test_defect_injected', {'path': 'app.js', 'purpose': 'repair_acceptance'})
            broken = independent_check(url, destination / 'broken', kit)
            assert broken['passed'] is False and any(c['count'] == 'Erro' for c in broken['checks']), broken
            state['injected'] = True
            save(destination / 'state.json', state)
            if audit_preview:
                await asyncio.to_thread(live_preview.stop, state['user_id'], audit_preview)
                audit_preview = None
            await clean(created)
        repaired = await stage('repair_run', REPAIR)
        url = preview_urls.get(repaired)
        assert url, 'Repair worker did not start preview'
        final_dir = destination / ('repaired-' + utcnow().replace(':', '-'))
        report = independent_check(url, final_dir, kit)
        assert report['passed'], report
        evidence = delivery_evidence(db, repaired)
        assert 'app.js' in evidence['changed_files'], evidence
        assert evidence['tests_passed'] and evidence['validation_after_last_change'], evidence
        assert 'click' in evidence['browser_tools'], evidence
        tool_events = [(row['seq'], json.loads(row['payload'])) for row in db.all(
            "SELECT seq,payload FROM events WHERE run_id=? AND event='workspace_action_result' ORDER BY seq", (repaired,))]
        first_edit = min(seq for seq, payload in tool_events if payload.get('success') is True
                         and payload.get('summary', {}).get('action') in ('write', 'replace'))
        reproduced = any(seq < first_edit and payload.get('summary', {}).get('tool') == 'list_console_messages'
                         and payload.get('qa_pass') is False for seq, payload in tool_events)
        assert reproduced, 'Worker must reproduce and observe the injected defect before editing'
        state['completed'] = True
        state['final_report'] = str(final_dir / 'report.json')
        state['operator_application_repairs'] = 0
        state['worker_reproduced_before_repair'] = reproduced
        save(destination / 'state.json', state)
        print(json.dumps({'completed': True, **state}, ensure_ascii=False), flush=True)
    finally:
        if audit_preview:
            await asyncio.to_thread(live_preview.stop, state['user_id'], audit_preview)
        for run_id in (state.get('creation_run'), state.get('repair_run')):
            if run_id:
                await clean(run_id)
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--kit', type=Path, required=True, help='Directory with installed @playwright/test')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    asyncio.run(run_cycle(args.destination.resolve(), args.model, args.kit.resolve(), args.resume))


if __name__ == '__main__':
    main()
