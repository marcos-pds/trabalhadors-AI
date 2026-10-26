"""Pinned, approval-gated Chrome DevTools MCP access for local project testing."""
import asyncio
from contextlib import AsyncExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
from urllib.parse import urlsplit

from fastapi import HTTPException

SERVER_PACKAGE = 'chrome-devtools-mcp@1.0.1'
NAVIGATION_ALLOWLIST = (
    'http://localhost:*/*,http://127.0.0.1:*/*,http://[::1]:*/*,'
    'https://localhost:*/*,https://127.0.0.1:*/*,https://[::1]:*/*')
ALLOWED_TOOLS = frozenset({
    'list_pages', 'new_page', 'navigate_page', 'take_snapshot',
    'list_console_messages', 'lighthouse_audit', 'get_css_styles',
})
TOOL_ARGUMENTS = {
    'list_pages': set(),
    'new_page': {'url', 'background', 'timeout'},
    'navigate_page': {'pageId', 'url', 'type', 'ignoreCache', 'timeout',
                      'handleBeforeUnload'},
    'take_snapshot': {'pageId', 'verbose'},
    'list_console_messages': {'pageId', 'pageSize', 'pageIdx', 'types',
                              'includePreservedMessages'},
    'lighthouse_audit': {'pageId', 'mode', 'device'},
    'get_css_styles': {'pageId', 'uid'},
}
PAGE_TOOLS = frozenset({
    'take_snapshot', 'list_console_messages', 'lighthouse_audit', 'get_css_styles',
})
_sessions = {}
_session_locks = {}


def _data_root():
    data_root = os.environ.get('CENTRAL_DATA_DIR')
    return (Path(data_root) if data_root else
            Path(__file__).resolve().parent.parent / 'data').resolve()


def browser_profile_path(user_id, project_id):
    root = _data_root() / 'browser_profiles'
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or root.resolve().parent != _data_root():
        raise RuntimeError('Diretório de perfis do navegador inválido.')
    profile = root / hashlib.sha256(
        (user_id + ':' + project_id).encode()).hexdigest()[:32]
    if profile.is_symlink():
        raise RuntimeError('Perfil do navegador inválido.')
    return profile


def clear_project_profile(db, user_id, project_id):
    active = db.one(
        "SELECT r.id FROM runs r JOIN conversations c ON c.id=r.conversation_id "
        "WHERE c.project_id=? AND r.user_id=? "
        "AND r.status IN ('queued','running','awaiting_approval') LIMIT 1",
        (project_id, user_id))
    if active:
        raise HTTPException(409, 'Finalize ou cancele as tarefas do projeto antes de apagar o perfil.')
    profile = browser_profile_path(user_id, project_id)
    if profile.exists():
        try:
            shutil.rmtree(profile)
        except OSError:
            raise HTTPException(
                409, 'O perfil está em uso ou não pôde ser removido. '
                     'Encerre as tarefas e tente novamente.') from None
    return {'project_id': project_id, 'removed': True}


def _loop_key(run_id):
    return id(asyncio.get_running_loop()), run_id


def _local_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in ('http', 'https') and
                parsed.hostname in ('localhost', '127.0.0.1', '::1') and
                not parsed.username and not parsed.password and
                parsed.port != 0 and not any(char.isspace() for char in value)
                and '\\' not in value)
    except ValueError:
        return False


