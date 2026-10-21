"""Local design skill + strictly scoped, logged package tooling. No arbitrary shell."""
import asyncio
import json
import os
import re
import shutil
import subprocess
from .database import uid, utcnow
from .workspace import WorkspaceError, is_link_or_junction

SKILLS = {'ux-ui-studio-pro': {
 'id':'ux-ui-studio-pro','name':'UI/UX Studio Pro',
 'description':'Design systems, layouts responsivos, componentes, acessibilidade e animações.',
 'tools':['Tailwind CSS 4','shadcn/ui (guia)','Lucide React','Motion','Playwright (guia)'],
 'docs':['https://tailwindcss.com/docs/installation/using-vite',
         'https://ui.shadcn.com/docs/installation/vite',
         'https://motion.dev/docs/react-installation','https://playwright.dev/docs/intro']
}}
NPM = {'tailwindcss':'tailwindcss@^4','@tailwindcss/vite':'@tailwindcss/vite@^4',
       'lucide-react':'lucide-react','motion':'motion','clsx':'clsx',
       'tailwind-merge':'tailwind-merge','class-variance-authority':'class-variance-authority',
       '@radix-ui/react-slot':'@radix-ui/react-slot',
       '@radix-ui/react-dialog':'@radix-ui/react-dialog',
       '@radix-ui/react-dropdown-menu':'@radix-ui/react-dropdown-menu',
       '@playwright/test':'@playwright/test'}
PIP = {'pytest':'pytest','httpx':'httpx','sqlalchemy':'SQLAlchemy',
       'python-multipart':'python-multipart','pydantic':'pydantic'}
# Strict top-level explicit user authorization. No indirect grant by a model.
GRANT = re.compile(r'^\s*autorizo\s+o\s+arquiteto(?:\s+ia)?\s+a\s+'
                   r'(?:revisar\s+e\s+)?aprovar\s+altera[cç][oõ]es\s+e\s+'
                   r'instalar\s+pacotes\s+permitidos(?:\s+neste\s+projeto)?[.!]?\s*$',re.I)
REVOKE = re.compile(r'^\s*revogo\s+a\s+autonomia\s+do\s+arquiteto(?:\s+ia)?[.!]?\s*$',re.I)
FENCE = chr(96)*3
BLOCK = re.compile(re.escape(FENCE)+r'central-packages\s*\n(.*?)\n'+re.escape(FENCE),re.I|re.S)

