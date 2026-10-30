"""Domain-allowlisted HTTPS CONNECT proxy for an isolated dependency job.

Runs in a separate unprivileged container. DNS answers are checked once and
the upstream socket connects to that exact public IPv4 address (no rebinding).
No request URLs, credentials, or payloads are logged.
"""
import base64
import hmac
import ipaddress
import os
import re
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_DOMAINS = 'registry.npmjs.org,pypi.org,files.pythonhosted.org'
DOMAIN = re.compile(r'(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z')


def domains(value):
    names = frozenset(name.strip().lower() for name in value.split(','))
    if not 1 <= len(names) <= 32 or any(not DOMAIN.fullmatch(name) for name in names):
        raise ValueError('Configure 1..32 exact ASCII DNS names without wildcards')
    return names


def destination(authority, allowed, resolver=socket.getaddrinfo):
    if not isinstance(authority, str) or authority.count(':') != 1:
        raise ValueError('Only DNS-name:443 is permitted')
    host, port = authority.rsplit(':', 1)
    host = host.lower()
    if port != '443' or host not in allowed or not DOMAIN.fullmatch(host):
        raise ValueError('Destination not permitted')
    answers = resolver(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    addresses = {row[4][0] for row in answers}
    if not addresses:
        raise ValueError('DNS returned no addresses')
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (ip.version != 4 or not ip.is_global or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified or ip.is_loopback):
            raise ValueError('Destination DNS contains a non-public address')
    return sorted(addresses)[0], 443


def handler(allowed, token):
    class Handler(BaseHTTPRequestHandler):
        rbufsize = 0

        def log_message(self, *_args):
            pass

        def do_CONNECT(self):
            expected = 'Basic ' + base64.b64encode(('central:' + token).encode()).decode()
            if not hmac.compare_digest(self.headers.get('Proxy-Authorization', '').encode('utf-8'), expected.encode()):
                self.send_response(407)
                self.send_header('Proxy-Authenticate', 'Basic realm="dependency-job"')
                self.end_headers()
                self.close_connection = True
                return
            try:
                address = destination(self.path, allowed)
            except (ValueError, OSError):
                self.send_error(403, 'Destination denied')
                return
            try:
                with socket.create_connection(address, timeout=8) as upstream:
                    self.send_response(200, 'Connection established')
                    self.end_headers()
                    self.connection.settimeout(8)
                    upstream.settimeout(8)
                    deadline, transferred = time.monotonic() + 60, 0
                    while time.monotonic() < deadline and transferred < 32 * 1024 * 1024:
                        ready, _, _ = select.select([self.connection, upstream], [], [], 1)
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            transferred += len(data)
                            target = upstream if source is self.connection else self.connection
                            target.sendall(data)
            except OSError:
                # A CONNECT may already have completed: close, never append an
                # HTTP error to the encrypted TLS stream or expose exception text.
                return
            finally:
                self.close_connection = True
    return Handler


class Proxy(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler_class):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler_class)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

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


if __name__ == '__main__':
    allowed = domains(os.environ.get('CENTRAL_EGRESS_DOMAINS', DEFAULT_DOMAINS))
    token = os.environ.get('CENTRAL_EGRESS_TOKEN', '')
    if len(token) < 32:
        raise ValueError('A unique job token is required')
    server = Proxy(('0.0.0.0', 8080), handler(allowed, token))
    expiry = threading.Timer(120, server.shutdown)
    expiry.daemon = True
    expiry.start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
