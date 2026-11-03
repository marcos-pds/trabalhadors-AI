"""Own the local ComfyUI process started on behalf of Motion Studio."""
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit

import httpx

from .motion_contracts import ContractError, _root, _reparse, runtime_path


class ComfyStartupError(RuntimeError):
    """ComfyUI could not be started or did not become ready."""


class ComfyRuntime:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._log = None
        self._job = None

    @staticmethod
    def _healthy(endpoint):
        try:
            with httpx.Client(timeout=1, trust_env=False, follow_redirects=False) as client:
                response = client.get(endpoint.rstrip('/') + '/system_stats')
                return response.status_code == 200 and isinstance(response.json(), dict)
        except (httpx.HTTPError, ValueError):
            return False

    def ensure_started(self, config, timeout=90):
        if not config.comfy_endpoint or not config.comfy_root:
            raise ComfyStartupError('ComfyUI local não foi localizado na instalação desta Central.')
        if self._healthy(config.comfy_endpoint):
            return 'running'
        endpoint = urlsplit(config.comfy_endpoint)
        try:
            loopback = endpoint.hostname == 'localhost' or endpoint.hostname in ('127.0.0.1', '::1')
            if endpoint.scheme != 'http' or not loopback:
                raise ComfyStartupError('A inicialização automática exige endpoint ComfyUI local.')
            root = _root(config.comfy_root)
            entry = root / 'main.py'
            python = runtime_path('episode_assembly', config)
            if not entry.is_file() or _reparse(entry) or not python:
                raise ComfyStartupError('A instalação local do ComfyUI está incompleta.')
            python_path = Path(python)
            if not python_path.is_file() or python_path.is_symlink():
                raise ComfyStartupError('O runtime Python local do ComfyUI não está disponível.')
            port = endpoint.port or 80
            with self._lock:
                if self._process is None or self._process.poll() is not None:
                    self._close_log()
                    log_root = _root(python_path.parent.parent.parent)
                    log_path = log_root / 'comfyui.log'
                    if os.path.lexists(log_path) and _reparse(log_path):
                        raise ComfyStartupError('O log local do ComfyUI está vinculado a outro caminho.')
                    self._log = log_path.open('ab', buffering=0)
                    args = [
                        str(python_path), str(entry), '--listen', '127.0.0.1',
                        '--port', str(port), '--disable-auto-launch', '--reserve-vram', '2',
                    ]
                    environment = {
                        key: os.environ[key]
                        for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'PATHEXT',
                                    'SYSTEMDRIVE', 'TEMP', 'TMP', 'APPDATA',
                                    'LOCALAPPDATA', 'USERPROFILE')
                        if key in os.environ
                    }
                    environment['PATH'] = str(python_path.parent) + os.pathsep + environment.get('PATH', '')
                    environment['PYTHONNOUSERSITE'] = '1'
                    self._process = subprocess.Popen(
                        args, cwd=root, stdin=subprocess.DEVNULL,
                        stdout=self._log, stderr=subprocess.STDOUT,
                        shell=False, env=environment,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                        start_new_session=os.name != 'nt',
                    )
                    if os.name == 'nt':
                        try:
                            from .external_runtimes import _WindowsJob
                            self._job = _WindowsJob(self._process)
                        except Exception:
                            self._process.terminate()
                            self._process.wait(timeout=5)
                            self._process = None
                            self._close_log()
                            raise ComfyStartupError('A inicialização segura do ComfyUI falhou.') from None
                process = self._process
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._healthy(config.comfy_endpoint):
                    return 'running'
                if process.poll() is not None:
                    raise ComfyStartupError('O processo ComfyUI encerrou antes de ficar pronto; consulte o log local.')
                time.sleep(.5)
            raise ComfyStartupError('O ComfyUI não ficou pronto no tempo esperado; consulte o log local.')
        except ComfyStartupError:
            raise
        except (ContractError, OSError, ValueError) as exc:
            raise ComfyStartupError('Não foi possível iniciar o ComfyUI local.') from exc

    def stop(self):
        with self._lock:
            process = self._process
            self._process = None
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if self._job:
                self._job.close()
                self._job = None
            self._close_log()

    def _close_log(self):
        if self._log:
            self._log.close()
            self._log = None


COMFY_RUNTIME = ComfyRuntime()
