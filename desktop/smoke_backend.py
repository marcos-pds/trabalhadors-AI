"""Run the bundled backend with fresh data and verify its real HTTP surface."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import secrets
import subprocess
import tempfile
import threading
import time
from urllib.request import urlopen
from urllib.request import Request
from urllib.error import HTTPError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='central-desktop-frozen-') as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith('CENTRAL_')}
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        if os.name == 'nt':
            windows = Path(os.environ['SystemRoot'])
            env['PATH'] = str(windows / 'System32') + os.pathsep + str(windows)
        token = secrets.token_hex(32)
        env.update(CENTRAL_DATA_DIR=directory, CENTRAL_DEPLOYMENT_MODE='local',
                   CENTRAL_DESKTOP_SHUTDOWN_TOKEN=token)
        proc = subprocess.Popen([str(binary)], cwd=binary.parent, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        lines = queue.Queue()

        def read(stream):
            for line in iter(stream.readline, b''):
                lines.put(line.decode('utf-8', errors='replace').strip())
        readers = [threading.Thread(target=read, args=(stream,), daemon=True)
                   for stream in (proc.stdout, proc.stderr)]
        for thread in readers:
            thread.start()
        try:
            deadline = time.monotonic() + 65
            url = None
            errors = []
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=.2)
                except queue.Empty:
                    if proc.poll() is not None:
                        break
                    continue
                match = re.fullmatch(r'CENTRAL_DESKTOP_READY=(http://127\.0\.0\.1:\d{1,5}/)', line)
                if match:
                    url = match[1]
                    break
                errors.append(line)
            if not url:
                raise RuntimeError('Frozen backend startup failed: ' + '\n'.join(errors[-12:]))
            with urlopen(url + 'api/health/ready', timeout=10) as response:
                health = json.load(response)
            assert health['status'] == 'ready' and health['database'] == 'ready', health
            with urlopen(url, timeout=10) as response:
                html = response.read().decode()
                assert '<html' in html
            assets = re.findall(r'(?:src|href)="(/[^" ]+\.(?:js|css))"', html)
            assert assets
            for asset in assets:
                with urlopen(url.rstrip('/') + asset, timeout=10) as response:
                    assert response.status == 200 and response.read()
            try:
                urlopen(url + 'api/projects', timeout=10)
            except HTTPError as error:
                assert error.code == 401
            else:
                raise AssertionError('Desktop must preserve authentication')
            assert (Path(directory) / 'central.sqlite3').is_file()
            print(json.dumps({'packaged_backend': True, 'ready': True, 'frontend_assets': len(assets),
                              'authentication_required': True, 'isolated_data': True,
                              'external_python_node_hidden_from_path': os.name == 'nt'}))
        finally:
            if proc.poll() is None and url:
                try:
                    with urlopen(Request(url + '__desktop/shutdown', method='POST',
                                         headers={'X-Central-Desktop-Token': token}), timeout=3):
                        pass
                    proc.wait(timeout=12)
                except Exception:
                    proc.terminate()
            elif proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
            for thread in readers:
                thread.join(timeout=2)
            proc.stdout.close()
            proc.stderr.close()


if __name__ == '__main__':
    main()