def validate_request(request):
    if (not isinstance(request, dict) or request.get('action') != 'browser_tool'
            or request.get('tool') not in ALLOWED_TOOLS
            or not isinstance(request.get('arguments', {}), dict)):
        raise ValueError('Ferramenta DevTools ou argumentos não permitidos.')
    tool = request['tool']
    arguments = request.get('arguments', {})
    if set(arguments) - TOOL_ARGUMENTS[tool]:
        raise ValueError('Argumento DevTools não permitido.')
    if len(json.dumps(arguments, ensure_ascii=False)) > 8000:
        raise ValueError('Os argumentos DevTools excedem o limite permitido.')
    if tool in ('new_page', 'navigate_page') and not _local_url(arguments.get('url')):
        raise ValueError('O navegador da Central só pode abrir URLs HTTP(S) locais.')
    if tool == 'navigate_page' and arguments.get('type', 'url') != 'url':
        raise ValueError('Navegação por histórico ou reload não está disponível.')
    if tool == 'navigate_page' and 'pageId' not in arguments:
        raise ValueError('Informe pageId de uma página local listada.')
    if 'pageId' in arguments and (
            not isinstance(arguments['pageId'], int) or isinstance(arguments['pageId'], bool)):
        raise ValueError('Identificador de página inválido.')
    if 'timeout' in arguments and (
            not isinstance(arguments['timeout'], int) or isinstance(arguments['timeout'], bool) or
            not 1 <= arguments['timeout'] <= 30000):
        raise ValueError('Tempo limite fora do intervalo permitido.')
    for key in ('background', 'verbose', 'ignoreCache', 'includePreservedMessages'):
        if key in arguments and not isinstance(arguments[key], bool):
            raise ValueError('Argumento booleano DevTools inválido.')
    if 'pageSize' in arguments and (
            not isinstance(arguments['pageSize'], int) or isinstance(arguments['pageSize'], bool) or
            not 1 <= arguments['pageSize'] <= 50):
        raise ValueError('pageSize deve estar entre 1 e 50.')
    if 'pageIdx' in arguments and (
            not isinstance(arguments['pageIdx'], int) or isinstance(arguments['pageIdx'], bool) or
            not 0 <= arguments['pageIdx'] <= 100):
        raise ValueError('pageIdx fora do intervalo permitido.')
    if 'types' in arguments and (
            not isinstance(arguments['types'], list) or len(arguments['types']) > 5
            or any(value not in ('error', 'warn', 'info', 'log', 'debug')
                   for value in arguments['types'])):
        raise ValueError('Tipos de mensagem de console inválidos.')
    if 'mode' in arguments and arguments['mode'] not in ('navigation', 'snapshot'):
        raise ValueError('Modo Lighthouse inválido.')
    if 'device' in arguments and arguments['device'] not in ('desktop', 'mobile'):
        raise ValueError('Dispositivo Lighthouse inválido.')
    if 'handleBeforeUnload' in arguments and arguments['handleBeforeUnload'] not in (
            'accept', 'dismiss'):
        raise ValueError('Tratamento de navegação inválido.')
    if 'uid' in arguments and (
            not isinstance(arguments['uid'], str) or len(arguments['uid']) > 80):
        raise ValueError('UID DevTools inválido.')
    return tool, arguments


def approval_summary(request):
    tool, arguments = validate_request(request)
    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    return {'description': 'Chrome DevTools — ' + tool +
            ' (página local; aguardará aprovação). Argumentos: ' + encoded[:1200]}


def available(db, user_id):
    return bool(db.one(
        "SELECT id FROM ai_resources WHERE owner_id=? AND organization_id IS NULL "
        "AND kind='mcp' AND state='active' LIMIT 1", (user_id,)))


def worker_instruction(db, user_id, *, required=False):
    if not available(db, user_id):
        return ''
    instructions = (
        '\nChrome DevTools MCP está ativo para este usuário. Pode solicitar somente '
        'uma ferramenta local por vez usando '
        '{"action":"browser_tool","tool":"...","arguments":{...}}. Use '
        'list_pages com {} para obter pageId locais; new_page com {"url":"http://localhost:PORTA/"}; '
        'navigate_page com {"pageId":N,"url":"http://localhost:PORTA/"}; '
        'take_snapshot com {"pageId":N}; list_console_messages com {"pageId":N}; '
        'lighthouse_audit com {"pageId":N,"mode":"navigation","device":"desktop"}; '
        'get_css_styles com {"pageId":N,"uid":"UID"}. Somente HTTP(S) em '
        'localhost/127.0.0.1/::1; cada chamada aguarda aprovação explícita. '
        'Não alegue resultados sem ler a saída.'
    )
    if required:
        instructions += (
            '\nVALIDAÇÃO OBRIGATÓRIA DA TAREFA: depois da última alteração, abra ou '
            'selecione a URL local indicada pelo usuário e execute take_snapshot, '
            'list_console_messages e lighthouse_audit. Cada ação exige sua aprovação '
            'no chat. Corrija defeitos encontrados e repita as verificações após '
            'qualquer correção. Não finalize se o servidor local não estiver disponível; '
            'explique qual serviço o usuário precisa iniciar.'
        )
    return instructions