class SkillsHub:
    def __init__(self,db,workspaces):
        self.db=db;self.workspaces=workspaces

    def catalog(self,user_id,project_id=None):
        enabled=set()
        if project_id:
            enabled={r['skill_id'] for r in self.db.all(
                'SELECT skill_id FROM project_skills WHERE project_id=? AND user_id=? AND enabled=1',
                (project_id,user_id))}
        return [dict(x,enabled=x['id'] in enabled) for x in SKILLS.values()]

    def enable(self,user_id,project_id,skill_id,enabled):
        if skill_id not in SKILLS: raise WorkspaceError('Skill inexistente.',404)
        if not self.db.one('SELECT id FROM projects WHERE id=? AND user_id=?',(project_id,user_id)):
            raise WorkspaceError('Projeto não encontrado.',404)
        self.db.execute('''INSERT INTO project_skills(user_id,project_id,skill_id,enabled,updated_at)
          VALUES(?,?,?,?,?) ON CONFLICT(project_id,skill_id) DO UPDATE
          SET enabled=excluded.enabled,updated_at=excluded.updated_at''',
          (user_id,project_id,skill_id,int(enabled),utcnow()))
        return {'id':skill_id,'enabled':enabled}

    @staticmethod
    def explicitly_requested(prompt):
        """Only affirmative, user-authored requests to USE this named local skill."""
        text=prompt.casefold()
        if re.search(r'\b(n[aã]o|sem)\s+(?:utilizar|usar|ativar)\b',text):
            return False
        return bool(re.search(
            r'\b(?:utilize|utilizando|utilizar|use|usar|ative|ativar)\b'
            r'.{0,55}\bskill\s+ui\s*/\s*ux\s+studio\s+pro\b',text,re.S))

    def guide(self,user_id,conversation_id,specialty):
        if specialty not in ('frontend','design','architecture','code','review'):return ''
        r=self.db.one('''SELECT s.enabled FROM project_skills s JOIN conversations c
          ON c.project_id=s.project_id AND c.user_id=s.user_id
          WHERE c.id=? AND c.user_id=? AND s.skill_id=?''',
          (conversation_id,user_id,'ux-ui-studio-pro'))
        if not r or not r['enabled']:return ''
        return (
          '\nSKILL UI/UX STUDIO PRO: Planeje e implemente UX/UI profissional. '
          'Para e-commerce: hero elegante, navegação e busca, categorias, card de produto, '
          'filtros, carrinho visual, checkout acessível, foco, estados vazios, loading e erros. '
          'Use contraste WCAG AA, responsividade mobile-first, espaçamentos coerentes, '
          'tipografia fluida e reduced-motion. Preserve a API, sem dependências fictícias. '
          'Stack opcional: Tailwind CSS 4 (Vite plugin @tailwindcss/vite e CSS @import tailwindcss), '
          'shadcn/ui (guia, NÃO CLI executável), Lucide React, Motion via motion/react, '
          'Playwright para testes (não alegar screenshots não feitos). '
          'Não invente que a instalação do pacote foi executada; só foi se o executor confirmar. '
          'Arquiteto autorizado pode solicitar pacotes usando um bloco JSON '
          +FENCE+'central-packages\n{"manager":"npm","packages":["lucide-react","motion"]}\n'+FENCE+
          '. NPM permitido: '+', '.join(NPM)+'. PIP permitido: '+', '.join(PIP)+'. '
          'Nenhum comando arbitrário, script de instalação, CLI shadcn ou navegador é permitido.'
        )

    def delegation(self,user_id,conversation_id):
        r=self.db.one('''SELECT d.* FROM architect_delegations d JOIN conversations c
           ON c.id=d.conversation_id AND c.user_id=d.user_id
           WHERE d.user_id=? AND d.conversation_id=?''',(user_id,conversation_id))
        return {'enabled':bool(r and r['enabled']),
                'project_id':r['project_id'] if r else None}

    def set_delegation(self,user_id,conversation_id,enabled):
        r=self.db.one('''SELECT c.project_id FROM conversations c
            JOIN projects p ON p.id=c.project_id AND p.user_id=c.user_id
            WHERE c.id=? AND c.user_id=?''',(conversation_id,user_id))
        if not r:raise WorkspaceError('A conversa precisa estar vinculada a um projeto.',422)
        self.workspaces._folder(user_id,r['project_id'])
        self.db.execute('''INSERT INTO architect_delegations
         (conversation_id,project_id,user_id,enabled,updated_at)
         VALUES(?,?,?,?,?) ON CONFLICT(conversation_id)
         DO UPDATE SET enabled=excluded.enabled,updated_at=excluded.updated_at''',
         (conversation_id,r['project_id'],user_id,int(enabled),utcnow()))
        return self.delegation(user_id,conversation_id)

    def instruction(self,user_id,conversation_id,text):
        if '\n' in text.strip() or 'não autorizo' in text.lower() or FENCE in text:
            return None
        if REVOKE.fullmatch(text.strip()):
            return self.set_delegation(user_id,conversation_id,False)
        if GRANT.fullmatch(text.strip()):
            return self.set_delegation(user_id,conversation_id,True)
        return None

    @staticmethod
    def manifest(text):
        blocks=BLOCK.findall(text or '')
        if not blocks:return None
        if len(blocks)!=1:raise WorkspaceError('Apenas um bloco de pacotes por etapa.')
        try:data=json.loads(blocks[0])
        except json.JSONDecodeError:raise WorkspaceError('JSON de pacotes inválido.')
        if not isinstance(data,dict) or set(data)!={'manager','packages'}:
            raise WorkspaceError('Manifesto de pacotes inválido.')
        m=data['manager'];packages=data['packages']
        allowed=NPM if m=='npm' else PIP if m=='pip' else None
        if not allowed or not isinstance(packages,list) or not 1<=len(packages)<=5:
            raise WorkspaceError('Gerenciador ou quantidade de pacotes inválida.')
        if any(not isinstance(p,str) or p not in allowed for p in packages) or len(set(packages))!=len(packages):
            raise WorkspaceError('Pacote não autorizado ou duplicado.')
        return m,packages

    def _install_sync(self,user_id,project_id,manager,packages):
        folder=self.workspaces._folder(user_id,project_id)
        target=folder/('frontend' if manager=='npm' else 'backend')
        if not target.is_dir() or any(is_link_or_junction(p) for p in (folder,target)):
            raise WorkspaceError('Diretório de dependências inexistente ou inseguro.')
        if manager=='npm':
            manifest=target/'package.json'
            if is_link_or_junction(manifest) or not manifest.is_file() or manifest.stat().st_size>160000:
                raise WorkspaceError('package.json ausente/inseguro.')
            if not isinstance(json.loads(manifest.read_text(encoding='utf-8')),dict):
                raise WorkspaceError('package.json inválido.')
            # npm writes lockfiles and node_modules; none may redirect outside the root.
            for item in (manifest,target/'package-lock.json',target/'node_modules',
                         target/'npm-shrinkwrap.json',target/'.npmrc'):
                if is_link_or_junction(item):
                    raise WorkspaceError('npm encontrou arquivo ou diretório vinculado a outra pasta.',403)
                if item.is_file() and item.stat().st_nlink>1:
                    raise WorkspaceError('Arquivos com hardlink não podem ser alterados pelo npm.',403)
            exe=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
            if not exe:raise WorkspaceError('npm não encontrado no PATH.',503)
            cmd=[exe,'install','--ignore-scripts','--no-audit','--no-fund',
                 '--registry=https://registry.npmjs.org',*[NPM[p] for p in packages]]
            env=os.environ.copy();env['npm_config_ignore_scripts']='true'
        else:
            venv=target/'.venv'
            if is_link_or_junction(venv):raise WorkspaceError('venv com link não permitido.')
            python=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            if not python.is_file():raise WorkspaceError('Crie backend/.venv antes de instalar pacotes.')
            cmd=[str(python),'-m','pip','install','--no-input','--disable-pip-version-check',
                 '--only-binary=:all:','--index-url','https://pypi.org/simple',*[PIP[p] for p in packages]]
            env=os.environ.copy();env['PIP_NO_INPUT']='1'
        result=subprocess.run(cmd,cwd=str(target),env=env,stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,text=True,timeout=150,
                              check=False,shell=False)
        return {'ok':result.returncode==0,'manager':manager,'packages':packages,
                'exit_code':result.returncode,'output':result.stdout[-1800:]}

    async def install_for_run(self,run):
        grant=self.delegation(run['user_id'],run['conversation_id'])
        if not grant['enabled']:return []
        steps=self.db.all('''SELECT s.output,a.specialty FROM steps s JOIN agents a ON a.id=s.agent_id
                              WHERE s.run_id=? AND s.status='completed' ''',(run['id'],))
        results=[]
        for step in steps:
            if step['specialty']!='architecture':continue
            try:manifest=self.manifest(step['output'])
            except WorkspaceError as exc:
                results.append({'ok':False,'error':str(exc)});continue
            if not manifest:continue
            manager,packages=manifest
            if not self.delegation(run['user_id'],run['conversation_id'])['enabled']:break
            job=uid()
            self.db.execute('''INSERT INTO architect_package_installs
              (id,user_id,project_id,run_id,manager,packages,status,created_at)
              VALUES(?,?,?,?,?,?,?,?)''',
              (job,run['user_id'],grant['project_id'],run['id'],manager,json.dumps(packages),'running',utcnow()))
            try:result=await asyncio.to_thread(self._install_sync,run['user_id'],grant['project_id'],manager,packages)
            except (WorkspaceError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
                result={'ok':False,'error':str(exc)[:250],'manager':manager,'packages':packages}
            self.db.execute('''UPDATE architect_package_installs SET status=?,details=?,finished_at=?
                 WHERE id=?''',('completed' if result['ok'] else 'failed',
                   json.dumps(result,ensure_ascii=False),utcnow(),job))
            results.append(result)
            break
        return results

    def installs(self,user_id,project_id):
        return self.db.all('''SELECT id,manager,packages,status,details,created_at,finished_at
            FROM architect_package_installs WHERE user_id=? AND project_id=?
            ORDER BY created_at DESC LIMIT 30''',(user_id,project_id))
