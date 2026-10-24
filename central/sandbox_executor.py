"""Optional Docker-backed command execution, with no implicit host fallback.

The Docker daemon is an operator-controlled trusted service; this does not
isolate the Central API itself or files written by the file tools. It restricts
*command* execution when CENTRAL_COMMAND_RUNNER=docker.
"""
import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException

IMAGE = 'central-ai-executor:py311-node22'
SUPPORTED = frozenset({
    'npm_build', 'npm_test', 'python_test', 'python_compile', 'git_status'
})
BLOCKED = frozenset({
    'npm_ci', 'npm_install', 'pip_requirements', 'pip_package', 'venv_create'
})
_IMAGE_NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_./:@-]{0,159}$')


def backend():
    value = os.environ.get('CENTRAL_COMMAND_RUNNER', 'host').strip().lower()
    if value not in ('host', 'docker'):
        # Never silently interpret an unknown security setting as host mode.
        raise RuntimeError('CENTRAL_COMMAND_RUNNER deve ser host ou docker.')
    return value


def docker_available():
    return bool(shutil.which('docker.exe' if os.name == 'nt' else 'docker'))


def _workspace_source(root):
    source = str(Path(root).resolve(strict=True))
    # Docker --mount uses comma-delimited options. Reject special separators
    # rather than allow a folder name to append another bind mount option.
    if any(x in source for x in (',', '\n', '\r', '\x00')):
        raise HTTPException(422, 'O caminho não é compatível com um mount Docker seguro.')
    return source


def sandbox_argv(spec, request, name=None):
    """Construct an argv array, never a shell command or Docker flags from AI."""
    if backend() != 'docker':
        raise RuntimeError('Executor Docker não está ativo.')
    code = request.get('command')
    if code in BLOCKED:
        raise HTTPException(
            409, 'Instalações e criação de ambientes ainda não são suportadas '
                 'na sandbox sem rede. Prepare dependências fora da Central '
                 'antes de executar builds ou testes isolados.')
    if code not in SUPPORTED:
        raise HTTPException(422, 'Comando não compatível com executor isolado.')
    docker = shutil.which('docker.exe' if os.name == 'nt' else 'docker')
    if not docker:
        raise HTTPException(
            503, 'Docker não encontrado. Instale/inicie Docker Desktop e '
                 'configure uma imagem de executor. O comando não será '
                 'executado diretamente no Windows.')
    image = os.environ.get('CENTRAL_DOCKER_IMAGE', IMAGE).strip()
    if not _IMAGE_NAME.fullmatch(image) or image.startswith(('-', '/')):
        raise HTTPException(422, 'Imagem Docker configurada é inválida.')
    source = _workspace_source(spec['root'])
    workdir = '/workspace'
    # Bind the selected project subfolder ONLY. A sibling repository or home
    # directory must never be mounted by convenience. No Docker socket.
    container = name or ('central-job-' + uuid.uuid4().hex)
    if not re.fullmatch(r'central-job-[a-f0-9]{32}',container):
        raise ValueError('Invalid generated container name')
    user = (f'{os.getuid()}:{os.getgid()}'
            if os.name != 'nt' and hasattr(os, 'getuid') else '10001:10001')
    command_map = {
        'npm_build': ['npm','run','build'],
        'npm_test': ['npm','test'],
        'python_test': ['python3','-m','pytest','-q'],
        'python_compile': ['python3','-m','compileall','-q','.'],
        'git_status': ['git','-c','safe.directory=/workspace','status','--short'],
    }
    return [
        docker,'run','--rm','--name',container,
        '--network','none','--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges',
        '--pids-limit','128','--memory','512m','--memory-swap','512m',
        '--cpus','1','--user',user,
        '--tmpfs','/tmp:rw,nosuid,size=64m',
        '--mount','type=bind,source='+source+',target=/workspace',
        '--workdir',workdir,
        '-e','HOME=/tmp','-e','CI=1','-e','PYTHONDONTWRITEBYTECODE=1',
        image,*command_map[code],
    ], container


def force_remove(name):
    if not name or not re.fullmatch(r'central-job-[a-f0-9]{32}',name):
        return
    docker = shutil.which('docker.exe' if os.name == 'nt' else 'docker')
    if not docker:
        return
    import subprocess
    try:
        subprocess.run([docker,'rm','-f',name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def status():
    runner=backend()
    return {
        'backend': runner,
        'docker_installed': docker_available() if runner == 'docker' else None,
        'network': 'disabled' if runner == 'docker' else 'host',
        'memory_limit_mb': 512 if runner == 'docker' else None,
        'cpu_limit': 1 if runner == 'docker' else None,
        'pids_limit': 128 if runner == 'docker' else None,
        'docker_image': os.environ.get('CENTRAL_DOCKER_IMAGE', IMAGE) if runner == 'docker' else None,
        'dependency_installation': False if runner == 'docker' else 'requires_approval',
        'live_preview': False if runner == 'docker' else 'host_only',
        'note': ('A sandbox isola comandos, não as ferramentas de arquivo, a API ou o Docker daemon.'
                 if runner == 'docker'
                 else 'Comandos executam diretamente com os privilégios do usuário local.'),
    }