async def _open_session(db, user_id, run_id):
    from .computer_access import policy
    grant = policy(db, user_id)
    if grant['mode'] not in ('full', 'ask') or not grant['folder']:
        raise RuntimeError('Autorize uma pasta em Computador antes de usar o navegador.')
    if not available(db, user_id):
        raise RuntimeError('Ative a configuração oficial Chrome DevTools MCP em Recursos.')
    row = db.one(
        'SELECT c.project_id FROM runs r JOIN conversations c ON c.id=r.conversation_id '
        'WHERE r.id=? AND r.user_id=?', (run_id, user_id))
    project_id = row['project_id'] if row else None
    setting = db.one(
        'SELECT mode FROM project_browser_settings WHERE project_id=?',
        (project_id,)) if project_id else None
    mode = setting['mode'] if setting else 'run_isolated'

    args = ['--yes', SERVER_PACKAGE, '--headless']
    project_profile = None
    if mode == 'project_persistent' and project_id:
        other_run = db.one(
            "SELECT r.id FROM runs r JOIN conversations c ON c.id=r.conversation_id "
            "WHERE c.project_id=? AND r.user_id=? AND r.id<>? "
            "AND r.status IN ('queued','running','awaiting_approval') LIMIT 1",
            (project_id, user_id, run_id))
        if other_run:
            raise RuntimeError(
                'O perfil persistente já pode estar em uso por outra tarefa do projeto. '
                'Finalize-a ou escolha sessão isolada.')
        project_profile = browser_profile_path(user_id, project_id)
        project_profile.mkdir(parents=True, exist_ok=True)
    else:
        args.append('--isolated')
    args.append('--experimentalNavigationAllowlist')

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    stack = AsyncExitStack()
    try:
        await stack.__aenter__()
        inherited = ('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'HOME',
                     'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')
        env = {key: os.environ[key] for key in inherited if key in os.environ}
        env.update({'CI': '1', 'CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS': '1'})
        if project_profile:
            env['HOME'] = str(project_profile.resolve())
            env['USERPROFILE'] = str(project_profile.resolve())
        command, command_args = _npx_command(args)
        read_stream, write_stream = await stack.enter_async_context(stdio_client(
            StdioServerParameters(command=command, args=command_args, env=env)))
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream))
        await asyncio.wait_for(session.initialize(), timeout=90)
        return {'stack': stack, 'session': session, 'lock': asyncio.Lock()}
    except BaseException:
        await stack.aclose()
        raise


def _pages(result):
    structured = getattr(result, 'structuredContent', None) or {}
    return structured.get('pages', []) if isinstance(structured, dict) else []


def _page_is_local(page):
    return isinstance(page, dict) and _local_url(page.get('url'))


def _page_id(page):
    return page.get('id') if isinstance(page, dict) else None


def _npx_command(args):
    npx = shutil.which('npx')
    if not npx:
        raise RuntimeError('npx não foi encontrado; instale Node.js para usar Chrome DevTools.')
    if os.name == 'nt':
        node = shutil.which('node')
        cli = Path(npx).resolve().parent / 'node_modules' / 'npm' / 'bin' / 'npx-cli.js'
        if not node or not cli.is_file():
            raise RuntimeError('Não foi possível localizar Node.js/npx para iniciar o MCP fixado.')
        return node, [str(cli), *args]
    return npx, args


