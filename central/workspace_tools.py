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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from .computer_access import allowed_folder, policy, scoped_path, RESTRICTED_NAMES
from .database import uid, utcnow

MAX_WRITE_BYTES = 32000
MAX_OUTPUT = 9000
MAX_ACTIONS = 18
MAX_ROUNDS = 12
MAX_VALIDATION_RETRIES = 2
COMMAND_TIMEOUT = 45
PACKAGE = re.compile(r'^(?:@[-a-z0-9_.]+/)?[-a-z0-9_.]+(?:@[-a-z0-9_.]+)?$', re.I)
PIP_PACKAGE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*(?:==[0-9][a-zA-Z0-9_.-]*)?$')

COMMAND_LABELS = {
    'npm_build': 'npm run build', 'npm_test': 'npm test',
    'npm_install': 'npm install --ignore-scripts [pacote]',
    'npm_ci': 'npm ci --ignore-scripts',
    'python_test': 'python -m pytest -q',
    'python_compile': 'python -m compileall -q .',
    'pip_requirements': 'python -m pip install -r requirements.txt',
    'pip_package': 'python -m pip install [pacote]',
    'git_status': 'git status --short',
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
    if action == 'list':
        directory = target(folder, relative, directory=True)
        return {'action': action, 'path': relative, 'description': 'Listar ' + str(directory.name)}
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
    raise HTTPException(422, 'Ação desconhecida. Use list, read, write, replace ou command.')


def command_spec(folder, request):
    code = request.get('command')
    if code not in COMMAND_LABELS:
        raise HTTPException(422, 'Comando não permitido. Use uma das tarefas de desenvolvimento disponíveis.')
    cwd = request.get('cwd', '')
    root = target(folder, cwd, directory=True)
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    git = shutil.which('git.exe' if os.name == 'nt' else 'git')
    local_python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    # Never let a package installation mutate the Central's own interpreter or
    # another environment outside the granted workspace.
    if code in ('pip_requirements', 'pip_package') and not local_python.is_file():
        raise HTTPException(422, 'Crie uma .venv dentro desta pasta antes de instalar pacotes Python.')
    python_bin = str(local_python) if local_python.is_file() else sys.executable
    if code.startswith('npm_') and not npm:
        raise HTTPException(422, 'npm não encontrado no PATH do Windows.')
    if code == 'git_status' and not git:
        raise HTTPException(422, 'Git não instalado.')
    commands = {
        'npm_build': [npm, 'run', 'build'],
        'npm_test': [npm, 'test'],
        'npm_ci': [npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'],
        'python_test': [python_bin, '-m', 'pytest', '-q'],
        'python_compile': [python_bin, '-m', 'compileall', '-q', '.'],
        'pip_requirements': [python_bin, '-m', 'pip', 'install', '-r', 'requirements.txt'],
        'git_status': [git, 'status', '--short'],
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
    if code in ('npm_build', 'npm_test', 'npm_ci', 'npm_install') and not (root / 'package.json').is_file():
        raise HTTPException(422, 'package.json não encontrado neste diretório.')
    if code == 'pip_requirements' and not (root / 'requirements.txt').is_file():
        raise HTTPException(422, 'requirements.txt não encontrado neste diretório.')
    label = COMMAND_LABELS[code].replace('[pacote]', package)
    return {'cwd': cwd, 'root': root, 'argv': argv, 'label': label}


def execute(folder, request):
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
    try:
        result = subprocess.run(spec['argv'], cwd=str(spec['root']), env=env,
                                capture_output=True, text=True, errors='replace',
                                timeout=COMMAND_TIMEOUT, shell=False)
        output = ((result.stdout or '') + '\n' + (result.stderr or ''))[-MAX_OUTPUT:]
        return {'command': spec['label'], 'exit_code': result.returncode,
                'output': output, 'success': result.returncode == 0}
    except subprocess.TimeoutExpired:
        return {'command': spec['label'], 'exit_code': None,
                'output': 'Tempo limite de 45 segundos excedido.', 'success': False}


def issue_approval(db, user_id, run_id, step_id, folder, request, summary):
    # Store pending edits/commands inside the local DB; no secrets are returned to other users.
    token = uid()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    db.execute('''INSERT INTO workspace_action_approvals
      (id,user_id,run_id,step_id,folder,request_json,status,expires_at,created_at)
      VALUES(?,?,?,?,?,?,?,?,?)''',
      (token, user_id, run_id, step_id, folder, json.dumps(request, ensure_ascii=False),
       'pending', expires, utcnow()))
    return token


def decide(db, user_id, run_id, approval_id, approved):
    row = db.one('''SELECT * FROM workspace_action_approvals
      WHERE id=? AND user_id=? AND run_id=?''', (approval_id, user_id, run_id))
    if not row or row['status'] != 'pending':
        raise HTTPException(409, 'Autorização indisponível ou já respondida.')
    current = policy(db, user_id)
    if current['mode'] != 'ask' or current['folder'] != row['folder']:
        raise HTTPException(409, 'Permissão alterada ou revogada.')
    if datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
        raise HTTPException(409, 'Autorização expirada.')
    db.execute("UPDATE workspace_action_approvals SET status=? WHERE id=? AND status='pending'",
               ('approved' if approved else 'denied', approval_id))
    return {'ok': True, 'approved': approved}


async def agent_action(db, user_id, run_id, step_id, request, emit):
    config = policy(db, user_id)
    if config['mode'] == 'blocked':
        raise HTTPException(403, 'Acesso bloqueado. Autorize uma pasta no chat.')
    folder = allowed_folder(config['folder'])
    summary = preview(folder, request)
    emit(run_id, 'workspace_action_requested', {'step_id': step_id, 'summary': summary})
    if config['mode'] == 'ask':
        token = issue_approval(db, user_id, run_id, step_id, folder, request, summary)
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
    try:
        result = await asyncio.to_thread(execute, folder, request)
    except HTTPException as exc:
        result = {'error': str(exc.detail), 'success': False}
    emit(run_id, 'workspace_action_result', {
        'step_id': step_id, 'summary': summary,
        'success': result.get('success', 'error' not in result),
        'exit_code': result.get('exit_code'), 'output': str(result.get('output', ''))[-1600:]})
    return result


def validation_commands(folder):
    root = Path(folder)
    commands = []
    if (root / 'package.json').is_file():
        commands.append({'action': 'command', 'command': 'npm_build'})
    elif (root / 'frontend' / 'package.json').is_file():
        commands.append({'action': 'command', 'command': 'npm_build', 'cwd': 'frontend'})
    if (root / 'tests').is_dir() or (root / 'pytest.ini').exists() or (root / 'pyproject.toml').exists():
        commands.append({'action': 'command', 'command': 'python_test'})
    if not commands:
        commands.append({'action': 'command', 'command': 'python_compile'})
    return commands[:2]
