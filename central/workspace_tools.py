"""Audited workspace tools for autonomous *local* workers.

No generic shell, no arbitrary executables, no absolute paths, no deletions.
The granted folder is the only execution root. Every action is re-authorized.
"""
import asyncio
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from .computer_access import allowed_folder, policy, scoped_path, RESTRICTED_NAMES
from .database import uid, utcnow
from .workspace_guard import enforce_run_scope, enforce_host_command_policy
from .sandbox_executor import backend as command_backend, sandbox_argv, force_remove
from .approval_engine import issue_approval, decide
from .dependency_egress import Lease, mode as dependency_network, INSTALL_COMMANDS, docker_environment

_process_lock = threading.RLock()
_active_commands = {}
_active_containers = {}
_preparing_runs = set()
_cancelled_command_runs = set()
# Bound concurrent subprocesses per *server process*. Worker mode on a separate
# process has a separate pool; this is not a machine-wide sandbox quota.
_command_slots = threading.BoundedSemaphore(2)


def reset_run_commands(run_id):
    with _process_lock:
        _cancelled_command_runs.discard(run_id)


def _kill_tree(process):
    if process.poll() is not None:
        return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=5, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def stop_run_commands(run_id):
    """Stop only a process launched by this run; never affect unrelated Windows apps."""
    with _process_lock:
        _cancelled_command_runs.add(run_id)
        process = _active_commands.get(run_id)
        container = _active_containers.get(run_id)
    if process is not None:
        _kill_tree(process)
    if container:
        force_remove(container)


MAX_WRITE_BYTES = 32000
MAX_OUTPUT = 9000
MAX_ACTIONS = 18
MAX_ROUNDS = 12
MAX_VALIDATION_RETRIES = 2
COMMAND_TIMEOUT = 45
# Installers can execute package hooks, even when npm --ignore-scripts is set
# (pip builds and environment setup remain executable code).
APPROVAL_REQUIRED_COMMANDS = frozenset({
    'npm_install','npm_ci','pip_requirements','pip_package','venv_create'
})


def critical_action(request):
    return (request.get('action') == 'command'
            and request.get('command') in APPROVAL_REQUIRED_COMMANDS)


def needs_explicit_approval(db,user_id,run_id,request):
    if request.get('action') == 'browser_tool':
        return True
    if request.get('action') == 'reference_search':
        return True
    if critical_action(request):
        return True
    if request.get('action') != 'command':
        return False
    from .workspace_guard import current_organization
    from .organizations import require_org
    org=current_organization(db,run_id)
    if not org:
        return False
    member=require_org(db,org,user_id,write=True)
    # In organizations, npm build/test and Python tests can execute
    # project-supplied scripts. Require one-time consent even in full mode.
    return not bool(member['is_personal'])
PACKAGE = re.compile(r'^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*(?:@[0-9][a-z0-9._-]*)?$', re.I)
PIP_PACKAGE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*(?:==[0-9][a-zA-Z0-9_.-]*)?$')

COMMAND_LABELS = {
    'npm_build': 'npm run build', 'npm_test': 'npm test',
    'npm_install': 'npm install --ignore-scripts [pacote]',
    'npm_ci': 'npm ci --ignore-scripts',
    'python_test': 'python -m pytest -q',
    'python_compile': 'python -m compileall -q .',
    'pip_requirements': 'python -m pip install -r requirements.txt',
    'pip_package': 'python -m pip install [pacote]',
    'venv_create': 'python -m venv .venv',
    'git_status': 'git status --short',
    'git_diff': 'git diff --no-ext-diff --no-textconv',
    'git_log': 'git log --oneline -20',
}


def _parts(relative, allow_root=False):
    if not isinstance(relative, str) or len(relative) > 280 or '\x00' in relative or '\\' in relative:
        raise HTTPException(422, 'Caminho relativo inválido.')
    if relative in ('', '.') and allow_root:
        return []
    parts = relative.split('/')
    if not parts or any(p in ('', '.', '..') or ':' in p for p in parts) or relative.startswith('/'):
        raise HTTPException(422, 'Use um caminho relativo dentro da pasta autorizada.')
    if any(p.lower() in RESTRICTED_NAMES or p.lower().startswith('.env') for p in parts):
        raise HTTPException(403, 'Arquivos sensíveis e pastas internas estão protegidos.')
    return parts


