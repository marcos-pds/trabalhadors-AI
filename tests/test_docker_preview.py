from central import docker_preview as preview


def test_preview_transport_has_no_container_network_or_published_port(tmp_path, monkeypatch):
    from test_sandbox_executor import mock_docker
    mock_docker(monkeypatch)
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'docker')
    captured = {}
    class Server:
        server_address = ('127.0.0.1', 34567)
        def __init__(self, address, handler):
            captured['address'], captured['handler'] = address, handler
        def serve_forever(self): pass
    class Thread:
        def __init__(self, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(preview, 'ThreadingHTTPServer', Server)
    monkeypatch.setattr(preview.threading, 'Thread', Thread)
    def spawn(args, **kwargs):
        captured['argv'] = args
        return object()
    monkeypatch.setattr(preview.subprocess, 'Popen', spawn)
    entry = preview.start(tmp_path, lambda: False)
    args = captured['argv']
    assert args[args.index('--network') + 1] == 'none'
    assert '--publish' not in args and '--privileged' not in args
    assert args[-2] == '--base' and args[-1] == entry['prefix']
    assert captured['address'][0] == '127.0.0.1'
    handler = captured['handler'].__new__(captured['handler'])
    errors = []
    handler.path = entry['prefix']
    handler.send_error = lambda status: errors.append(status)
    handler.do_GET()
    assert errors == [404]  # revocation checked before Docker exec


def test_expired_preview_cannot_stop_a_replacement_session(monkeypatch):
    from central import live_preview
    old, current = {}, {'process': object()}
    monkeypatch.setattr(live_preview, '_SESSIONS', {'user': current})
    live_preview.stop('user', expected=old)
    assert live_preview._SESSIONS['user'] is current
