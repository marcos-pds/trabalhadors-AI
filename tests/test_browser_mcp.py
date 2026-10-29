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


def test_browser_mcp_closes_session_at_run_end_in_owner_task(monkeypatch):
    async def scenario():
        factory = OwnedSessionFactory()
        monkeypatch.setattr(browser_mcp, '_open_session', factory.open)
        monkeypatch.setattr(browser_mcp, 'available', lambda *args: True)
        run_id = 'cleanup-test'
        key = browser_mcp._loop_key(run_id)
        result = await asyncio.create_task(execute(None, 'user', run_id, LIST_REQUEST))
        assert result['success']
        owner = factory.owners[0]
        assert owner is not asyncio.current_task()
        await asyncio.create_task(browser_mcp.close_run(run_id))
        assert factory.closed == [owner]
        assert owner.done()
        assert key not in browser_mcp._sessions

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
    # Node.js 22 (supported by the application) has no URLPattern global.
    # CI additionally runs this real URLPattern check on Node.js 24.
    feature = subprocess.run([node, '-p', 'typeof URLPattern'],
                             capture_output=True, text=True, timeout=10)
    if feature.returncode or feature.stdout.strip() != 'function':
        pytest.skip('URLPattern indisponível neste Node; CI valida com Node 24')
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


@pytest.mark.parametrize('tool, arguments', [
    ('click', {'pageId': 1, 'uid': '1_2', 'includeSnapshot': True}),
    ('fill', {'pageId': 1, 'uid': '1_2', 'value': 'Teste'}),
])
def test_local_interaction_request(tool, arguments):
    assert validate_request({'action': 'browser_tool', 'tool': tool,
                             'arguments': arguments}) == (tool, arguments)


@pytest.mark.parametrize('tool, arguments', [
    ('click', {'uid': '1_2'}),
    ('click', {'pageId': 1, 'uid': ''}),
    ('click', {'pageId': 1, 'uid': '1_2', 'includeSnapshot': 'true'}),
    ('fill', {'pageId': 1, 'uid': '1_2', 'value': 'x' * 2001}),
    ('fill', {'pageId': 1, 'uid': '1_2', 'value': 123}),
    ('fill', {'pageId': 1, 'uid': '1_2'}),
])
def test_interactions_require_scoped_bounded_arguments(tool, arguments):
    with pytest.raises(ValueError):
        validate_request({'action': 'browser_tool', 'tool': tool, 'arguments': arguments})


def test_console_error_beyond_display_limit_cannot_be_approved():
    class VerboseSession(FakeSession):
        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name='list_console_messages')])

        async def call_tool(self, name, arguments):
            if name in ('list_pages', 'select_page'):
                return await super().call_tool(name, arguments)
            text = '## Console messages\n' + 'msgid=1 [info] ok\n' * 600 + 'msgid=2 [error] broken'
            return SimpleNamespace(content=[SimpleNamespace(type='text', text=text)],
                                   structuredContent=None, isError=False)

    async def scenario():
        session = VerboseSession([{'id': 1, 'url': 'http://localhost:12345/', 'selected': True}])
        result = await _call(session, 'list_console_messages', {'pageId': 1})
        import json
        assert isinstance(json.loads(result['output']), dict)
        assert result['qa_pass'] is False
        assert 'erro' in result['qa_issue']
    asyncio.run(scenario())


def test_interaction_closes_new_external_tab_and_reports_failure():
    class PopupSession(FakeSession):
        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name='click')])

        async def call_tool(self, name, arguments):
            if name in ('list_pages', 'select_page'):
                return await super().call_tool(name, arguments)
            self.calls.append((name, arguments))
            if name == 'click':
                assert 'pageId' not in arguments
                self.pages.append({'id': 2, 'url': 'https://example.com/', 'selected': True})
            elif name != 'close_page':
                raise AssertionError(name)
            return SimpleNamespace(content=[], structuredContent=None, isError=False)

    async def scenario():
        session = PopupSession([{'id': 1, 'url': 'http://localhost:12345/', 'selected': True}])
        with pytest.raises(RuntimeError, match='interação'):
            await _call(session, 'click', {'pageId': 1, 'uid': '1_2'})
        assert ('close_page', {'pageId': 2}) in session.calls
    asyncio.run(scenario())


LIST_REQUEST = {'action': 'browser_tool', 'tool': 'list_pages', 'arguments': {}}


class OwnedSessionFactory:
    """A real AnyIO task group makes cross-task context exit fail as stdio does."""

    def __init__(self, *, block_open=False, block_call=False, block_cleanup=False):
        self.block_open = block_open
        self.block_call = block_call
        self.block_cleanup = block_cleanup
        self.opened = asyncio.Event()
        self.called = asyncio.Event()
        self.cleaning = asyncio.Event()
        self.release_cleanup = asyncio.Event()
        self.owners = []
        self.closed = []
        self.calls = []
        self.active = 0
        self.peak = 0

    async def open(self, db, user_id, run_id):
        from contextlib import AsyncExitStack, asynccontextmanager
        import anyio

        owner = asyncio.current_task()
        self.owners.append(owner)

        @asynccontextmanager
        async def transport():
            async with anyio.create_task_group() as group:
                group.start_soon(anyio.sleep_forever)
                try:
                    yield
                finally:
                    assert asyncio.current_task() is owner
                    self.cleaning.set()
                    if self.block_cleanup:
                        await self.release_cleanup.wait()
                    group.cancel_scope.cancel()
            self.closed.append(owner)

        factory = self

        class Session:
            async def call_tool(self, tool, arguments):
                assert asyncio.current_task() is owner
                factory.calls.append((owner, tool))
                factory.active += 1
                factory.peak = max(factory.peak, factory.active)
                factory.called.set()
                try:
                    if factory.block_call:
                        await asyncio.Event().wait()
                    await asyncio.sleep(0)
                    return SimpleNamespace(structuredContent={'pages': []}, content=[], isError=False)
                finally:
                    factory.active -= 1

        stack = AsyncExitStack()
        await stack.enter_async_context(transport())
        try:
            self.opened.set()
            if self.block_open:
                await asyncio.Event().wait()
            return {'stack': stack, 'session': Session(), 'lock': asyncio.Lock()}
        except BaseException:
            await stack.aclose()
            raise