def target(folder, relative, *, creating=False, directory=False):
    """Reject traversal and symlinks, even when the destination does not yet exist."""
    root = Path(allowed_folder(folder))
    parts = _parts(relative, allow_root=directory)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise HTTPException(403, 'Links e junções não são permitidos.')
        if not current.exists() and not creating:
            raise HTTPException(404, 'Arquivo ou pasta não encontrado.')
    try:
        real_parent = current.parent.resolve(strict=True) if not current.exists() else current.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(404, 'A pasta do arquivo não existe.') from exc
    if not real_parent.is_relative_to(root):
        raise HTTPException(403, 'O caminho está fora da pasta autorizada.')
    if directory:
        if not current.is_dir():
            raise HTTPException(422, 'Diretório inválido.')
    elif current.exists() and not current.is_file():
        raise HTTPException(422, 'É necessário um arquivo regular.')
    return current


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def preview(folder, request):
    """Validate and summarize before any write or command; safe to show in UI."""
    action = request.get('action')
    relative = request.get('path', '')
    if action == 'reference_search':
        from .reference_search import validate_query
        query = validate_query(request.get('query'))
        return {
            'action': action,
            'query': query,
            'description': 'Pesquisar referências públicas no DuckDuckGo: "' + query + '". '
                           'Somente esta consulta será enviada; confira antes de aprovar.',
        }
    if action == 'list':
        directory = target(folder, relative, directory=True)
        return {'action': action, 'path': relative, 'description': 'Listar ' + str(directory.name)}
    if action == 'mkdir':
        path = target(folder, relative, creating=True)
        if path.exists():
            raise HTTPException(409, 'Esta pasta já existe.')
        return {'action': action, 'path': relative, 'description': 'Criar pasta ' + relative}
    if action == 'read':
        path = target(folder, relative)
        if path.suffix.lower() not in {'.py', '.ts', '.tsx', '.js', '.jsx', '.css', '.html', '.json',
                                      '.md', '.txt', '.yaml', '.yml', '.toml', '.sql', '.xml', '.ini',
                                      '.csv', '.bat', '.ps1', '.sh', '.go', '.rs', '.java', '.cpp', '.h'}:
            raise HTTPException(422, 'Somente leitura de texto e código é permitida.')
        return {'action': action, 'path': relative, 'description': 'Ler ' + relative}
    if action in ('write', 'replace'):
        if not isinstance(relative, str) or not relative:
            raise HTTPException(422, 'Informe o caminho do arquivo.')
        content = request.get('content') if action == 'write' else request.get('new')
        if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_WRITE_BYTES:
            raise HTTPException(413, 'O conteúdo deve ser texto UTF-8 com até 32 KB.')
        if not relative.lower().endswith(('.py', '.ts', '.tsx', '.js', '.jsx', '.css', '.html', '.json',
                                         '.md', '.txt', '.yaml', '.yml', '.toml', '.sql', '.xml',
                                         '.ini', '.csv', '.go', '.rs', '.java', '.cpp', '.h')):
            raise HTTPException(422, 'Não é permitido criar scripts executáveis nem arquivos binários.')
        # Parent must already exist. New directories require an existing command/tool in a future version.
        path = target(folder, relative, creating=True)
        before = path.read_bytes() if path.exists() else b''
        if len(before) > MAX_WRITE_BYTES:
            raise HTTPException(413, 'Arquivo existente grande demais para edição automática.')
        expected = request.get('expected_sha256')
        if path.exists() and expected != _sha(before):
            raise HTTPException(409, 'Arquivo mudou ou não foi lido antes da edição. Leia novamente.')
        if not path.exists() and expected not in (None, ''):
            raise HTTPException(409, 'Arquivo inexistente. Reavalie a alteração.')
        try:
            before_text = before.decode('utf-8')
        except UnicodeError as exc:
            raise HTTPException(422, 'Arquivo atual não é UTF-8.') from exc
        if action == 'replace':
            old = request.get('old')
            if not isinstance(old, str) or not old or len(old) > 10000 or before_text.count(old) != 1:
                raise HTTPException(409, 'Trecho original não encontrado exatamente uma vez. Leia o arquivo novamente.')
            content = before_text.replace(old, content, 1)
            if len(content.encode('utf-8')) > MAX_WRITE_BYTES:
                raise HTTPException(413, 'Arquivo resultante excede 32 KB.')
        difference = ''.join(list(difflib.unified_diff(
            before_text.splitlines(keepends=True), content.splitlines(keepends=True),
            fromfile='antes/' + relative, tofile='depois/' + relative))[:80])[:3600]
        return {'action': action, 'path': relative, 'description': 'Criar/alterar ' + relative,
                'diff': difference, 'new_bytes': len(content.encode('utf-8'))}
    if action == 'command':
        spec = command_spec(folder, request)
        return {'action': action, 'path': spec['cwd'], 'description': 'Executar: ' + spec['label']}
    raise HTTPException(422, 'Ação desconhecida. Use list, read, mkdir, write, replace ou command.')


