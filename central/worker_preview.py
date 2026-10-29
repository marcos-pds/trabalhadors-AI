"""Run-owned preview adapter; approval decisions belong to the caller's gateway.

No approvals are issued here. Ownership is process-local, like live_preview.
"""
import asyncio
import json
import re
import threading

from fastapi import HTTPException

from . import live_preview
from .computer_access import RESTRICTED_NAMES
from .workspace_guard import enforce_run_scope, enforce_host_command_policy
from .workspace_tools import target

_LOCK = threading.RLock()
_OWNED = {}
_COMPONENT = re.compile(r'[A-Za-z0-9_. -]{1,64}\Z')
_DEVICES = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)),
            *(f'lpt{i}' for i in range(1, 10))}


def validate_request(request):
    """Return a copy; ValueError on extra keys, invalid types or unsafe cwd."""
    if (not isinstance(request, dict)
            or set(request) - {'action', 'operation', 'cwd'}
            or request.get('action') != 'preview'
            or not isinstance(request.get('operation'), str)
            or request['operation'] not in ('start', 'status', 'stop')):
        raise ValueError('Use preview com operation start, status ou stop.')
    if 'cwd' in request:
        cwd = request['cwd']
        if not isinstance(cwd, str) or len(cwd) > 240:
            raise ValueError('cwd deve ser um caminho relativo de ate 240 caracteres.')
        parts = cwd.split('/') if cwd else []
        if len(parts) > 12 or any(
                not _COMPONENT.fullmatch(part) or part in ('.', '..')
                or part != part.strip() or part.endswith('.')
                or part.lower() in RESTRICTED_NAMES or part.lower().startswith('.env')
                or part.split('.')[0].lower() in _DEVICES for part in parts):
            raise ValueError('cwd fora do workspace ou reservado.')
    result = dict(request)
    if result['operation'] == 'start':
        result.setdefault('cwd', '')
    return result


def _authorize(db, user_id, run_id, *, start=False, step_id=None):
    folder = enforce_run_scope(db, user_id, run_id, write=True)
    binding = db.one('SELECT * FROM run_workspace_bindings WHERE run_id=?', (run_id,))
    if (not binding or binding['user_id'] != user_id or binding['folder'] != folder):
        raise HTTPException(409, 'A previa exige um workspace vinculado a tarefa.')
    if start:
        enforce_host_command_policy(db, user_id, run_id)
    if step_id is not None:
        from .step_scope import execution_folder
        folder = execution_folder(db, user_id, run_id, step_id, write=start)
    return folder


def _execute(db, user_id, run_id, request, cancelled, step_id=None):
    operation = request['operation']
    with _LOCK:
        if cancelled.is_set():
            return {'status': 'stopped'}
        folder = _authorize(db, user_id, run_id, start=operation == 'start', step_id=step_id)
        key = (id(db), user_id, run_id)
        owned = _OWNED.get(key)
        if owned:
            if owned['folder'] != folder:
                raise HTTPException(409, 'O workspace da previa mudou.')
            if 'cwd' in request and request['cwd'] != owned['cwd']:
                raise HTTPException(409, 'cwd nao corresponde a previa desta tarefa.')
            # Verify the actual session, not just a remembered URL or user ID.
            with live_preview._LOCK:
                entry = live_preview._SESSIONS.get(user_id)
                if entry is not owned['entry']:
                    _OWNED.pop(key, None)
                    owned = None
                elif (entry.get('folder') != folder or entry.get('cwd') != owned['cwd']
                      or entry.get('owner') is not owned['token']):
                    raise HTTPException(409, 'A previa nao corresponde ao workspace da tarefa.')
        if operation == 'start' and owned:
            if live_preview.info(user_id, expected=owned['entry'])['status'] != 'running':
                _OWNED.pop(key, None)
                owned = None
        if operation == 'start' and not owned:
            cwd = request['cwd']
            target(folder, cwd, directory=True)
            token = object()

            def authorize():
                return _authorize(db, user_id, run_id, start=True, step_id=step_id) == folder

            live_preview.start(db, user_id, cwd, owner=token,
                               authorize=authorize, expected_folder=folder)
            with live_preview._LOCK:
                entry = live_preview._SESSIONS.get(user_id)
                if (not entry or entry.get('owner') is not token
                        or entry.get('folder') != folder or entry.get('cwd') != cwd):
                    raise HTTPException(409, 'A previa foi substituida durante inicializacao.')
                if cancelled.is_set():
                    live_preview.stop(user_id, expected=entry)
                    return {'status': 'stopped'}
                owned = dict(db=db, folder=folder, cwd=cwd, token=token, entry=entry)
                _OWNED[key] = owned
        if not owned:
            # Never inspect/adopt/stop a UI preview or another database/run.
            return {'status': 'stopped'}
        target(folder, owned['cwd'], directory=True)
        if operation == 'stop':
            result = live_preview.stop(user_id, expected=owned['entry'])
            _OWNED.pop(key, None)
            return result
        result = live_preview.info(user_id, expected=owned['entry'])
        if result['status'] == 'running':
            if result.get('folder') != folder or result.get('cwd') != owned['cwd']:
                raise HTTPException(409, 'Informacao da previa fora do workspace.')
        else:
            _OWNED.pop(key, None)
        return result


async def execute(db, user_id, run_id, request, *, step_id=None):
    """Execute an already gateway-approved request off the event loop."""
    request = validate_request(request)
    cancelled = threading.Event()
    try:
        result = await asyncio.to_thread(_execute, db, user_id, run_id, request, cancelled, step_id)
        result = dict(result, success=True)
        result['output'] = json.dumps(
            {key: result[key] for key in ('status', 'url', 'cwd') if key in result},
            ensure_ascii=False)
        return result
    except asyncio.CancelledError:
        cancelled.set()
        # A cancelled to_thread keeps running; queue cleanup behind its lock.
        await asyncio.shield(close_run(run_id))
        raise


def _close_run(run_id):
    with _LOCK:
        for key, owned in list(_OWNED.items()):
            if key[2] == run_id:
                live_preview.stop(key[1], expected=owned['entry'])
                _OWNED.pop(key, None)
    return {'status': 'stopped'}


async def close_run(run_id):
    """Internal cleanup after completion/revocation; no tool authorization bypass.

    Stops only exact sessions owned by this run in this process, across DBs.
    """
    return await asyncio.to_thread(_close_run, run_id)


def worker_instruction():
    return ('Para testar o projeto, use {"action":"preview","operation":"start",'
            '"cwd":""} (ou cwd relativo do projeto com npm dev). Abra a URL local '
            'retornada nas ferramentas de navegador, examine console e interface, '
            'corrija erros e teste novamente. Use {"action":"preview",'
            '"operation":"status"} para consultar e {"action":"preview",'
            '"operation":"stop"} apenas antes de reiniciar a previa ou quando solicitado '
            'explicitamente. Mantenha a previa ativa para verificacao independente; '
            'o motor encerra a previa no fim do run. Nao execute shell para iniciar servidores. '
            'Estas acoes continuam sujeitas a autorizacao do gateway.')
