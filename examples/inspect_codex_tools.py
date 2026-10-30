"""Inspect the installed Codex tool surface against a local HTTP recorder.

No real inference: the local model endpoint records tool names and returns 400.
No user config, credential content or prompts are printed.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import time

from central.codex_runtime import _Client, _executable
from central.codex_bridge import restricted_config, cli_arguments


def main():
    captured, ready = {}, threading.Event()

    class Recorder(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if length > 4 * 1024 * 1024:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(length))
            captured['tools'] = payload.get('tools', [])
            ready.set()
            body = b'{"error":{"message":"local capability inspection only","type":"invalid_request_error"}}'
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = None
    try:
        with ExitStack() as stack:
            directory = stack.enter_context(tempfile.TemporaryDirectory(prefix='central-codex-tools-'))
            config = restricted_config()
            config.update({
                'model_provider': 'central_inspection',
                'model_providers.central_inspection': {
                    'name': 'Local inspection', 'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                    'wire_api': 'responses', 'requires_openai_auth': False,
                    'request_max_retries': 0, 'stream_max_retries': 0,
                },
            })
            arguments = cli_arguments(config)
            client = _Client(arguments, time.monotonic() + 40, None)
            stack.callback(client.close)
            client.request('initialize', {'clientInfo': {'name': 'central_capability_inspection', 'version': '1.0'}})
            client.send({'method': 'initialized', 'params': {}})
            result = client.request('thread/start', {
                'model': 'gpt-6.1-sol', 'cwd': str(Path(directory).resolve()),
                'sandbox': 'read-only', 'approvalPolicy': 'never', 'ephemeral': True,
                'baseInstructions': 'Return OK. No tool use.',
                'config': {'model_provider': 'central_inspection'},
            })
            client.request('turn/start', {'threadId': result['thread']['id'],
                           'input': [{'type': 'text', 'text': 'Return OK.'}]})
            if not ready.wait(15):
                raise RuntimeError('Local recorder did not receive an inference request')
            names = [tool.get('name', tool.get('type')) for tool in captured['tools']]
            print(json.dumps({'tool_names': names, 'count': len(names)}))
            client = None
    finally:
        if client is not None:
            client.close()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
