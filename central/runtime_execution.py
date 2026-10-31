"""Pinned CLI text planners. Native tools denied; Central executes action JSON.

Operator-owned binaries are trusted software, not an OS security sandbox.
No user HOME/config, automatic login, arbitrary argv or workspace is forwarded.
"""
import asyncio
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import sys
import threading
import time

from .external_runtimes import RuntimeBlocked, _connection, _isolated_environment, _object_pairs, _invalid_constant
from .external_runtimes import _read_version

VERSIONS = {'claude': '2.1.316', 'gemini': '0.66.0', 'opencode': '1.19.5'}
KINDS = {'claude_cli': 'claude', 'gemini_cli': 'gemini', 'opencode_cli': 'opencode', 'acp': 'acp'}
MAX_TEXT = 128000
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}\Z')


def _file(path):
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        raise RuntimeBlocked('runtime_not_installed')
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise RuntimeBlocked('invalid_executable')
    return path


def command(runtime):
    """Only fixed installed package entrypoints; no browser-supplied executable."""
    if runtime == 'acp':
        if os.environ.get('CENTRAL_ACP_BACKEND', 'gemini') != 'gemini':
            raise RuntimeBlocked('acp_backend_required')
        runtime = 'gemini'
    if runtime not in VERSIONS:
        raise RuntimeBlocked('unknown_runtime')
    root = os.environ.get('CENTRAL_RUNTIME_TOOLS_DIR')
    if root is None and os.environ.get('LOCALAPPDATA'):
        root = str(Path(os.environ['LOCALAPPDATA']) / 'Central IA/runtime-tools')
    if not root or not Path(root).is_absolute():
        raise RuntimeBlocked('runtime_tools_not_configured')
    root = Path(root) / 'node_modules'
    packages = {'claude': ('@anthropic-ai/claude-code', '@anthropic-ai/claude-code-win32-x64/claude.exe'),
                'gemini': ('@google/gemini-cli', '@google/gemini-cli/bundle/gemini.js'),
                'opencode': ('opencode-ai', 'opencode-windows-x64/bin/opencode.exe')}
    package, executable = packages[runtime]
    try:
        manifest = json.loads(_file(root / package / 'package.json').read_text(encoding='utf-8'))
    except (ValueError, OSError):
        raise RuntimeBlocked('invalid_installation') from None
    if manifest.get('name') != package or manifest.get('version') != VERSIONS[runtime]:
        raise RuntimeBlocked('unsupported_version')
    executable = _file(root / executable)
    if runtime == 'gemini':
        node = os.environ.get('CENTRAL_RUNTIME_NODE') or shutil.which('node')
        if not node:
            raise RuntimeBlocked('node_not_found')
        return [str(_file(node)), str(executable)]
    if os.name != 'nt':
        raise RuntimeBlocked('platform_not_supported')
    return [str(executable)]


def inventory():
    result = {}
    for runtime in (*VERSIONS, 'acp'):
        try:
            command(runtime)
            status = 'configured'
        except RuntimeBlocked as exc:
            status = str(exc)
        result[runtime] = {'status': status, 'execution_implemented': True,
                           'version': VERSIONS.get(runtime, VERSIONS['gemini']),
                           'native_tools': False, 'authentication': 'api_key',
                           'os_sandbox': False, 'inference_homologated': False}
    return result


def verify(runtime, timeout=10, cancel_event=None):
    argv = command(runtime)
    expected = VERSIONS['gemini' if runtime == 'acp' else runtime]
    pattern = r'(\d+\.\d+\.\d+)' + (r' \(Claude Code\)' if runtime == 'claude' else '')
    with _connection(argv + ['--version'], time.monotonic() + timeout, cancel_event) as process:
        if _read_version(process, pattern) != expected:
            raise RuntimeBlocked('unsupported_version')
    return expected


def _write(path, value):
    Path(path).write_text(json.dumps(value), encoding='utf-8')


