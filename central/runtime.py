"""Explicitly authorized local development preview for React/Vite + FastAPI.

No arbitrary shell, npm scripts, npx, pip installation or model-requested command
execution. Fixed localhost ports. Processes live only until stopped or Central exits.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

from .database import utcnow
from .workspace import WorkspaceError, is_link_or_junction


class RuntimeManager:
    FRONT_PORT = 5173
    BACK_PORT = 8000

    def __init__(self, db, workspaces):
        self.db = db
        self.workspaces = workspaces
        self.lock = threading.RLock()
        self.sessions = {}

    def _conversation(self,user_id,conversation_id):
        row = self.db.one('''SELECT c.project_id FROM conversations c
             JOIN projects p ON p.id=c.project_id AND p.user_id=c.user_id
             WHERE c.id=? AND c.user_id=?''',(conversation_id,user_id))
        if not row or not row['project_id']:
            raise WorkspaceError('Selecione um projeto válido nesta conversa.',422)
        return row['project_id']

    def access(self,user_id,conversation_id):
        project_id=self._conversation(user_id,conversation_id)
        row=self.db.one('''SELECT enabled FROM runtime_permissions WHERE conversation_id=?
                            AND user_id=? AND project_id=?''',
                        (conversation_id,user_id,project_id))
        return {'project_id':project_id,'enabled':bool(row and row['enabled'])}

    def authorize(self,user_id,conversation_id,enabled):
        project_id=self._conversation(user_id,conversation_id)
        self.workspaces._folder(user_id,project_id)
        self.db.execute('''INSERT INTO runtime_permissions(conversation_id,user_id,project_id,
                          enabled,updated_at) VALUES(?,?,?,?,?)
                          ON CONFLICT(conversation_id) DO UPDATE SET
                          project_id=excluded.project_id,enabled=excluded.enabled,
                          updated_at=excluded.updated_at''',
                          (conversation_id,user_id,project_id,int(enabled),utcnow()))
        return self.access(user_id,conversation_id)

    @staticmethod
    def _safe_location(folder,path,kind='file'):
        # Refuse symlink/junction traversal and hardlinked executables/configs.
        if not path.is_relative_to(folder):
            raise WorkspaceError('Execução fora da pasta autorizada.',403)
        for entry in [path,*list(path.parents)[:len(path.parts)-len(folder.parts)+1]]:
            if is_link_or_junction(entry):
                raise WorkspaceError('Link simbólico/junção bloqueado no projeto.',403)
        if kind=='file' and (not path.is_file() or path.stat().st_nlink>1):
            raise WorkspaceError('Arquivo de execução ausente ou inseguro.',422)
        if kind=='dir' and not path.is_dir():
            raise WorkspaceError('Diretório do projeto ausente.',422)
        return path

    @staticmethod
    def _available(port):
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
            return sock.connect_ex(('127.0.0.1',port)) != 0

    def _commands(self,folder):
        front=self._safe_location(folder,folder/'frontend','dir')
        back=self._safe_location(folder,folder/'backend','dir')
        package=self._safe_location(folder,front/'package.json')
        self._safe_location(folder,front/'node_modules','dir')
        vite=self._safe_location(folder,front/'node_modules/vite/bin/vite.js')
        try:
            config=json.loads(package.read_text(encoding='utf-8'))
        except (ValueError,OSError):
            raise WorkspaceError('frontend/package.json inválido.',422)
        if not isinstance(config,dict):
            raise WorkspaceError('frontend/package.json inválido.',422)
        node=shutil.which('node.exe' if os.name=='nt' else 'node')
        if not node:raise WorkspaceError('Node.js não instalado ou não encontrado no PATH.',422)
        python=back/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        # Python virtualenvs commonly symlink their interpreter on POSIX.
        # The sandbox root and backend/.venv themselves must not be linked.
        self._safe_location(folder,back/'.venv','dir')
        if not python.is_file():
            raise WorkspaceError('Ambiente Python não encontrado em backend/.venv.',422)
        if os.name=='nt':
            self._safe_location(folder,python)
        self._safe_location(folder,back/'main.py')
        return [
            ('backend',[str(python),'-m','uvicorn','main:app','--host','127.0.0.1',
                        '--port',str(self.BACK_PORT)],back),
            ('frontend',[node,str(vite),'--host','127.0.0.1','--port',
                         str(self.FRONT_PORT),'--strictPort'],front)
        ]

    def _check_session(self,key):
        current=self.sessions.get(key)
        if not current:return None
        if any(proc.poll() is not None for proc in current.values()):
            self._terminate(current)
            self.sessions.pop(key,None)
            return None
        return current

    @staticmethod
    def _terminate(processes):
        for proc in processes.values():
            if proc.poll() is None:
                try:proc.terminate()
                except OSError:pass
        for proc in processes.values():
            if proc.poll() is None:
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:proc.kill()
                    except OSError:pass

    def status(self,user_id,conversation_id):
        project_id=self._conversation(user_id,conversation_id)
        permission=self.access(user_id,conversation_id)
        with self.lock:
            current=self._check_session((user_id,project_id))
            return {
                'project_id':project_id,
                'authorized':permission['enabled'],
                'running':bool(current),
                'frontend_url':f'http://127.0.0.1:{self.FRONT_PORT}/' if current else None,
                'backend_docs_url':f'http://127.0.0.1:{self.BACK_PORT}/docs' if current else None,
                'message':'Executando localmente.' if current else 'Projeto não iniciado pela Central.'
            }

    def start(self,user_id,conversation_id):
        permission=self.access(user_id,conversation_id)
        if not permission['enabled']:
            raise WorkspaceError('Autorize a execução local nesta conversa antes de iniciar.',403)
        key=(user_id,permission['project_id'])
        with self.lock:
            current=self._check_session(key)
            if current:return self.status(user_id,conversation_id)
            if self.sessions:
                raise WorkspaceError('Outro projeto já está em execução pela Central. Pare-o antes.',409)
            folder=self.workspaces._folder(user_id,permission['project_id'])
            if is_link_or_junction(folder) or not folder.is_dir():
                raise WorkspaceError('Pasta de projeto inexistente ou insegura.',403)
            commands=self._commands(folder)
            if not self._available(self.FRONT_PORT) or not self._available(self.BACK_PORT):
                raise WorkspaceError('A porta 5173 ou 8000 já está em uso. Pare os servidores manuais antes de iniciar pela Central.',409)
            processes={}
            try:
                for kind,argv,cwd in commands:
                    processes[kind]=subprocess.Popen(
                        argv,cwd=str(cwd),shell=False,
                        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0))
                self.sessions[key]=processes
            except (OSError,ValueError) as exc:
                self._terminate(processes)
                raise WorkspaceError('Não foi possível iniciar os servidores locais: '+str(exc)[:170],422)
            return self.status(user_id,conversation_id)

    def stop(self,user_id,conversation_id):
        project_id=self._conversation(user_id,conversation_id)
        with self.lock:
            procs=self.sessions.pop((user_id,project_id),None)
            if procs:self._terminate(procs)
        return self.status(user_id,conversation_id)

    def shutdown(self):
        with self.lock:
            for processes in self.sessions.values():
                self._terminate(processes)
            self.sessions.clear()