async def _call(session, tool, arguments):
    listing = await session.call_tool('list_pages', {})
    pages = _pages(listing)
    if tool == 'list_pages':
        local = [{'pageId': _page_id(page), 'url': page['url'],
                  'selected': bool(page.get('selected'))}
                 for page in pages if _page_is_local(page)]
        return {'success': True, 'pages': local}
    before_ids = {_page_id(page) for page in pages}
    if tool in ('new_page', 'navigate_page'):
        arguments = dict(arguments)
        arguments['allowList'] = NAVIGATION_ALLOWLIST
        if tool == 'navigate_page':
            page_id = arguments.get('pageId')
            if not any(_page_id(page) == page_id and _page_is_local(page)
                       for page in pages):
                raise ValueError('A página selecionada não é um endereço local autorizado.')
    elif tool in PAGE_TOOLS:
        arguments = dict(arguments)
        page_id = arguments.get('pageId')
        page = (next((item for item in pages if _page_id(item) == page_id), None)
                if page_id is not None else
                next((item for item in pages if item.get('selected')), None))
        if not _page_is_local(page) and page_id is None:
            page = next((item for item in pages if _page_is_local(item)), None)
            if page:
                page_id = _page_id(page)
                arguments['pageId'] = page_id
        if not _page_is_local(page):
            raise ValueError('A página selecionada não é um endereço local autorizado.')

    available_tools = await session.list_tools()
    if tool not in {item.name for item in available_tools.tools}:
        raise RuntimeError('A ferramenta não está disponível nesta versão do servidor.')
    result = await asyncio.wait_for(
        session.call_tool(tool, arguments), timeout=120)
    if getattr(result, 'isError', False):
        details = '\n'.join(
            getattr(block, 'text', '') for block in getattr(result, 'content', []) or []
            if getattr(block, 'type', '') == 'text'
        ).strip()
        suffix = ': ' + details[:1000] if details else ''
        raise RuntimeError('O servidor Chrome DevTools retornou erro' + suffix)
    if tool in ('new_page', 'navigate_page'):
        after = _pages(result)
        page_id = arguments.get('pageId')
        target = (next((page for page in after if _page_id(page) == page_id), None)
                  if tool == 'navigate_page' else
                  next((page for page in after if _page_id(page) not in before_ids), None))
        if target and not _page_is_local(target):
            await session.call_tool('close_page', {'pageId': _page_id(target)})
            raise RuntimeError('A navegação saiu do endereço local permitido; a aba foi fechada.')
    content = []
    for block in getattr(result, 'content', []) or []:
        if getattr(block, 'type', '') == 'text':
            content.append(getattr(block, 'text', ''))
    structured = getattr(result, 'structuredContent', None)
    output = {'text': '\n'.join(content)[:8000]}
    if isinstance(structured, dict):
        output['data'] = structured
    return {'success': True, 'output': json.dumps(output, ensure_ascii=False)[:10000]}


async def execute(db, user_id, run_id, request):
    tool, arguments = validate_request(request)
    if not available(db, user_id):
        raise RuntimeError('O Chrome DevTools MCP foi desativado para este usuário.')
    key = _loop_key(run_id)
    creation_lock = _session_locks.setdefault(key, asyncio.Lock())
    async with creation_lock:
        runtime = _sessions.get(key)
        if runtime is None:
            runtime = await _open_session(db, user_id, run_id)
            _sessions[key] = runtime
        async with runtime['lock']:
            return await _call(runtime['session'], tool, arguments)


async def close_run(run_id):
    loop_id = id(asyncio.get_running_loop())
    key = (loop_id, run_id)
    runtime = _sessions.pop(key, None)
    _session_locks.pop(key, None)
    if runtime:
        await runtime['stack'].aclose()


async def close_all():
    loop_id = id(asyncio.get_running_loop())
    entries = [(key, value) for key, value in list(_sessions.items())
               if key[0] == loop_id]
    for key, runtime in entries:
        _sessions.pop(key, None)
        _session_locks.pop(key, None)
        await runtime['stack'].aclose()