def prepare(runtime, model, api_key, home):
    argv = command(runtime)
    env = _isolated_environment(home)
    base = Path(home)
    if runtime == 'claude':
        # Managed hooks can survive bare mode. Reject such installations rather
        # than claiming user settings flags override administrative policy.
        managed = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'ClaudeCode'
        if managed.exists() and any(managed.iterdir()):
            raise RuntimeBlocked('managed_policy_present')
        if os.name == 'nt':
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, r'SOFTWARE\Policies\ClaudeCode'):
                        raise RuntimeBlocked('managed_policy_present')
                except FileNotFoundError:
                    pass
        _write(base / 'mcp.json', {'mcpServers': {}})
        env.update(ANTHROPIC_API_KEY=api_key, CLAUDE_CONFIG_DIR=str(base / '.claude'),
                   DISABLE_AUTOUPDATER='1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
        return argv + ['--print', '--bare', '--restricted', '--tools', '', '--disallowedTools', '*',
                       '--setting-sources', '', '--strict-mcp-config', '--mcp-config', str(base / 'mcp.json'),
                       '--no-session-persistence', '--max-turns', '1', '--model', model,
                       '--output-format', 'stream-json', '--verbose'], env
    if runtime in ('gemini', 'acp'):
        managed = (Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'gemini-cli' if os.name == 'nt'
                   else Path('/Library/Application Support/GeminiCli' if sys.platform == 'darwin' else '/etc/gemini-cli'))
        if managed.exists() and any(managed.iterdir()):
            raise RuntimeBlocked('managed_policy_present')
        settings = {'admin': {'secureModeEnabled': True, 'extensions': {'enabled': False},
                             'mcp': {'enabled': False}, 'skills': {'enabled': False}},
                    'hooksConfig': {'enabled': False}, 'skills': {'enabled': False},
                    'mcpServers': {}, 'telemetry': {'enabled': False},
                    'privacy': {'usageStatisticsEnabled': False},
                    'advanced': {'ignoreLocalEnv': True},
                    'security': {'auth': {'selectedType': 'gemini-api-key'}},
                    'general': {'maxAttempts': 1}}
        _write(base / 'settings.json', settings)
        (base / '.gemini').mkdir()
        _write(base / '.gemini/settings.json', settings)
        (base / 'deny.toml').write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n', encoding='utf-8')
        env.update(GEMINI_API_KEY=api_key, GEMINI_CLI_HOME=home,
                   GEMINI_CLI_SYSTEM_SETTINGS_PATH=str(base / 'absent-system.json'),
                   GEMINI_CLI_SYSTEM_DEFAULTS_PATH=str(base / 'absent-defaults.json'))
        args = ['--model', model, '--skip-trust', '--policy', str(base / 'deny.toml')]
        return (argv + args + (['--acp'] if runtime == 'acp' else
                ['--output-format', 'stream-json', '--prompt', 'Respond to the supplied Central context only.'])), env
    provider, separator, identifier = model.partition('/')
    if not separator or provider not in ('groq', 'google', 'anthropic', 'openai', 'openrouter'):
        raise RuntimeBlocked('opencode_provider_required')
    config = {'$schema': 'https://opencode.ai/config.json', 'permission': 'deny', 'plugin': [], 'mcp': {},
              'agent': {'central': {'mode': 'primary', 'description': 'Central text planner',
                  'prompt': 'Return only the response requested by the supplied Central system and messages. All actions are JSON text for Central. Never call native tools or functions.',
                  'tools': {'*': False}, 'permission': 'deny'}},
              'provider': {provider: {'models': {identifier: {'name': identifier}},
                                     'options': {'apiKey': '{env:CENTRAL_RUNTIME_API_KEY}'}}}}
    _write(base / 'opencode.json', config)
    env.update(CENTRAL_RUNTIME_API_KEY=api_key, OPENCODE_CONFIG=str(base / 'opencode.json'),
               OPENCODE_CONFIG_DIR=home, OPENCODE_DISABLE_AUTOUPDATE='true',
               OPENCODE_DISABLE_PRUNE='true')
    return argv + ['run', '--pure', '--agent', 'central', '--format', 'json', '--model', model,
                   'Respond to the supplied Central context only.'], env


def _json(line):
    try:
        result = json.loads(line.decode('utf-8'), object_pairs_hook=_object_pairs, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise RuntimeBlocked('protocol_error') from None
    if not isinstance(result, dict):
        raise RuntimeBlocked('protocol_error')
    return result


def _failure(event):
    """Classify only failure metadata; never return CLI error bodies or tokens."""
    error = event.get('error')
    error = error if isinstance(error, dict) else {}
    data = error.get('data')
    data = data if isinstance(data, dict) else {}
    code = error.get('code', error.get('status', data.get('statusCode')))
    if code == 413:
        return 'input_limit'
    if code in (401, 403) or error.get('type') in ('AuthenticationError', 'AuthError'):
        return 'authentication_required'
    if code == 429 or error.get('type') in ('RateLimitError', 'QuotaExceededError'):
        return 'runtime_rate_limit'
    if code == 404:
        return 'runtime_model_unavailable'
    return 'runtime_request_failed'


def cli_reply(process, runtime):
    chunks, size, finished = [], 0, False
    while True:
        line = process.receive()
        if line is None:
            break
        event = _json(line)
        kind = event.get('type')
        text = ''
        if event.get('tool_calls') or (isinstance(event.get('message'), dict) and event['message'].get('tool_calls')):
            raise RuntimeBlocked('native_tools_requested')
        if kind in ('tool_use', 'tool_call', 'tool_result'):
            raise RuntimeBlocked('native_tools_requested')
        if runtime == 'claude':
            if kind == 'system' and event.get('subtype') == 'init' and event.get('tools'):
                raise RuntimeBlocked('native_tools_enabled')
            if kind == 'assistant':
                message = event.get('message')
                if not isinstance(message, dict) or not isinstance(message.get('content', []), list):
                    raise RuntimeBlocked('protocol_error')
                for part in message.get('content', []):
                    if not isinstance(part, dict):
                        raise RuntimeBlocked('protocol_error')
                    if part.get('type') in ('tool_use', 'server_tool_use', 'mcp_tool_use', 'tool_result'):
                        raise RuntimeBlocked('native_tools_requested')
            if kind == 'result':
                if event.get('is_error') or event.get('subtype') != 'success':
                    raise RuntimeBlocked(_failure(event))
                text, finished = event.get('result', ''), True
        elif runtime == 'gemini':
            if kind == 'message' and event.get('role') == 'assistant':
                text = event.get('content', '')
            if kind == 'result':
                if event.get('status') != 'success':
                    raise RuntimeBlocked(_failure(event))
                finished = True
            if kind == 'error':
                raise RuntimeBlocked(_failure(event))
        else:
            if kind == 'text':
                part = event.get('part')
                if not isinstance(part, dict):
                    raise RuntimeBlocked('protocol_error')
                text = part.get('text', '')
            if kind == 'step_finish':
                finished = True
            if kind == 'error':
                raise RuntimeBlocked(_failure(event))
        if not isinstance(text, str):
            raise RuntimeBlocked('protocol_error')
        size += len(text)
        if size > MAX_TEXT:
            raise RuntimeBlocked('output_limit')
        chunks.append(text)
    while process.process.poll() is None:
        process.check()
        time.sleep(.01)
    if process.process.returncode != 0 or not finished or not ''.join(chunks).strip():
        raise RuntimeBlocked('runtime_request_failed')
    return ''.join(chunks)


def _rpc(process, identifier, method, params, session=None):
    process.send({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params})
    chunks = []
    size = 0
    for _ in range(128):
        line = process.receive()
        if line is None or not line.endswith(b'\n'):
            raise RuntimeBlocked('disconnected')
        value = _json(line)
        if value.get('jsonrpc') != '2.0':
            raise RuntimeBlocked('protocol_error')
        if 'method' in value:
            if 'result' in value or 'error' in value:
                raise RuntimeBlocked('protocol_error')
            if 'id' in value:
                incoming = value['id']
                if type(incoming) not in (str, int) or len(str(incoming)) > 128:
                    raise RuntimeBlocked('protocol_error')
                if value['method'] == 'session/request_permission':
                    process.send({'jsonrpc': '2.0', 'id': incoming, 'result': {'outcome': {'outcome': 'cancelled'}}})
                else:
                    process.send({'jsonrpc': '2.0', 'id': incoming,
                                  'error': {'code': -32601, 'message': 'Client method not supported'}})
                raise RuntimeBlocked('native_tools_requested')
            if value['method'] == 'session/update':
                data = value.get('params', {})
                if not isinstance(data, dict) or not isinstance(data.get('update', {}), dict):
                    raise RuntimeBlocked('protocol_error')
                update = data.get('update', {})
                if session is None and update.get('sessionUpdate') in (
                        'available_commands_update', 'current_mode_update', 'config_option_update', 'session_info_update'):
                    continue
                if session is None or data.get('sessionId') != session:
                    raise RuntimeBlocked('protocol_error')
                if update.get('sessionUpdate') in ('tool_call', 'tool_call_update'):
                    raise RuntimeBlocked('native_tools_requested')
                if update.get('sessionUpdate') == 'agent_message_chunk':
                    block = update.get('content', {})
                    if block.get('type') != 'text' or not isinstance(block.get('text'), str):
                        raise RuntimeBlocked('protocol_error')
                    text = block['text']; size += len(text)
                    if size > MAX_TEXT:
                        raise RuntimeBlocked('output_limit')
                    chunks.append(text)
            continue
        if type(value.get('id')) is not int or value['id'] != identifier or 'error' in value:
            raise RuntimeBlocked('rpc_error')
        result = value.get('result')
        if not isinstance(result, dict):
            raise RuntimeBlocked('protocol_error')
        return result, ''.join(chunks)
    raise RuntimeBlocked('output_limit')


def acp_reply(process, context, home):
    initialized, _ = _rpc(process, 1, 'initialize', {'protocolVersion': 1,
        'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False},
        'clientInfo': {'name': 'central-text-planner', 'version': '1.0.0'}})
    if type(initialized.get('protocolVersion')) is not int or initialized['protocolVersion'] != 1:
        raise RuntimeBlocked('unsupported_protocol')
    if not isinstance(initialized.get('agentCapabilities'), dict):
        raise RuntimeBlocked('protocol_error')
    identifier = 2
    methods = initialized.get('authMethods', [])
    if not isinstance(methods, list) or len(methods) > 32 or any(not isinstance(method, dict) for method in methods):
        raise RuntimeBlocked('protocol_error')
    if any(isinstance(method, dict) and method.get('id') == 'gemini-api-key' for method in methods):
        _rpc(process, identifier, 'authenticate', {'methodId': 'gemini-api-key'})
        identifier += 1
    session, _ = _rpc(process, identifier, 'session/new', {'cwd': home, 'mcpServers': []})
    sid = session.get('sessionId')
    if not isinstance(sid, str) or not 0 < len(sid) <= 256 or any(ord(char) < 32 for char in sid):
        raise RuntimeBlocked('protocol_error')
    try:
        result, text = _rpc(process, identifier + 1, 'session/prompt', {'sessionId': sid,
                            'prompt': [{'type': 'text', 'text': context}]}, sid)
    except RuntimeBlocked as exc:
        if str(exc) == 'cancelled':
            # Best-effort protocol cancellation before killing our owned tree.
            try:
                process.outgoing.put_nowait((json.dumps({'jsonrpc': '2.0', 'method': 'session/cancel',
                    'params': {'sessionId': sid}}) + '\n').encode())
                time.sleep(.03)
            except queue.Full:
                pass
        raise
    if result.get('stopReason') != 'end_turn' or not text.strip():
        raise RuntimeBlocked('runtime_request_failed')
    return text


def stream(runtime, model, system, messages, *, api_key, timeout=60, cancel_event=None):
    if os.environ.get('CENTRAL_DEPLOYMENT_MODE', 'local') != 'local':
        raise RuntimeBlocked('server_mode_refused')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise RuntimeBlocked('invalid_timeout')
    deadline = time.monotonic() + timeout
    command(runtime)  # resolve before touching private prompt data
    verify(runtime, timeout=min(timeout, 10), cancel_event=cancel_event)
    if not isinstance(model, str) or not MODEL.fullmatch(model):
        raise RuntimeBlocked('invalid_model')
    if not isinstance(api_key, str) or not api_key or len(api_key) > 16384 or any(ord(c) < 32 for c in api_key):
        raise RuntimeBlocked('authentication_required')
    if not isinstance(system, str) or not isinstance(messages, list) or any(
            not isinstance(m, dict) or m.get('role') not in ('user', 'assistant', 'system')
            or not isinstance(m.get('content'), str) for m in messages):
        raise RuntimeBlocked('invalid_prompt')
    context = json.dumps({'system': system, 'messages': messages}, ensure_ascii=False)
    if len(context.encode('utf-8')) > 256 * 1024:
        raise RuntimeBlocked('input_limit')
    home_path = []
    def configure(home):
        home_path.append(home)
        return prepare(runtime, model, api_key, home)
    with _connection([], deadline, cancel_event, prepare=configure) as process:
        if runtime == 'acp':
            text = acp_reply(process, context, home_path[0])
        else:
            process.send_text(context + '\n')
            text = cli_reply(process, runtime)
        yield text.replace(api_key, '[redacted]')


async def stream_response(provider, key, model, system, messages, *, timeout=90):
    from .providers import ProviderError
    runtime = KINDS.get(provider['kind'])
    stopped = threading.Event()
    output = queue.Queue(maxsize=2)
    def run():
        try:
            for text in stream(runtime, model, system, messages, api_key=key,
                               timeout=timeout, cancel_event=stopped):
                if not stopped.is_set():
                    output.put(('text', text), timeout=1)
            output.put(('done', None), timeout=1)
        except RuntimeBlocked as exc:
            output.put(('error', str(exc)), timeout=1)
        except Exception:
            output.put(('error', 'runtime_unavailable'), timeout=1)
    worker = threading.Thread(target=run, name='central-runtime-execution', daemon=True)
    worker.start()
    try:
        while True:
            try:
                kind, value = await asyncio.to_thread(output.get, True, .05)
            except queue.Empty:
                continue
            if kind == 'done':
                return
            if kind == 'error':
                category = {'authentication_required': 'authentication', 'runtime_rate_limit': 'rate_limit',
                            'runtime_model_unavailable': 'request', 'timeout': 'timeout'}.get(value, 'response')
                status = {'input_limit': 413, 'runtime_rate_limit': 429,
                          'authentication_required': 401, 'runtime_model_unavailable': 404}.get(value)
                raise ProviderError(category, 'Runtime local: ' + value,
                                    value in ('runtime_rate_limit', 'timeout'), status)
            yield value
    finally:
        stopped.set()
        await asyncio.to_thread(worker.join, 5)
        if worker.is_alive():
            raise ProviderError('internal', 'Runtime local nao confirmou encerramento.', False)
