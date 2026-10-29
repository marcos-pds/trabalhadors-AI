"""Real, isolated Chrome DevTools smoke test against an ephemeral local fixture.

Run with the Central virtualenv: python -m examples.validate_browser_tools
No production database, user browser profile, credentials or model inference.
This tests the gateway adapter, not autonomous model-driven repair.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from central.browser_mcp import SERVER_PACKAGE, _call, _npx_command, validate_request


async def validate(url, *, lighthouse=False):
    command, args = _npx_command([
        '--yes', SERVER_PACKAGE, '--headless', '--isolated', '--no-performance-crux',
        '--experimentalNavigationAllowlist',
    ])
    inherited = ('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'HOME',
                 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')
    env = {key: os.environ[key] for key in inherited if key in os.environ}
    env.update(CI='1', CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS='1')
    results = {}
    async with AsyncExitStack() as stack:
        reader, writer = await stack.enter_async_context(stdio_client(
            StdioServerParameters(command=command, args=args, env=env)))
        session = await stack.enter_async_context(ClientSession(reader, writer))
        await asyncio.wait_for(session.initialize(), 90)

        async def call(tool, arguments):
            validate_request({'action': 'browser_tool', 'tool': tool, 'arguments': arguments})
            return await _call(session, tool, arguments)

        await call('new_page', {'url': url})
        pages = (await call('list_pages', {}))['pages']
        page_id = next(page['pageId'] for page in pages if page['url'] == url)
        snap = await call('take_snapshot', {'pageId': page_id})
        assert snap['qa_pass'], snap
        text = json.loads(snap['output'])['text']
        field = re.search(r'uid=(\S+) textbox "Nome"', text)
        button = re.search(r'uid=(\S+) button "Adicionar"', text)
        assert field and button, text
        filled = await call('fill', {'pageId': page_id, 'uid': field[1],
                                     'value': 'Teste local', 'includeSnapshot': True})
        filled_text = json.loads(filled['output'])['text']
        assert 'Teste local' in filled_text, filled
        # Snapshot UIDs may change after an interaction; always read the latest.
        button = re.search(r'uid=(\S+) button "Adicionar"', filled_text)
        assert button, filled_text
        clicked = await call('click', {'pageId': page_id, 'uid': button[1],
                                      'includeSnapshot': True})
        assert 'Total: 1' in json.loads(clicked['output'])['text'], clicked
        console = await call('list_console_messages', {'pageId': page_id})
        assert console['qa_pass'], console
        results.update(snapshot=True, fill=True, click=True, console=True)
        if lighthouse:
            for device in ('desktop', 'mobile'):
                audit = await call('lighthouse_audit', {'pageId': page_id,
                                                        'mode': 'navigation', 'device': device})
                # Preserve a genuine negative audit instead of inventing success.
                results['lighthouse_' + device] = {
                    'qa_pass': audit['qa_pass'], 'qa_issue': audit['qa_issue'],
                    'report': json.loads(audit['output'])['text'],
                }
        await call('navigate_page', {'pageId': page_id, 'url': url + '?broken=1'})
        broken = await call('list_console_messages', {'pageId': page_id})
        assert broken['qa_pass'] is False, broken
        results['detected_injected_console_error'] = True
        print(json.dumps(results, ensure_ascii=False, indent=2))
        if lighthouse:
            assert all(results['lighthouse_' + device]['qa_pass'] for device in ('desktop', 'mobile'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lighthouse', action='store_true')
    args = parser.parse_args()

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith('/favicon.ico'):
                self.send_response(204)
                self.end_headers()
                return
            if self.path in ('/robots.txt', '/llms.txt'):
                body = (b'User-agent: *\nAllow: /\n' if self.path == '/robots.txt'
                        else b'# Teste Central\n\nA local application for validating the Central browser tools. '
                             b'This fixture has a named input, a counter button and observable results.\n\n'
                             b'## Documentation\n\n- [Home](/): Local interactive validation page.\n')
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = ('''<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Teste local das ferramentas de QA da Central.">
<title>Teste Central</title></head><body><main><h1>Teste Central</h1>
<label>Nome <input id="name"></label><button id="add">Adicionar</button>
<p id="total" aria-live="polite">Total: 0</p></main><script>
let count=0; document.querySelector('#add').onclick=()=>{
document.querySelector('#total').textContent='Total: '+(++count)};
''' + ('console.error("Defeito de teste injetado");' if 'broken=1' in self.path else '')
                    + '</script></body></html>').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(validate(f'http://127.0.0.1:{server.server_port}/', lighthouse=args.lighthouse))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == '__main__':
    main()
