"""Real Linux Docker tests. Opt in with CENTRAL_DOCKER_INTEGRATION=1.

Run only against the operator's test Docker daemon; tests create disposable
networks, proxy containers and project fixtures. No host directories are deleted.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

import pytest
from central import dependency_egress as egress, sandbox_executor as sb
from central import workspace_tools as tools, docker_preview

pytestmark = pytest.mark.skipif(os.environ.get('CENTRAL_DOCKER_INTEGRATION') != '1',
                                reason='Real Docker integration is opt-in')


@pytest.fixture
def isolated_project(tmp_path, monkeypatch):
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'docker')
    monkeypatch.setenv('CENTRAL_DOCKER_INSTALL_NETWORK', 'proxy')
    monkeypatch.setenv('CENTRAL_EGRESS_DOMAINS', egress.DEFAULT_DOMAINS)
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'local')
    (tmp_path / 'package.json').write_text('{"name":"isolated-test","version":"1.0.0"}')
    return tmp_path


def test_real_npm_download_then_offline_ci(isolated_project, monkeypatch):
    result = tools.execute(str(isolated_project), {
        'action': 'command', 'command': 'npm_install', 'package': 'is-number@7.0.0'},
        run_id='integration-npm')
    assert result['success'], result
    assert (isolated_project / '.central-npm-cache').is_dir()
    assert json.loads((isolated_project / 'node_modules/is-number/package.json').read_text())['version'] == '7.0.0'
    monkeypatch.setenv('CENTRAL_DOCKER_INSTALL_NETWORK', 'none')
    offline = tools.execute(str(isolated_project), {'action': 'command', 'command': 'npm_ci'},
                            run_id='integration-npm-offline')
    assert offline['success'], offline


def test_real_python_wheel_download_and_offline_install(isolated_project, monkeypatch):
    request = {'action': 'command', 'command': 'pip_package', 'package': 'idna==3.10'}
    result = tools.execute(str(isolated_project), request, run_id='integration-pip')
    assert result['success'], result
    assert (isolated_project / '.central-python/idna/__init__.py').is_file()
    assert list((isolated_project / '.central-wheels').glob('idna-*.whl'))
    monkeypatch.setenv('CENTRAL_DOCKER_INSTALL_NETWORK', 'none')
    offline = tools.execute(str(isolated_project), request, run_id='integration-pip-offline')
    assert offline['success'], offline


def test_real_egress_allows_registry_and_blocks_bypass(isolated_project):
    lease = egress.Lease()
    container = None
    try:
        lease.prepare()
        args, container = sb.sandbox_argv({'root': isolated_project}, {'command': 'npm_ci'}, egress=lease)
        script = '''import os,socket,urllib.request,urllib.error
proxy=urllib.request.ProxyHandler({'https':os.environ['HTTPS_PROXY']})
opener=urllib.request.build_opener(proxy)
assert opener.open('https://pypi.org/simple/idna/',timeout=8).status==200
try: opener.open('https://example.com/',timeout=8)
except urllib.error.URLError as exc: assert '403' in str(exc),str(exc)
else: raise AssertionError('Unlisted destination escaped proxy policy')
for host in ('1.1.1.1','169.254.169.254','172.17.0.1'):
 try: socket.create_connection((host,443),2)
 except OSError: pass
 else: raise AssertionError('Direct network escape to '+host)
print('egress-isolation-ok')
'''
        args = args[:args.index(sb.IMAGE) + 1] + ['python3', '-c', script]
        result = subprocess.run(args, capture_output=True, text=True, timeout=35,
                                env=egress.docker_environment())
        assert result.returncode == 0, result.stderr
        assert 'egress-isolation-ok' in result.stdout
    finally:
        sb.force_remove(container)
        lease.cleanup()


def test_real_preview_works_without_container_network(isolated_project):
    (isolated_project / 'package.json').write_text('{"scripts":{"dev":"node server.cjs"}}')
    (isolated_project / 'server.cjs').write_text('''
require('http').createServer((req,res)=>{
  res.setHeader('Content-Type','text/html');
  res.end(req.url.endsWith('/large') ? 'x'.repeat(4194305) : '<h1>isolated-preview-ok</h1>');
}).listen(4173,'127.0.0.1');
''')
    authorized = [True]
    entry = docker_preview.start(isolated_project, lambda: authorized[0])
    url = 'http://127.0.0.1:' + str(entry['port']) + entry['prefix']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for attempt in range(30):
            try:
                with opener.open(url, timeout=10) as response:
                    assert b'isolated-preview-ok' in response.read()
                    assert response.headers['Access-Control-Allow-Origin'] == '*'
                break
            except urllib.error.HTTPError:
                if attempt == 29:
                    raise
                time.sleep(.2)
        with pytest.raises(urllib.error.HTTPError) as too_large:
            opener.open(url + 'large', timeout=10)
        assert too_large.value.code == 502
        authorized[0] = False
        with pytest.raises(urllib.error.HTTPError) as revoked:
            opener.open(url, timeout=5)
        assert revoked.value.code == 404
    finally:
        docker_preview.cleanup(entry)
        entry['process'].wait(timeout=8)