def command_spec(folder, request):
    code = request.get('command')
    if code not in COMMAND_LABELS:
        raise HTTPException(422, 'Comando não permitido. Use uma das tarefas de desenvolvimento disponíveis.')
    cwd = request.get('cwd', '')
    root = target(folder, cwd, directory=True)
    docker_mode = command_backend() == 'docker'
    npm = ('npm' if docker_mode else
           shutil.which('npm.cmd' if os.name == 'nt' else 'npm'))
    git = 'git' if docker_mode else shutil.which('git.exe' if os.name == 'nt' else 'git')
    local_python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    # Never let a package installation mutate the Central's own interpreter or
    # another environment outside the granted workspace.
    if code in ('pip_requirements', 'pip_package') and not docker_mode and not local_python.is_file():
        raise HTTPException(422, 'Crie uma .venv dentro desta pasta antes de instalar pacotes Python.')
    python_bin = ('python3' if docker_mode else
                  str(local_python) if local_python.is_file() else sys.executable)
    if code.startswith('npm_') and not npm:
        raise HTTPException(422, 'npm não encontrado no PATH do Windows.')
    if code.startswith('git_') and not git:
        raise HTTPException(422, 'Git não instalado.')
    commands = {
        'npm_build': [npm, 'run', 'build'],
        'npm_test': [npm, 'test'],
        'npm_ci': [npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'],
        'python_test': [python_bin, '-m', 'pytest', '-q'],
        'python_compile': [python_bin, '-m', 'compileall', '-q', '.'],
        'pip_requirements': [python_bin, '-m', 'pip', 'install', '-r', 'requirements.txt'],
        'venv_create': [sys.executable, '-m', 'venv', '.venv'],
        'git_status': [git, '-c', 'core.fsmonitor=false', 'status', '--short'],
        'git_diff': [git, '-c', 'core.fsmonitor=false', 'diff', '--no-ext-diff', '--no-textconv'],
        'git_log': [git, '-c', 'core.fsmonitor=false', 'log', '--no-show-signature', '--oneline', '-20'],
    }
    package = request.get('package', '')
    if code == 'npm_install':
        if not isinstance(package, str) or not PACKAGE.fullmatch(package):
            raise HTTPException(422, 'Nome do pacote npm inválido.')
        argv = [npm, 'install', '--ignore-scripts', '--no-audit', '--no-fund', package]
    elif code == 'pip_package':
        if not isinstance(package, str) or not PIP_PACKAGE.fullmatch(package):
            raise HTTPException(422, 'Nome do pacote Python inválido.')
        argv = [python_bin, '-m', 'pip', 'install', package]
    else:
        argv = commands[code]
    if code == 'venv_create' and (root / '.venv').exists():
        raise HTTPException(409, 'O ambiente virtual .venv já existe nesta pasta.')
    if code in ('npm_build', 'npm_test', 'npm_ci', 'npm_install') and not (root / 'package.json').is_file():
        raise HTTPException(422, 'package.json não encontrado neste diretório.')
    if code == 'pip_requirements' and not (root / 'requirements.txt').is_file():
        raise HTTPException(422, 'requirements.txt não encontrado neste diretório.')
    if code == 'pip_requirements':
        # Disallow pip -e, -r nested files, VCS URLs and index flags in AI-driven installs.
        for line in (root / 'requirements.txt').read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*(?:\[[a-zA-Z0-9_,.-]+\])?(?:\s*(?:==|>=|<=|>|<|~=|!=)\s*[0-9a-zA-Z.*+-]+(?:\s*,\s*(?:==|>=|<=|>|<|~=|!=)\s*[0-9a-zA-Z.*+-]+)*)?', line):
                raise HTTPException(422, 'requirements.txt contém opções, URLs ou dependências locais não permitidas para instalação automática.')
    label = COMMAND_LABELS[code].replace('[pacote]', package)
    return {'cwd': cwd, 'root': root, 'argv': argv, 'label': label}


def execute(folder, request, run_id=None):
    """Blocking worker function; call using asyncio.to_thread from async routes/engine."""
    details = preview(folder, request)  # validate every execution, including after approvals
    action = request['action']
    relative = request.get('path', '')
    if action == 'list':
        directory = target(folder, relative, directory=True)
        items = []
        for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if len(items) == 120:
                break
            if child.name.lower() in RESTRICTED_NAMES or child.name.lower().startswith('.env'):
                continue
            if child.is_symlink() or (hasattr(child, 'is_junction') and child.is_junction()):
                continue
            items.append({'name': child.name, 'type': 'dir' if child.is_dir() else 'file'})
        return {'items': items, 'path': relative}
    if action == 'mkdir':
        directory = target(folder, relative, creating=True)
        with _process_lock:
            if run_id and run_id in _cancelled_command_runs:
                raise HTTPException(409, 'Tarefa cancelada; criação de pasta bloqueada.')
            directory.mkdir()
        return {'path': relative, 'created': True}
    if action == 'read':
        file = target(folder, relative)
        if file.stat().st_size > MAX_WRITE_BYTES:
            raise HTTPException(413, 'Arquivo de código grande demais (32 KB).')
        data = file.read_bytes()
        try:
            decoded = data.decode('utf-8')
        except UnicodeError as exc:
            raise HTTPException(422, 'Arquivo não é UTF-8.') from exc
        return {'path': relative, 'content': decoded, 'sha256': _sha(data)}
    if action in ('write', 'replace'):
        file = target(folder, relative, creating=True)
        # Check version again immediately before atomic replacement.
        old = file.read_bytes() if file.exists() else None
        expected = request.get('expected_sha256')
        if (old is not None and _sha(old) != expected) or (old is None and expected not in ('', None)):
            raise HTTPException(409, 'Conflito de edição: arquivo mudou. Leia novamente.')
        if action == 'replace':
            before_text = old.decode('utf-8') if old is not None else ''
            pattern = request['old']
            if before_text.count(pattern) != 1:
                raise HTTPException(409, 'Trecho original mudou. Leia novamente.')
            content = before_text.replace(pattern, request['new'], 1)
        else:
            content = request['content']
        new_data = content.encode('utf-8')
        import tempfile
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.central-write-', dir=file.parent, delete=False) as out:
                tmp = Path(out.name)
                out.write(new_data)
            with _process_lock:
                if run_id and run_id in _cancelled_command_runs:
                    raise HTTPException(409, 'Tarefa cancelada; alteração de arquivo bloqueada.')
                os.replace(tmp, file)
        finally:
            if tmp and tmp.exists():
                tmp.unlink()
        return {'path': relative, 'sha256': _sha(new_data), 'bytes': len(new_data), 'diff': details['diff']}
    spec = command_spec(folder, request)
    env_keys = ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA',
                'LOCALAPPDATA', 'HOME', 'VIRTUAL_ENV')
    env = {k: v for k, v in os.environ.items() if k.upper() in env_keys}
    env.update({'CI': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
                'PYTHONUNBUFFERED': '1', 'npm_config_update_notifier': 'false'})
    if not _command_slots.acquire(blocking=False):
        return {'command': spec['label'], 'exit_code': None,
                'output':'Máximo de dois comandos locais simultâneos por processo.',
                'success': False}
    proc = None
    reader = None
    container_name = None
    egress = None
    preparation_owned = False
    output_tail = bytearray()
    total_output_bytes = [0]

    def drain():
        # Draining in a thread rather than communicate() avoids retaining
        # unlimited stdout/stderr in RAM when a tool produces huge logs.
        while True:
            try:
                data = proc.stdout.read(4096)
            except (OSError, ValueError):
                break
            if not data:
                break
            total_output_bytes[0] += len(data)
            output_tail.extend(data)
            if len(output_tail) > MAX_OUTPUT:
                del output_tail[:-MAX_OUTPUT]

    try:
        with _process_lock:
            if run_id and (run_id in _active_commands or run_id in _preparing_runs):
                return {'command': spec['label'], 'exit_code': None,
                        'output': 'Outro comando desta tarefa ainda está em execução.', 'success': False}
            if run_id:
                _preparing_runs.add(run_id)
                preparation_owned = True
        if (command_backend() == 'docker' and request.get('command') in INSTALL_COMMANDS
                and dependency_network() == 'proxy'):
            egress = Lease()
            egress.prepare(cancelled=lambda: bool(run_id and run_id in _cancelled_command_runs))
        with _process_lock:
            if run_id and run_id in _cancelled_command_runs:
                return {'command': spec['label'], 'exit_code': None,
                        'output': 'Execução cancelada pelo usuário.', 'success': False}
            if run_id and run_id in _active_commands:
                return {'command': spec['label'], 'exit_code': None,
                        'output': 'Outro comando desta tarefa ainda está em execução.',
                        'success': False}
            argv = spec['argv']
            if command_backend() == 'docker':
                argv, container_name = (sandbox_argv(spec, request, egress=egress) if egress
                                        else sandbox_argv(spec, request))
                env = docker_environment()
            proc = subprocess.Popen(
                argv, cwd=str(spec['root']), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False,
                shell=False,
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0),
                start_new_session=(os.name != 'nt'))
            if run_id:
                _active_commands[run_id] = proc
                if container_name:
                    _active_containers[run_id] = container_name
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            proc.wait(timeout=COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            if container_name:
                force_remove(container_name)
            proc.wait(timeout=5)
            return {'command': spec['label'], 'exit_code': None,
                    'output': 'Tempo limite de 45 segundos excedido. Processo encerrado.',
                    'success': False}
        if reader:
            reader.join(timeout=2)
        output = output_tail.decode('utf-8', errors='replace')
        return {'command': spec['label'], 'exit_code': proc.returncode,
                'output': output,
                'output_truncated': total_output_bytes[0] > MAX_OUTPUT,
                'success': proc.returncode == 0}
    except (OSError, subprocess.TimeoutExpired) as exc:
        if proc:
            _kill_tree(proc)
        if container_name:
            force_remove(container_name)
        return {'command': spec['label'], 'exit_code': None,
                'output': 'Falha ao iniciar ou encerrar ferramenta: ' + str(exc)[:250],
                'success': False}
    finally:
        if proc:
            if proc.stdout:
                try:
                    proc.stdout.close()
                except OSError:
                    pass
            if reader:
                reader.join(timeout=1)
        if run_id and proc:
            with _process_lock:
                if _active_commands.get(run_id) is proc:
                    _active_commands.pop(run_id, None)
                if _active_containers.get(run_id) == container_name:
                    _active_containers.pop(run_id, None)
        if preparation_owned:
            with _process_lock:
                _preparing_runs.discard(run_id)
        if egress:
            force_remove(container_name)
            egress.cleanup()
        _command_slots.release()

async def agent_action(db, user_id, run_id, step_id, request, emit, executor=None):
    requires_write = request.get('action') in ('mkdir','write','replace','command')
    folder = enforce_run_scope(db,user_id,run_id,write=requires_write)
    browser_tool = request.get('action') == 'browser_tool'
    reference_search = request.get('action') == 'reference_search'
    if request.get('action') == 'command':
        enforce_host_command_policy(db,user_id,run_id)
    config = policy(db, user_id)
    if browser_tool:
        from .browser_mcp import approval_summary
        summary = approval_summary(request)
        summary.update({'action': 'browser_tool', 'tool': request['tool']})
    else:
        summary = preview(folder, request)
    emit(run_id, 'workspace_action_requested', {'step_id': step_id, 'summary': summary})
    approval_required = (True if browser_tool else
                         executor.approvals.required(user_id, run_id, request) if executor
                         else needs_explicit_approval(db,user_id,run_id,request))
    if config['mode'] == 'ask' or approval_required:
        token = (executor.approvals.issue(user_id, run_id, step_id, folder, request, summary)
                 if executor else issue_approval(db, user_id, run_id, step_id, folder, request, summary))
        emit(run_id, 'workspace_approval_required', {
            'step_id': step_id, 'approval_id': token, 'summary': summary})
        for _ in range(600):  # 10 minute deadline, cancellation propagates
            await asyncio.sleep(1)
            row = db.one('SELECT status FROM workspace_action_approvals WHERE id=? AND user_id=?',
                         (token, user_id))
            if row and row['status'] in ('approved', 'denied'):
                if row['status'] == 'denied':
                    return {'error': 'Operação negada pelo usuário.', 'approved': False}
                break
            if policy(db, user_id) != config:
                return {'error': 'Permissão revogada ou alterada.', 'approved': False}
        else:
            return {'error': 'Aprovação expirou após 10 minutos.', 'approved': False}
    if policy(db, user_id) != config:
        return {'error': 'Permissão revogada ou alterada.', 'approved': False}
    enforce_run_scope(db,user_id,run_id,write=requires_write)
    if request.get('action') == 'command':
        enforce_host_command_policy(db,user_id,run_id)
    try:
        if browser_tool:
            from .browser_mcp import execute as execute_browser
            result = await execute_browser(db, user_id, run_id, request)
        elif reference_search:
            from .reference_search import search
            result = await asyncio.to_thread(search, request.get('query'))
        else:
            result = await asyncio.to_thread(
                executor.execute if executor else execute, folder, request, run_id)
    except HTTPException as exc:
        result = {'error': str(exc.detail), 'success': False}
    emit(run_id, 'workspace_action_result', {
        'step_id': step_id, 'summary': summary,
        'tool': request.get('tool', ''),
        'references': result.get('references', [])[:6],
        'success': result.get('success', 'error' not in result),
        'exit_code': result.get('exit_code'), 'output': str(result.get('output', ''))[-1600:]})
    return result


def validation_commands(folder, changed_files=None):
    """Run real checks in the nearest applicable workspace, never an empty build.

    A monorepo can be nested several levels below the granted folder. Validate
    the project actually touched rather than compiling unrelated root files.
    """
    root = Path(allowed_folder(folder))
    candidates = []
    for relative in changed_files or []:
        if not isinstance(relative, str):
            continue
        try:
            path = target(folder, relative, creating=False)
        except HTTPException:
            continue
        for directory in (path.parent, *path.parent.parents):
            if not directory.is_relative_to(root):
                break
            pkg = directory / 'package.json'
            if pkg.is_file():
                try:
                    scripts = json.loads(pkg.read_text(encoding='utf-8')).get('scripts') or {}
                except (OSError, ValueError, AttributeError):
                    scripts = {}
                if isinstance(scripts, dict):
                    if 'build' in scripts:
                        candidates.append((directory, 'npm_build'))
                    elif 'test' in scripts:
                        candidates.append((directory, 'npm_test'))
                if 'build' in scripts or 'test' in scripts:
                    break

    if not candidates:
        for directory in (root, root / 'frontend'):
            pkg = directory / 'package.json'
            if not pkg.is_file():
                continue
            try:
                scripts = json.loads(pkg.read_text(encoding='utf-8')).get('scripts') or {}
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(scripts, dict):
                if 'build' in scripts:
                    candidates.append((directory, 'npm_build'))
                elif 'test' in scripts:
                    candidates.append((directory, 'npm_test'))

    commands = []
    for directory, name in candidates:
        command = {'action': 'command', 'command': name}
        if directory != root:
            command['cwd'] = directory.relative_to(root).as_posix()
        if command not in commands:
            commands.append(command)

    if ((root / 'tests').is_dir() or (root / 'pytest.ini').exists()
            or (root / 'pyproject.toml').exists()):
        commands.append({'action': 'command', 'command': 'python_test'})
    if not commands:
        # Never claim a JavaScript app was validated by an empty compileall.
        python_files = any(root.glob('*.py')) or any(root.glob('src/*.py'))
        if python_files:
            commands.append({'action': 'command', 'command': 'python_compile'})
    if not commands:
        raise RuntimeError(
            'Nenhum build ou teste aplicável foi encontrado nos projetos modificados. '
            'Crie/configure scripts de validação antes de declarar a entrega concluída.')
    return commands[:2]
