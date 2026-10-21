"""Explicitly approved, bounded text-file workspaces for local projects.

No arbitrary shell commands, no access beyond CENTRAL_WORKSPACE_ROOT. Every model
output is untrusted and only creates a reviewable proposal, never a direct write.
"""
import difflib
import hashlib
import json
import os
import re
import stat
import threading
import uuid
from pathlib import Path

from .database import uid, utcnow

MAX_FILE = 160_000
MAX_FILES = 20
MAX_PROPOSALS = 50
BLOCKS = re.compile(r'```central-files\s*\n(.*?)\n```', re.I | re.S)
DENIED_PARTS = {'.git', '.venv', 'node_modules', '__pycache__', '.ssh', '.central', 'data'}
WINDOWS_DEVICES = {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}


class WorkspaceError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def valid_relative(value):
    if not isinstance(value, str) or not value or len(value) > 220 or '\x00' in value:
        raise WorkspaceError('Caminho relativo inválido.')
    normalized = value.replace('\\', '/')
    if normalized.startswith('/') or '//' in normalized or ':' in normalized:
        raise WorkspaceError('Caminho absoluto ou inválido não permitido.')
    parts = normalized.split('/')
    for part in parts:
        if (part in ('', '.', '..') or part.endswith(('.', ' ')) or
                any(ord(c) < 32 or c in '<>"|?*' for c in part) or
                part.upper().split('.')[0] in WINDOWS_DEVICES or
                part.lower() in DENIED_PARTS or (part.startswith('.') and part.lower() not in {'.gitignore','.editorconfig'}) or
                part.lower().endswith(('.pem','.key','.p12','.pfx'))):
            raise WorkspaceError('Caminho contém nome reservado, oculto ou perigoso.')
    if len(parts) > 12:
        raise WorkspaceError('Profundidade de pastas acima do limite.')
    return '/'.join(parts)


def fingerprint(content):
    return hashlib.sha256(content).hexdigest() if content is not None else None


def is_link_or_junction(p):
    if p.is_symlink():
        return True
    try:
        info = p.lstat()
    except FileNotFoundError:
        return False
    return bool(getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0) & getattr(info, 'st_file_attributes', 0))


