"""Durable job graph, parallel workers, checkpoints, failover and event journal."""
import asyncio
import json
import random
from collections import defaultdict
from .database import uid, utcnow
from .providers import ProviderClient, ProviderError

TEMPLATES = [
 ('Arquiteto IA','architecture','Planeje soluções técnicas de maneira clara. Defina dependências, interfaces e critérios de aceite.','◈'),
 ('Frontend IA','frontend','Implemente frontend com foco em UX, acessibilidade, componentes reais e responsividade.','◇'),
 ('Backend IA','backend','Projete e implemente APIs, autenticação, persistência, validações e segurança.','⬡'),
 ('Designer IA','design','Produza direção visual, UI elegante, microinterações, hierarquia tipográfica e experiência do usuário.','✺'),
 ('Programador IA','code','Implemente código completo, coerente, legível e testável.','⌘'),
 ('Revisor IA','review','Analise resultados criticamente, aponte defeitos e valide critérios com rigor.','✓'),
 ('Pesquisador IA','research','Pesquise e compare alternativas. Sem ferramenta de busca, reconheça limitações e não invente referências.','◎'),
 ('DevOps IA','devops','Pipelines, infraestrutura, observabilidade, confiabilidade e execução segura.','⚙'),
 ('Vídeo e Legendas IA','video','Oriente transcrição, legendagem, edição e automação de vídeos.','▣'),
 ('Coordenador IA','coordination','Una resultados, priorize entregas e explique decisões e pendências.','✦'),
]

KEYWORDS = {
 'frontend': ['frontend','front-end','react','interface','componente','css','html','tela','página','dashboard'],
 'backend': ['backend','back-end','api','servidor','banco','database','autenticação','login','endpoint'],
 'design': ['design','layout','visual','estilo','figma','ui','identidade'],
 'research': ['pesquis','compare','compar','estud','analis'],
 'devops': ['deploy','docker','devops','infra','ci/cd','pipeline'],
 'video': ['vídeo','video','legenda','transcri','reels'],
 'code': ['código','program','função','script','bug','corrij'],
}


def discover_agents(agents, prompt, mode='auto', agent_ids=None):
    candidates = [a for a in agents if a['enabled']]
    if agent_ids:
        selected = [a for a in candidates if a['id'] in agent_ids]
        return selected[:5]
    if not candidates: return []
    if mode == 'manual': return candidates[:1]
    lower = prompt.lower()
    specialties = [name for name, words in KEYWORDS.items() if any(w in lower for w in words)]
    filtered = [a for a in candidates if a['specialty'] in specialties]
    if mode == 'team' and not filtered:
        filtered = [a for a in candidates if a['specialty'] in ('architecture','code','review')]
    return filtered[:3] if filtered else [next((a for a in candidates if a['specialty']=='coordination'), candidates[0])]


def create_plan(agents):
    if not agents: return []
    jobs = [{'id': uid(), 'agent_id': a['id'], 'name': a['name'], 'kind': 'agent', 'deps': [], 'instructions': ''} for a in agents]
    return jobs


def validate_flow(definition, agents):
    """Small DAG workflow builder, with agent and human approval nodes."""
    nodes = definition.get('nodes', [])
    if not isinstance(nodes, list) or len(nodes) > 20 or not nodes:
        raise ValueError('O fluxo deve conter entre 1 e 20 blocos.')
    ids = {n.get('id') for n in nodes}
    if len(ids) != len(nodes) or None in ids: raise ValueError('IDs de blocos duplicados/inválidos.')
    known_agents = {a['id'] for a in agents}
    for n in nodes:
        if n.get('kind') not in ('agent','approval'):
            raise ValueError('Somente blocos de agente e aprovação são executáveis nesta versão.')
        if n['kind']=='agent' and n.get('agent_id') not in known_agents:
            raise ValueError('O fluxo referencia trabalhador indisponível.')
        if not isinstance(n.get('deps', []),list) or any(d not in ids or d==n['id'] for d in n.get('deps',[])):
            raise ValueError('Dependências de fluxo inválidas.')
    seen = set()
    remaining = nodes[:]
    while remaining:
        ready = [n for n in remaining if all(d in seen for d in n.get('deps',[]))]
        if not ready: raise ValueError('Fluxo contém dependências cíclicas.')
        for n in ready:
            seen.add(n['id'])
            remaining.remove(n)
    return nodes


