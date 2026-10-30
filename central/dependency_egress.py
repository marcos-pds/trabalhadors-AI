"""Per-installation Docker network and CONNECT proxy, with bounded lifecycle.

Requires Docker Engine >=28 isolated internal bridges. Older daemons fail
closed; no fallback to a routed bridge or a host process is permitted.
"""
import os
import re
import secrets
import shutil
import subprocess
import time
import uuid
from fastapi import HTTPException

IMAGE = 'central-ai-egress:py311-v1'
DEFAULT_DOMAINS = 'registry.npmjs.org,pypi.org,files.pythonhosted.org'
NAME = re.compile(r'central-egress-[a-f0-9]{32}')
INSTALL_COMMANDS = frozenset(('npm_ci', 'npm_install', 'pip_package', 'pip_requirements'))


def mode():
    value = os.environ.get('CENTRAL_DOCKER_INSTALL_NETWORK', 'none').strip()
    if value not in ('none', 'bridge', 'proxy'):
        raise HTTPException(422, 'CENTRAL_DOCKER_INSTALL_NETWORK deve ser none, bridge ou proxy.')
    if value == 'bridge' and os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local') == 'server':
        raise HTTPException(422, 'Modo servidor exige dependências offline ou por proxy restrito.')
    return value


def docker_environment():
    keys = {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA',
            'LOCALAPPDATA', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY',
            'DOCKER_CERT_PATH', 'DOCKER_CONFIG'}
    return {key: value for key, value in os.environ.items() if key.upper() in keys}


def configured_domains():
    # Share the exact parser used in the proxy image; the operator controls it.
    from sandbox.egress_proxy import domains
    value = os.environ.get('CENTRAL_EGRESS_DOMAINS', DEFAULT_DOMAINS)
    try:
        return ','.join(sorted(domains(value)))
    except ValueError as exc:
        raise HTTPException(422, 'Lista de domínios de dependências inválida.') from exc


class Lease:
    def __init__(self):
        self.domains = configured_domains()
        self.name = 'central-egress-' + uuid.uuid4().hex
        self.proxy = self.name + '-proxy'
        self.token = secrets.token_urlsafe(32)
        self.proxy_url = 'http://central:' + self.token + '@central-registry-proxy:8080'
        self.docker = shutil.which('docker.exe' if os.name == 'nt' else 'docker')
        if not self.docker:
            raise HTTPException(503, 'Docker não encontrado; instalação isolada indisponível.')
        self.ready = False

    def prepare(self, cancelled=lambda: False):
        deadline = time.monotonic() + 30
        def run(args):
            if cancelled():
                raise HTTPException(409, 'Instalação cancelada antes de iniciar o comando.')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HTTPException(504, 'Tempo limite ao preparar o proxy isolado.')
            try:
                subprocess.run([self.docker, *args], env=docker_environment(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=min(8, remaining), check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise HTTPException(503, 'Falha ao preparar proxy isolado; verifique Docker >=28 e a imagem de egress.') from exc
        run(['network', 'create', '--internal', '--driver', 'bridge',
             '--label', 'central.managed=dependency-egress',
             '--opt', 'com.docker.network.bridge.gateway_mode_ipv4=isolated',
             '--opt', 'com.docker.network.bridge.gateway_mode_ipv6=isolated', self.name])
        run(['create', '--pull', 'never', '--name', self.proxy, '--network', 'bridge',
             '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
             '--memory', '128m', '--memory-swap', '128m', '--cpus', '.25', '--pids-limit', '32',
             '--user', '10001:10001', '--sysctl', 'net.ipv4.ip_forward=0',
             '--sysctl', 'net.ipv6.conf.all.forwarding=0',
             '--label', 'central.managed=dependency-egress',
             '-e', 'CENTRAL_EGRESS_DOMAINS=' + self.domains,
             '-e', 'CENTRAL_EGRESS_TOKEN=' + self.token, IMAGE])
        run(['network', 'connect', '--alias', 'central-registry-proxy', self.name, self.proxy])
        run(['start', self.proxy])
        # Poll inside the image: no host port is published for the proxy.
        for _ in range(10):
            try:
                run(['exec', self.proxy, 'python3', '-c',
                     'import socket;s=socket.create_connection(("127.0.0.1",8080),1);s.close()'])
                self.ready = True
                return
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
                time.sleep(.1)
        raise HTTPException(503, 'O proxy de dependências não iniciou.')

    def cleanup(self):
        if not NAME.fullmatch(self.name) or self.proxy != self.name + '-proxy':
            return
        self.ready = False
        for args in (['rm', '-f', self.proxy], ['network', 'rm', self.name]):
            try:
                subprocess.run([self.docker, *args], env=docker_environment(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=8, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