def test_owner_serializes_cross_task_commands_and_close_all(monkeypatch):
    async def scenario():
        factory = OwnedSessionFactory()
        monkeypatch.setattr(browser_mcp, '_open_session', factory.open)
        monkeypatch.setattr(browser_mcp, 'available', lambda *args: True)
        tasks = [asyncio.create_task(execute(None, 'user', 'serial', LIST_REQUEST)) for _ in range(3)]
        assert all(result['success'] for result in await asyncio.gather(*tasks))
        assert len(factory.owners) == 1
        assert factory.peak == 1
        assert {owner for owner, _ in factory.calls} == set(factory.owners)
        await execute(None, 'user', 'other-run', LIST_REQUEST)
        await asyncio.create_task(browser_mcp.close_all())
        assert len(factory.closed) == 2
        assert all(owner.done() for owner in factory.owners)
        assert not any(key[0] == id(asyncio.get_running_loop()) for key in browser_mcp._sessions)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize('phase', ['open', 'call'])
def test_cancelled_worker_closes_owner_and_rejects_queued_commands(monkeypatch, phase):
    async def scenario():
        factory = OwnedSessionFactory(block_open=phase == 'open', block_call=phase == 'call')
        monkeypatch.setattr(browser_mcp, '_open_session', factory.open)
        monkeypatch.setattr(browser_mcp, 'available', lambda *args: True)
        worker = asyncio.create_task(execute(None, 'user', 'cancelled', LIST_REQUEST))
        await (factory.opened if phase == 'open' else factory.called).wait()
        queued = asyncio.create_task(execute(None, 'user', 'cancelled', LIST_REQUEST))
        await asyncio.sleep(0)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        with pytest.raises(RuntimeError, match='encerrada'):
            await queued
        assert factory.closed == factory.owners
        assert all(owner.done() for owner in factory.owners)
        assert browser_mcp._loop_key('cancelled') not in browser_mcp._sessions

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_cancelling_closer_does_not_cancel_same_task_cleanup(monkeypatch):
    async def scenario():
        factory = OwnedSessionFactory(block_cleanup=True)
        monkeypatch.setattr(browser_mcp, '_open_session', factory.open)
        monkeypatch.setattr(browser_mcp, 'available', lambda *args: True)
        await execute(None, 'user', 'closing', LIST_REQUEST)
        closer = asyncio.create_task(browser_mcp.close_run('closing'))
        await factory.cleaning.wait()
        closer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closer
        assert not factory.owners[0].done()
        factory.release_cleanup.set()
        await browser_mcp.close_run('closing')
        assert factory.closed == factory.owners
        assert browser_mcp._loop_key('closing') not in browser_mcp._sessions

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_close_before_owner_starts_does_not_leave_pending_futures(monkeypatch):
    async def scenario():
        factory = OwnedSessionFactory()
        monkeypatch.setattr(browser_mcp, '_open_session', factory.open)
        monkeypatch.setattr(browser_mcp, 'available', lambda *args: True)
        worker = asyncio.create_task(execute(None, 'user', 'unstarted', LIST_REQUEST))
        await asyncio.sleep(0)
        actor = browser_mcp._sessions[browser_mcp._loop_key('unstarted')]
        assert not actor['started']
        await browser_mcp.close_run('unstarted')
        with pytest.raises(RuntimeError, match='encerrada'):
            await worker
        assert actor['task'].done()
        assert factory.owners == []
        assert browser_mcp._loop_key('unstarted') not in browser_mcp._sessions

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


def test_failed_initialization_fails_all_waiters_and_allows_retry(monkeypatch):
    async def scenario():
        monkeypatch.setattr(browser_mcp, 'available', lambda *args: True)

        async def fail_open(*args):
            await asyncio.sleep(0)
            raise RuntimeError('initialization failed')

        monkeypatch.setattr(browser_mcp, '_open_session', fail_open)
        results = await asyncio.gather(
            execute(None, 'user', 'retry', LIST_REQUEST),
            execute(None, 'user', 'retry', LIST_REQUEST), return_exceptions=True)
        assert all(isinstance(result, RuntimeError) and str(result) == 'initialization failed'
                   for result in results)
        assert browser_mcp._loop_key('retry') not in browser_mcp._sessions
        factory = OwnedSessionFactory()
        monkeypatch.setattr(browser_mcp, '_open_session', factory.open)
        assert (await execute(None, 'user', 'retry', LIST_REQUEST))['success']
        await browser_mcp.close_run('retry')
        assert factory.closed == factory.owners

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
