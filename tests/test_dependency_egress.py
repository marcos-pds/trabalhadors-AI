import json

import pytest
from fastapi import HTTPException
from central import dependency_egress as egress, sandbox_executor as sb
from central import workspace_tools as tools
from sandbox import egress_proxy as proxy
from test_sandbox_executor import mock_docker


def answer(*addresses):
    return [(2, 1, 6, '', (address, 443)) for address in addresses]


@pytest.mark.parametrize('authority', [
    'localhost:443', '127.0.0.1:443', '169.254.169.254:443',
    'pypi.org:80', 'pypi.org:0443', 'user@pypi.org:443',
    'pypi.org.evil.com:443', 'pypi.org.:443', '[::1]:443',
])
def test_proxy_rejects_unlisted_names_ports_and_ambiguous_authorities(authority):
    with pytest.raises(ValueError):
        proxy.destination(authority, proxy.domains(proxy.DEFAULT_DOMAINS),
                          lambda *_args: pytest.fail('Denied name must not reach DNS'))


@pytest.mark.parametrize('address', [
    '127.0.0.1', '10.0.0.2', '172.16.0.1', '192.168.1.1', '169.254.169.254',
    '100.64.0.1', '0.0.0.0', '224.0.0.1', '::1', '::ffff:127.0.0.1',
])
def test_proxy_rejects_private_reserved_and_mixed_dns_answers(address):
    with pytest.raises(ValueError):
        proxy.destination('pypi.org:443', {'pypi.org'}, lambda *_: answer('151.101.0.223', address))


def test_proxy_pins_one_validated_public_ipv4_resolution():
    calls = []
    def resolve(*args):
        calls.append(args)
        return answer('151.101.0.223')
    assert proxy.destination('pypi.org:443', {'pypi.org'}, resolve) == ('151.101.0.223', 443)
    assert len(calls) == 1


@pytest.mark.parametrize('value', ['', '*.pypi.org', 'https://pypi.org', 'pypi.org,', 'pypi.org:443'])
def test_allowlist_configuration_fails_closed(value):
    with pytest.raises(ValueError):
        proxy.domains(value)


def test_proxy_requires_per_job_authentication_before_resolution():
    handler = proxy.handler({'pypi.org'}, 'a' * 40)
    request = handler.__new__(handler)
    request.headers = {}
    request.send_response = lambda code: statuses.append(code)
    request.send_header = lambda *_: None
    request.end_headers = lambda: None
    statuses = []
    request.do_CONNECT()
    assert statuses == [407] and request.close_connection


def test_lease_builds_isolated_network_and_cleans_only_its_resources(monkeypatch):
    calls = []
    mock_docker(monkeypatch)
    monkeypatch.setattr(egress.subprocess, 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    lease = egress.Lease()
    lease.prepare()
    assert lease.ready
    args = calls[0][0]
    assert '--internal' in args and 'com.docker.network.bridge.gateway_mode_ipv4=isolated' in args
    creation = next(args for args, _ in calls if args[1] == 'create')
    assert '--publish' not in creation and '--mount' not in creation
    assert creation[creation.index('--pull') + 1] == 'never'
    assert 'CENTRAL_EGRESS_TOKEN=' + lease.token in creation
    assert '--cap-drop' in creation and 'net.ipv4.ip_forward=0' in creation
    lease.cleanup()
    assert not lease.ready
    assert calls[-2][0] == ['/fake/docker', 'rm', '-f', lease.proxy]
    assert calls[-1][0] == ['/fake/docker', 'network', 'rm', lease.name]


def test_proxy_mode_requires_a_prepared_lease_and_never_routes_builds(monkeypatch, tmp_path):
    mock_docker(monkeypatch)
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'docker')
    monkeypatch.setenv('CENTRAL_DOCKER_INSTALL_NETWORK', 'proxy')
    with pytest.raises(HTTPException):
        sb.sandbox_argv({'root': tmp_path}, {'command': 'npm_ci'})
    lease = egress.Lease(); lease.ready = True
    for code in ('npm_ci', 'pip_package', 'npm_build'):
        args, _ = sb.sandbox_argv({'root': tmp_path}, {'command': code, 'package': 'requests'}, egress=lease)
        assert args[args.index('--network') + 1] == (lease.name if code != 'npm_build' else 'none')
        if code != 'npm_build':
            assert args[args.index('--dns') + 1] == '127.0.0.1'
            assert '--publish' not in args
    args, _ = sb.sandbox_argv({'root': tmp_path}, {'command': 'pip_package', 'package': 'requests'}, egress=lease)
    download = json.loads(args[-2])
    assert download[download.index('--proxy') + 1] == lease.proxy_url


def test_server_mode_rejects_unrestricted_dependency_bridge(monkeypatch):
    monkeypatch.setenv('CENTRAL_DEPLOYMENT_MODE', 'server')
    monkeypatch.setenv('CENTRAL_DOCKER_INSTALL_NETWORK', 'bridge')
    with pytest.raises(HTTPException):
        egress.mode()


def test_failed_proxy_preparation_is_cleaned_and_releases_command_slot(monkeypatch, tmp_path):
    mock_docker(monkeypatch)
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'docker')
    monkeypatch.setenv('CENTRAL_DOCKER_INSTALL_NETWORK', 'proxy')
    (tmp_path / 'package.json').write_text('{}')
    cleaned = []
    class Lease:
        def prepare(self, **_kwargs):
            raise HTTPException(503, 'failed')
        def cleanup(self):
            cleaned.append(True)
    monkeypatch.setattr(tools, 'Lease', Lease)
    with pytest.raises(HTTPException):
        tools.execute(str(tmp_path), {'action': 'command', 'command': 'npm_ci'}, run_id='setup-failure')
    assert cleaned == [True]
    assert 'setup-failure' not in tools._preparing_runs
    assert tools._command_slots.acquire(blocking=False)
    tools._command_slots.release()