class Engine:
    def __init__(self, db, security, client=None):
        self.db = db
        self.security = security
        self.client = client or ProviderClient()
        self.running = {}
        self.shutting_down = False
        self.sem = asyncio.Semaphore(5)
        self.agent_sems = {}
        self.circuit = {}  # (provider_id, model) -> monotonic expiry
        self.approvals = defaultdict(asyncio.Event)

    def emit(self, run_id, kind, data):
        self.db.event(run_id, kind, data)

    def schedule(self, run_id):
        if run_id in self.running and not self.running[run_id].done(): return
        task = asyncio.create_task(self.process(run_id))
        self.running[run_id] = task
        task.add_done_callback(lambda _: self.running.pop(run_id, None) if self.running.get(run_id) is task else None)

    def resume_pending(self):
        # This is safe for text-only generation; no external write tools are enabled.
        for row in self.db.all("SELECT id FROM runs WHERE status IN ('queued','running','awaiting_approval')"):
            self.db.execute("UPDATE steps SET status='queued' WHERE run_id=? AND status IN ('running','awaiting_approval')", (row['id'],))
            self.schedule(row['id'])

    def create_run(self, user_id, conversation_id, prompt, mode, agent_ids=None,
                   flow=None, budget=None, idempotency_key=None):
        if idempotency_key:
            existing = self.db.one('SELECT id FROM runs WHERE user_id=? AND idempotency_key=?', (user_id,idempotency_key))
            if existing: return existing['id']
        agents = self.db.all('SELECT * FROM agents WHERE user_id=? AND enabled=1', (user_id,))
        if flow:
            nodes = validate_flow(flow, agents)
            plan = [dict(id=n['id'], agent_id=n.get('agent_id'), name=n.get('name','Etapa'),
                         kind=n['kind'], deps=n.get('deps',[]), instructions=n.get('instructions','')) for n in nodes]
        else:
            chosen = discover_agents(agents, prompt, mode, agent_ids)
            if not chosen: raise ValueError('Cadastre ou habilite pelo menos um trabalhador.')
            plan = create_plan(chosen)
            if len(chosen) > 1 and not any(a['specialty']=='review' for a in chosen):
                reviewer = next((a for a in agents if a['specialty']=='review'), None)
                if reviewer:
                    plan.append({'id':uid(),'agent_id':reviewer['id'],'name':reviewer['name'],
                                 'kind':'agent','deps':[p['id'] for p in plan],'instructions':'Revise as entregas anteriores; reporte problemas concretos e ressalvas.'})
        run_id, now = uid(), utcnow()
        try:
            self.db.execute('''INSERT INTO runs(id,user_id,conversation_id,prompt,status,mode,agent_ids,plan,
             budget_limit,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
             (run_id,user_id,conversation_id,prompt,'queued',mode,json.dumps(agent_ids or []),json.dumps(plan),budget,idempotency_key,now,now))
        except Exception:
            if idempotency_key:
                existing = self.db.one('SELECT id FROM runs WHERE user_id=? AND idempotency_key=?', (user_id,idempotency_key))
                if existing: return existing['id']
            raise
        for p in plan:
            self.db.execute('''INSERT INTO steps(id,run_id,agent_id,kind,name,deps,instructions,status,created_at,updated_at)
             VALUES(?,?,?,?,?,?,?,?,?,?)''',
             (p['id'],run_id,p['agent_id'],p['kind'],p['name'],json.dumps(p['deps']),p['instructions'],'queued',now,now))
        self.emit(run_id,'run_created',{'mode':mode,'plan':plan})
        self.schedule(run_id)
        return run_id

    async def process(self, run_id):
        run = self.db.one('SELECT * FROM runs WHERE id=?', (run_id,))
        if not run: return
        self.db.execute("UPDATE runs SET status='running',updated_at=? WHERE id=?", (utcnow(),run_id))
        self.emit(run_id,'run_status',{'status':'running'})
        try:
            while True:
                steps = self.db.all('SELECT * FROM steps WHERE run_id=?', (run_id,))
                done = {s['id'] for s in steps if s['status']=='completed'}
                pending = [s for s in steps if s['status']=='queued']
                if not pending: break
                ready = [s for s in pending if set(json.loads(s['deps'])).issubset(done)]
                if not ready: raise RuntimeError('Nenhuma etapa executável. Verifique dependências e etapas falhas.')
                outcomes = await asyncio.gather(*(self.execute_step(run, s) for s in ready), return_exceptions=True)
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        raise outcome
            steps = self.db.all('SELECT * FROM steps WHERE run_id=?', (run_id,))
            complete = [s for s in steps if s['kind']=='agent' and s['output']]
            output = '\n\n'.join(f"## {s['name']}\n\n{s['output']}" for s in complete)
            if not output: output = 'Fluxo concluído.'
            self.db.execute("UPDATE runs SET status='completed',output=?,updated_at=? WHERE id=?", (output,utcnow(),run_id))
            self.db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                 (uid(),run['conversation_id'],run['user_id'],'assistant','Central IA',output,utcnow()))
            self.emit(run_id,'run_completed',{'output':output})
        except asyncio.CancelledError:
            new_status = 'queued' if self.shutting_down else 'cancelled'
            self.db.execute('UPDATE runs SET status=?,updated_at=? WHERE id=?', (new_status,utcnow(),run_id))
            self.db.execute("UPDATE steps SET status='queued' WHERE run_id=? AND status IN ('running','awaiting_approval')", (run_id,))
            self.emit(run_id,'run_status',{'status':new_status})
            raise
        except Exception as ex:
            error = str(ex)[:320]
            self.db.execute("UPDATE steps SET status='failed',error=?,updated_at=? WHERE run_id=? AND status='running'", (error,utcnow(),run_id))
            self.db.execute("UPDATE runs SET status='failed',error=?,updated_at=? WHERE id=?", (error,utcnow(),run_id))
            self.emit(run_id,'run_failed',{'error':error})

    async def execute_step(self, run, step):
        sid = step['id']
        self.db.execute("UPDATE steps SET status='running',updated_at=? WHERE id=?", (utcnow(),sid))
        self.emit(run['id'],'step_status',{'id':sid,'name':step['name'],'status':'running'})
        if step['kind']=='approval':
            self.db.execute("UPDATE runs SET status='awaiting_approval' WHERE id=?", (run['id'],))
            self.db.execute("UPDATE steps SET status='awaiting_approval' WHERE id=?", (sid,))
            self.emit(run['id'],'approval_requested',{'step_id':sid,'name':step['name']})
            while True:
                approval = self.db.one('SELECT status FROM steps WHERE id=?', (sid,))
                if approval and approval['status']=='completed': break
                if approval and approval['status']=='rejected': raise RuntimeError('Operação rejeitada pelo usuário.')
                try: await asyncio.wait_for(self.approvals[sid].wait(), timeout=1.2)
                except asyncio.TimeoutError: pass
                self.approvals[sid].clear()
            self.db.execute("UPDATE runs SET status='running' WHERE id=?", (run['id'],))
            self.emit(run['id'],'step_status',{'id':sid,'status':'completed'})
            return
        user = run['user_id']
        agent = self.db.one('SELECT * FROM agents WHERE id=? AND user_id=?', (step['agent_id'],user))
        if not agent: raise RuntimeError('Trabalhador não encontrado.')
        prev = self.db.all('SELECT name,output FROM steps WHERE run_id=? AND status=? AND output IS NOT NULL', (run['id'],'completed'))
        context = '\n\n'.join(f"{p['name']}:\n{p['output'][:2500]}" for p in prev)[:5500]
        messages = [{'role':'user','content':run['prompt'] + ('\n\nResultados anteriores:\n'+context if context else '')}]
        system = agent['instructions'] + '\nResponda em português. Indique limitações reais. Não declare ter usado ferramentas que não estão disponíveis.'
        if step['instructions']: system += '\nInstruções do fluxo: ' + step['instructions'][:2000]
        providers = self.db.all('SELECT * FROM providers WHERE user_id=? AND enabled=1 ORDER BY priority ASC,created_at ASC', (user,))
        if agent['provider_id']:
            providers.sort(key=lambda p: p['id'] != agent['provider_id'])
        if not providers:
            raise RuntimeError('Nenhum provedor configurado. Abra Provedores e adicione uma API válida.')
        failures = []
        agent_sem = self.agent_sems.setdefault(agent['id'], asyncio.Semaphore(agent['max_concurrency']))
        async with self.sem, agent_sem:
            for provider_index, provider in enumerate(providers):
                if provider_index > 0:
                    self.emit(run['id'],'step_reset',{'step_id':sid,'reason':'failover'})
                model = agent['model'] if provider['id']==agent['provider_id'] and agent['model'] else provider['model']
                if not model: continue
                key = (provider['id'],model)
                if self.circuit.get(key,0) > asyncio.get_running_loop().time(): continue
                if run['budget_limit'] is not None:
                    # Require explicitly configured estimates to avoid silently bypassing user budget.
                    if provider['input_price'] is None or provider['output_price'] is None:
                        failures.append('Preço/token não configurado; provedor bloqueado pelo orçamento.')
                        continue
                    estimated = ((len(run['prompt'])/4)/1_000_000*provider['input_price'] + (1400/1_000_000)*provider['output_price'])
                    current = self.db.one('SELECT total_cost FROM runs WHERE id=?', (run['id'],))['total_cost']
                    if current+estimated > run['budget_limit']:
                        failures.append('Orçamento insuficiente para a estimativa da requisição.')
                        continue
                for attempt in range(2):
                    self.db.execute('UPDATE steps SET attempts=attempts+1,provider_id=?,model=?,updated_at=? WHERE id=?',
                                    (provider['id'],model,utcnow(),sid))
                    self.emit(run['id'],'model_selected',{'step_id':sid,'provider':provider['name'],'model':model,'attempt':attempt+1})
                    parts = []
                    try:
                        async for token in self.client.stream(provider,self.security.decrypt(provider['api_key_enc']),model,system,messages):
                            parts.append(token)
                            self.emit(run['id'],'token',{'step_id':sid,'agent':agent['name'],'text':token})
                        output = ''.join(parts)
                        if not output.strip(): raise ProviderError('response','Resposta vazia.',True)
                        price = 0.0
                        if provider['input_price'] is not None and provider['output_price'] is not None:
                            # This is an estimate: streaming tokens usage varies by API. Not billed cost.
                            price = (len(messages[0]['content'])/4/1_000_000*provider['input_price']
                                + len(output)/4/1_000_000*provider['output_price'])
                        self.db.execute("UPDATE steps SET status='completed',output=?,error=NULL,updated_at=? WHERE id=?",(output,utcnow(),sid))
                        self.db.execute('UPDATE runs SET total_cost=total_cost+?,updated_at=? WHERE id=?', (price,utcnow(),run['id']))
                        self.emit(run['id'],'step_status',{'id':sid,'name':agent['name'],'status':'completed','provider':provider['name'],'model':model})
                        return
                    except ProviderError as e:
                        failures.append(f"{provider['name']}/{model}: {e.category}")
                        self.db.execute('UPDATE steps SET error=? WHERE id=?',(str(e),sid))
                        self.db.execute('UPDATE providers SET last_error=? WHERE id=?',(str(e),provider['id']))
                        self.emit(run['id'],'provider_error',{'step_id':sid,'provider':provider['name'],'category':e.category,'message':str(e)})
                        if e.category in ('authentication','credits'):
                            self.db.execute('UPDATE providers SET enabled=0 WHERE id=?',(provider['id'],))
                        if not e.retryable:
                            break
                        # Streaming already emitted: do not replay partial text without a clear recovery event.
                        if attempt==0:
                            self.emit(run['id'],'step_reset',{'step_id':sid,'reason':'retry'})
                            await asyncio.sleep(0.25+random.random()*0.15)
                        else: self.circuit[key] = asyncio.get_running_loop().time()+30
                    except Exception as e:
                        failures.append(f"{provider['name']}/{model}: internal error")
                        self.emit(run['id'],'provider_error',{'step_id':sid,'provider':provider['name'],'category':'internal','message':str(e)[:120]})
                        break
                self.emit(run['id'],'failover',{'step_id':sid,'failed_provider':provider['name'],'message':'Tentando próximo modelo compatível.'})
        self.db.execute("UPDATE steps SET status='failed',error=?,updated_at=? WHERE id=?",('; '.join(failures)[:400],utcnow(),sid))
        raise RuntimeError('Não foi possível concluir ' + agent['name'] + ': ' + '; '.join(failures)[:220])

    def resume_run(self, run_id):
        run = self.db.one('SELECT status FROM runs WHERE id=?', (run_id,))
        if not run or run['status'] not in ('failed', 'cancelled'):
            raise ValueError('Somente execuções interrompidas podem ser retomadas.')
        # Preserve completed checkpoints and rerun only incomplete nodes.
        self.db.execute("UPDATE steps SET status='queued',error=NULL WHERE run_id=? AND status IN ('failed','running','queued','rejected','awaiting_approval')", (run_id,))
        self.db.execute("UPDATE runs SET status='queued',error=NULL,updated_at=? WHERE id=?", (utcnow(),run_id))
        self.emit(run_id,'run_resumed',{'message':'Etapas concluídas foram preservadas.'})
        self.schedule(run_id)

    def approve(self, run_id, step_id, approved):
        self.db.execute("UPDATE steps SET status=?,output=?,updated_at=? WHERE id=? AND run_id=? AND status='awaiting_approval'",
                        ('completed' if approved else 'rejected','Aprovado' if approved else 'Rejeitado',utcnow(),step_id,run_id))
        self.emit(run_id,'approval_decision',{'step_id':step_id,'approved':approved})
        self.approvals[step_id].set()

    def cancel(self, run_id):
        t = self.running.get(run_id)
        if t and not t.done(): t.cancel()
        else:
            self.db.execute("UPDATE runs SET status='cancelled',updated_at=? WHERE id=?",(utcnow(),run_id))
            self.emit(run_id,'run_status',{'status':'cancelled'})
