"""Loopback HTTP proxy into a network-disabled preview container.

Docker exec transports HTTP bytes; no container ports or networks are exposed.
The preview has a separate browser origin from the authenticated Central API.
"""
import base64
import json
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from fastapi import HTTPException
from . import sandbox_executor as sandbox

MAX_BODY = 4 * 1024 * 1024
FETCH = '''import base64,json,sys,urllib.request,urllib.error
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
try:
 r=opener.open('http://127.0.0.1:4173'+sys.argv[1],timeout=5)
except urllib.error.HTTPError as e: r=e
b=r.read(4194305)
if len(b)>4194304: raise ValueError('Preview response exceeds limit')
print(json.dumps({'status':r.code,'type':r.headers.get('Content-Type','application/octet-stream'),'body':base64.b64encode(b).decode()}))
'''


def start(directory, authorized):
    """Return the process and separate-origin proxy; caller owns cleanup."""
    token = secrets.token_urlsafe(32)
    prefix = '/' + token + '/'
    argv, name = sandbox.sandbox_argv({'root': directory}, {'command': 'npm_build'})
    # Reuse every execution restriction, replacing only the allowlisted command.
    argv[-3:] = ['npm', 'run', 'dev', '--', '--host', '127.0.0.1',
                 '--port', '4173', '--strictPort', '--base', prefix]
    docker = argv[0]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # URLs contain a capability token.

        def do_GET(self):
            if not authorized() or not self.path.startswith(prefix) or len(self.path) > 4000:
                self.send_error(404)
                return
            path = urlsplit(self.path)
            if path.scheme or path.netloc or '\r' in self.path or '\n' in self.path:
                self.send_error(400)
                return
            if self.headers.get('Upgrade'):
                self.send_error(400, 'Use page reload; websocket HMR is disabled')
                return
            try:
                result = subprocess.run(
                    [docker, 'exec', name, 'python3', '-c', FETCH, self.path],
                    capture_output=True, timeout=8, check=True)
                response = json.loads(result.stdout)
                body = base64.b64decode(response['body'], validate=True)
                if len(body) > MAX_BODY:
                    raise ValueError('Preview response exceeds limit')
                content_type = response['type']
                if '\r' in content_type or '\n' in content_type:
                    raise ValueError('Invalid content type')
                status = int(response['status'])
                if not 200 <= status <= 599:
                    raise ValueError('Invalid response status')
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy',
                                 "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*; "
                                 "connect-src 'self'; object-src 'none'; base-uri 'self'")
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                self.send_error(502, 'Preview unavailable')

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        # Bound simultaneous Docker exec proxies, independently of request rate.
        slots = threading.BoundedSemaphore(4)

        def process_request(self, request, client_address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self.slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.slots.release()

    server = Server(('127.0.0.1', 0), Handler)
    try:
        process = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, shell=False)
    except OSError as exc:
        server.server_close()
        sandbox.force_remove(name)
        raise HTTPException(503, 'Não foi possível iniciar Docker para a prévia.') from exc
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return {'process': process, 'container': name, 'proxy': server,
            'port': server.server_address[1], 'prefix': prefix}


def cleanup(entry):
    server = entry.get('proxy')
    if server:
        server.shutdown()
        server.server_close()
    sandbox.force_remove(entry.get('container'))