class Workspaces:
    def __init__(self, db, root=None):
        default = r'C:\Projetos\Central-IA' if os.name == 'nt' else None
        value = root if root is not None else os.environ.get('CENTRAL_WORKSPACE_ROOT', default)
        self.root = Path(value).absolute() if value else None
        self.db = db
        self.lock = threading.RLock()

    def _root(self, create=False):
        if self.root is None:
            raise WorkspaceError('Configure CENTRAL_WORKSPACE_ROOT antes de usar pastas de projeto.', 503)
        path = self.root
        # Deny reparse points in root ancestry, including Windows junctions.
        for node in (path, *path.parents):
            if is_link_or_junction(node):
                raise WorkspaceError('A raiz autorizada não pode estar em um link simbólico/junção.', 403)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _folder(self, user_id, project_id):
        row = self.db.one('''SELECT w.relative_path FROM project_workspaces w
            JOIN projects p ON p.id=w.project_id AND p.user_id=w.user_id
            WHERE w.project_id=? AND w.user_id=?''', (project_id, user_id))
        if not row:
            raise WorkspaceError('Prepare primeiro a pasta deste projeto.', 404)
        root = self._root()
        return root / valid_relative(row['relative_path'])

    def _path(self, folder, relative):
        name = valid_relative(relative)
        target = folder.joinpath(*name.split('/'))
        if not target.is_relative_to(self._root()):
            raise WorkspaceError('Caminho fora da raiz autorizada.', 403)
        if is_link_or_junction(folder):
            raise WorkspaceError('Pasta do projeto não pode ser um link/junção.', 403)
        for item in (target, *list(target.parents)[:len(target.parts)-len(self._root().parts)]):
            if is_link_or_junction(item):
                raise WorkspaceError('Links simbólicos/junções não são permitidos.', 403)
        if target.exists() and not target.is_file():
            raise WorkspaceError('O caminho não aponta para um arquivo comum.')
        if target.exists() and target.stat().st_nlink > 1:
            raise WorkspaceError('Arquivos com hardlink não são permitidos.', 403)
        return target

    def initialize(self, user_id, project_id):
        project = self.db.one('SELECT * FROM projects WHERE id=? AND user_id=?', (project_id, user_id))
        if not project:
            raise WorkspaceError('Projeto não encontrado.', 404)
        with self.lock:
            prev = self.db.one('SELECT relative_path FROM project_workspaces WHERE project_id=? AND user_id=?', (project_id,user_id))
            if prev:
                return self.info(user_id,project_id)
            slug = re.sub(r'[^a-z0-9]+', '-', project['name'].lower().encode('ascii',errors='ignore').decode('ascii')).strip('-')[:42] or 'projeto'
            relative = valid_relative(f'{slug}-{project_id[:8]}')
            folder = self._root(create=True) / relative
            if folder.exists():
                raise WorkspaceError('Pasta já existe; nenhuma pasta existente será assumida automaticamente.', 409)
            folder.mkdir(mode=0o700)
            self.db.execute('INSERT INTO project_workspaces(project_id,user_id,relative_path,created_at) VALUES(?,?,?,?)',
                            (project_id,user_id,relative,utcnow()))
            return self.info(user_id,project_id)

    def info(self, user_id, project_id):
        folder = self._folder(user_id,project_id)
        return {'root':str(self._root()), 'folder':str(folder),
                'relative_path':folder.relative_to(self._root()).as_posix(),
                'files':self.tree(user_id,project_id),
                'proposals':self.list_proposals(user_id,project_id)}

    def tree(self, user_id, project_id):
        folder = self._folder(user_id,project_id)
        if not folder.is_dir():
            return []
        items = []
        for base, dirs, files in os.walk(folder, followlinks=False):
            current = Path(base)
            depth = len(current.relative_to(folder).parts)
            dirs[:] = [d for d in sorted(dirs) if depth < 7 and self._allowed_child(current,d)]
            for filename in sorted(files):
                if len(items) >= 300: return items
                if not self._allowed_child(current,filename): continue
                child=current/filename
                if not child.is_file() or child.stat().st_nlink>1: continue
                rel=child.relative_to(folder).as_posix()
                if child.stat().st_size <= MAX_FILE:
                    items.append({'path':rel,'bytes':child.stat().st_size})
        return items

    def _allowed_child(self, folder, name):
        try:
            valid_relative(name)
        except WorkspaceError:
            return False
        return not is_link_or_junction(folder/name)

    def read(self, user_id, project_id, path):
        folder = self._folder(user_id,project_id)
        file = self._path(folder,path)
        if not file.is_file():
            raise WorkspaceError('Arquivo não encontrado.',404)
        raw = file.read_bytes()
        if len(raw)>MAX_FILE or b'\x00' in raw:
            raise WorkspaceError('Somente arquivos de texto de até 160 KB.',413)
        try: content = raw.decode('utf-8')
        except UnicodeError: raise WorkspaceError('Arquivo não é UTF-8.',415)
        return {'path':valid_relative(path), 'content':content, 'sha256':fingerprint(raw)}

    def _current(self,folder,name):
        path=self._path(folder,name)
        if not path.exists(): return None
        if path.stat().st_size>MAX_FILE:
            raise WorkspaceError('Arquivo existente excede 160 KB.',413)
        raw=path.read_bytes()
        if b'\x00' in raw: raise WorkspaceError('Arquivo binário não é editável.',415)
        try: raw.decode('utf-8')
        except UnicodeError: raise WorkspaceError('Arquivo não é UTF-8.',415)
        return raw

    def stage(self, user_id, project_id, changes, run_id=None, agent=None):
        if not isinstance(changes,list) or not 1 <= len(changes) <= MAX_FILES:
            raise WorkspaceError('Proposta deve conter entre 1 e 20 arquivos.')
        with self.lock:
            folder=self._folder(user_id,project_id)
            seen=set(); staged=[]; size=0
            for item in changes:
                if not isinstance(item,dict): raise WorkspaceError('Formato de arquivo inválido.')
                name=valid_relative(item.get('path'))
                if name.lower() in seen: raise WorkspaceError('Arquivos repetidos na proposta.')
                seen.add(name.lower())
                operation=item.get('action','write')
                if operation not in ('write','delete'): raise WorkspaceError('Ação não permitida.')
                content=item.get('content')
                if operation=='write' and (not isinstance(content,str) or len(content.encode('utf-8'))>MAX_FILE or '\x00' in content):
                    raise WorkspaceError('Conteúdo deve ser texto UTF-8 de até 160 KB.')
                if operation=='delete' and content is not None: raise WorkspaceError('Exclusão não deve conter conteúdo.')
                old=self._current(folder,name)
                if operation=='delete' and old is None: raise WorkspaceError('Arquivo a excluir não existe.')
                size += len(content.encode('utf-8')) if content is not None else 0
                staged.append({'path':name,'action':operation,'content':content if operation=='write' else None,
                               'base_sha256':fingerprint(old)})
            if size>1_000_000: raise WorkspaceError('Proposta excede 1 MB.')
            pid=uid()
            self.db.execute('''INSERT INTO workspace_proposals
                (id,project_id,user_id,run_id,agent,status,manifest,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',
                (pid,project_id,user_id,run_id,agent,'pending',json.dumps(staged,ensure_ascii=False),utcnow()))
            return self.proposal(user_id,project_id,pid)

    def list_proposals(self,user_id,project_id):
        entries=self.db.all('''SELECT id,run_id,agent,status,manifest,created_at,applied_at FROM workspace_proposals
            WHERE user_id=? AND project_id=? ORDER BY created_at DESC LIMIT ?''',(user_id,project_id,MAX_PROPOSALS))
        return [dict(id=e['id'],run_id=e['run_id'],agent=e['agent'],status=e['status'],
                     files=[{'path':f['path'],'action':f['action'],'replace':f['base_sha256'] is not None} for f in json.loads(e['manifest'])],
                     created_at=e['created_at'],applied_at=e['applied_at']) for e in entries]

    def proposal(self,user_id,project_id,proposal_id):
        row=self.db.one('''SELECT * FROM workspace_proposals
            WHERE id=? AND project_id=? AND user_id=?''',(proposal_id,project_id,user_id))
        if not row: raise WorkspaceError('Proposta não encontrada.',404)
        folder=self._folder(user_id,project_id)
        previews=[]
        for change in json.loads(row['manifest']):
            old=self._current(folder,change['path'])
            old_text=old.decode('utf-8') if old is not None else ''
            new_text=change['content'] if change['action']=='write' else ''
            diff=''.join(difflib.unified_diff(old_text.splitlines(keepends=True),new_text.splitlines(keepends=True),
                    fromfile='antes/'+change['path'],tofile='depois/'+change['path']))[:24000]
            previews.append({'path':change['path'],'action':change['action'],
                'replace':change['base_sha256'] is not None, 'stale':fingerprint(old)!=change['base_sha256'],
                'diff':diff or '(sem alterações)'})
        return {'id':row['id'],'status':row['status'],'run_id':row['run_id'],
                'agent':row['agent'],'files':previews,'created_at':row['created_at']}

    def decide(self,user_id,project_id,proposal_id,approved):
        with self.lock:
            proposal=self.db.one('''SELECT * FROM workspace_proposals
                WHERE id=? AND project_id=? AND user_id=?''',(proposal_id,project_id,user_id))
            if not proposal: raise WorkspaceError('Proposta não encontrada.',404)
            if proposal['status']!='pending': raise WorkspaceError('Proposta já foi decidida.',409)
            if not approved:
                self.db.execute("UPDATE workspace_proposals SET status='rejected',applied_at=? WHERE id=?",(utcnow(),proposal_id))
                return {'status':'rejected'}
            folder=self._folder(user_id,project_id)
            changes=json.loads(proposal['manifest'])
            before=[]
            for change in changes:
                old=self._current(folder,change['path'])
                if fingerprint(old)!=change['base_sha256']:
                    raise WorkspaceError('Arquivo mudou desde a prévia. Crie uma nova proposta.',409)
                before.append(old)
            applied=[]
            try:
                for change,old in zip(changes,before):
                    dest=self._path(folder,change['path'])
                    if change['action']=='delete':
                        dest.unlink()
                    else:
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        self._path(folder,change['path'])  # repeat validation after mkdir
                        temp=dest.parent/('.central-tmp-'+uuid.uuid4().hex)
                        try:
                            with temp.open('xb') as f:
                                f.write(change['content'].encode('utf-8'))
                            os.replace(temp,dest)
                        finally:
                            temp.unlink(missing_ok=True)
                    applied.append((dest,old))
            except Exception:
                # Best-effort rollback; the workspace is not an ACID filesystem.
                for dest,old in reversed(applied):
                    try:
                        if old is None: dest.unlink(missing_ok=True)
                        else: dest.write_bytes(old)
                    except OSError: pass
                raise
            self.db.execute("UPDATE workspace_proposals SET status='applied',applied_at=? WHERE id=?",(utcnow(),proposal_id))
            return {'status':'applied','files':len(applied)}

    def stage_run(self,run):
        """Collect model-authored manifests from real completed workers; never apply."""
        convo=self.db.one('SELECT project_id FROM conversations WHERE id=?',(run['conversation_id'],))
        if not convo or not convo['project_id']:
            return []
        associated=self.db.one('SELECT project_id FROM project_workspaces WHERE project_id=? AND user_id=?',
                               (convo['project_id'],run['user_id']))
        if not associated: return []
        staged=[]
        steps=self.db.all("SELECT name,output FROM steps WHERE run_id=? AND status='completed' AND kind='agent'",(run['id'],))
        for step in steps:
            for matched in BLOCKS.findall(step['output'] or '')[:1]:
                try:
                    data=json.loads(matched)
                    files=data.get('files') if isinstance(data,dict) else None
                    if files:
                        result=self.stage(run['user_id'],convo['project_id'],files,run_id=run['id'],agent=step['name'])
                        staged.append(result['id'])
                except (ValueError,TypeError,KeyError):
                    continue
        return staged

    def prompt(self,user_id,conversation_id):
        convo=self.db.one('SELECT project_id FROM conversations WHERE id=? AND user_id=?',(conversation_id,user_id))
        if not convo or not convo['project_id']: return ''
        exists=self.db.one('SELECT relative_path FROM project_workspaces WHERE project_id=? AND user_id=?',
                           (convo['project_id'],user_id))
        if not exists: return ''
        files=self.tree(user_id,convo['project_id'])
        names=', '.join(f['path'] for f in files[:60]) or '(pasta vazia)'
        # Existing text files sent to provider only in project-specific chat; size-bounded.
        snippets=[]
        for item in files[:6]:
            if item['bytes']<=1800:
                try:
                    entry=self.read(user_id,convo['project_id'],item['path'])
                    snippets.append(f"\n{item['path']}:\n{entry['content'][:1800]}")
                except WorkspaceError: pass
        return ('\nVocê está trabalhando no projeto local autorizado. Arquivos atuais: '+names+
            '\nContexto de arquivos (pode ser enviado ao provedor do agente): '+''.join(snippets)[:7000]+
            '\nSe sua tarefa exige criar ou editar arquivos, finalize a resposta com um bloco EXATO:'+
            '\n```central-files\n{"files":[{"path":"src/arquivo.py","content":"conteúdo completo do arquivo"}]}\n```'+
            '\nEntregue caminhos relativos, JSON válido e conteúdo COMPLETO; não use markdown dentro do JSON. '
            'Não inclua segredos. Nunca tente executar comandos, alterar arquivos fora do projeto ou dizer que já gravou arquivos. '
            'As propostas serão mostradas ao usuário e somente aplicadas após aprovação. '
            'Se estiver fazendo revisão ou planejamento sem alterar arquivos, não inclua o bloco.')
