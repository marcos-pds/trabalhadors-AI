"""Opt-in per-step Git workspaces and operator-only, one-use text promotion.

Routing is not an OS sandbox. review/approve are operator APIs, never worker tools.
No commits, merges, resets, dirty-tree removal, or automatic approvals occur here.
"""
from contextlib import contextmanager
import difflib
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import time

from fastapi import HTTPException

from .computer_access import allowed_folder, policy
from .database import utcnow
from .workspace_guard import enforce_run_scope, current_organization
from .worker_worktrees import (_repo, _paths, _registered, _git, _ignore_container,
                               _MUTEX, WorktreeError)
from .worker_worktree_reviews import (_safe_path, _parents, _MAX_FILES,
                                    _MAX_FILE_BYTES, _MAX_TOTAL_BYTES,
                                    _EXPIRY_SECONDS, _VALID_STATUS)

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS isolated_workspace_runs("
    "run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,"
    "user_id TEXT NOT NULL REFERENCES users(id),organization_id TEXT,"
    "root TEXT NOT NULL,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),"
    "head TEXT NOT NULL,approved_json TEXT NOT NULL DEFAULT '{}',"
    "created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS isolated_workspace_steps("
    "run_id TEXT NOT NULL REFERENCES isolated_workspace_runs(run_id) ON DELETE CASCADE,"
    "step_id TEXT NOT NULL REFERENCES steps(id) ON DELETE CASCADE,"
    "user_id TEXT NOT NULL REFERENCES users(id),folder TEXT NOT NULL,head TEXT NOT NULL,"
    "state TEXT NOT NULL CHECK(state IN ('preparing','active','unchanged',"
    "'pending_review','reviewed','applying','approved','manual_recovery')),"
    "baseline_json TEXT NOT NULL DEFAULT '{}',seed_json TEXT NOT NULL DEFAULT '[]',"
    "review_json TEXT,token_hash TEXT,expires_at REAL,"
    "created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(run_id,step_id))",
    "CREATE INDEX IF NOT EXISTS idx_isolated_workspace_state "
    "ON isolated_workspace_steps(run_id,state)",
)
_IMPLEMENTERS = {'code', 'frontend', 'backend'}
_PENDING = {'preparing', 'active', 'pending_review', 'reviewed', 'applying', 'manual_recovery'}
_EXECUTABLE = {'queued', 'running', 'awaiting_approval'}
_PARKED = {'awaiting_integration', 'paused_operator'}


def _fail(detail, code=409):
    raise HTTPException(code, detail)


def _sha(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _scope(db, user, rid, *, parked=()):
    run = db.one('SELECT * FROM runs WHERE id=?', (rid,))
    if not run or run['user_id'] != user:
        _fail('Tarefa nao encontrada para esta conta.', 404)
    if run['status'] not in parked:
        folder = enforce_run_scope(db, user, rid, write=True)
    else:
        # Operator/resume access to parked tasks must not revive worker tools.
        grant = policy(db, user)
        if grant['mode'] not in ('full', 'ask') or not grant['folder']:
            _fail('Permissao de computador bloqueada.', 403)
        folder = allowed_folder(grant['folder'])
        org = current_organization(db, rid)
        if org:
            from .organizations import require_org
            require_org(db, org, user, write=True)
    binding = db.one('SELECT * FROM run_workspace_bindings WHERE run_id=?', (rid,))
    from .sandbox_executor import backend
    if (not binding or binding['user_id'] != user or binding['folder'] != folder
            or binding['organization_id'] != current_organization(db, rid)
            or binding['command_runner'] != backend()):
        _fail('Workspace original, organizacao ou executor mudou; operacao bloqueada.')
    config = db.one('SELECT * FROM isolated_workspace_runs WHERE run_id=?', (rid,))
    if config and (config['user_id'] != user or config['root'] != folder
                   or config['organization_id'] != binding['organization_id']):
        _fail('A configuracao de isolamento nao corresponde ao vinculo original.')
    return Path(folder), config


def _step(db, user, rid, sid, *, execution=False):
    step = db.one('SELECT * FROM steps WHERE id=? AND run_id=?', (sid, rid))
    if not step:
        _fail('Etapa nao pertence a tarefa.', 404)
    if execution and step['status'] not in _EXECUTABLE:
        _fail('Etapa nao esta ativa para executar ferramentas.')
    if not execution and step['status'] in ('cancelled', 'failed', 'paused_limit'):
        _fail('Etapa interrompida; retome antes de integrar.')
    role = None
    if step['kind'] == 'agent':
        agent = db.one('SELECT * FROM agents WHERE id=? AND user_id=?', (step['agent_id'], user))
        if not agent:
            _fail('Agente da etapa nao pertence a conta.', 404)
        from .agent_registry import effective_specialty
        role = effective_specialty(agent)
    return step, role


def _session(db, rid, sid):
    return db.one('SELECT * FROM isolated_workspace_steps WHERE run_id=? AND step_id=?', (rid, sid))


@contextmanager
def _locked(root):
    # O_EXCL is shared by API/worker processes and all runs in this repository.
    # A real crash leaves this marker for explicit operator recovery.
    with _MUTEX:
        root = _repo(root)
        marker = root / '.git' / 'central-isolation.lock'
        try:
            fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            _fail('Outra operacao de isolamento esta ativa ou exige recuperacao manual.')
        os.close(fd)
        try:
            yield
        finally:
            marker.unlink(missing_ok=True)


def _verify(root, config, row, rid, sid):
    if row['state'] in ('preparing', 'applying', 'manual_recovery'):
        _fail('Estado interrompido exige revisao manual; nao repita automaticamente.')
    _, _, worker = _paths(root, rid, sid)
    if (row['user_id'] != config['user_id'] or row['folder'] != str(worker)
            or not worker.is_dir() or not _registered(root, worker)):
        _fail('Worktree persistido nao corresponde a etapa.')
    if (_git(root, 'rev-parse', 'HEAD') != config['head']
            or row['head'] != config['head']
            or _git(worker, 'rev-parse', 'HEAD') != config['head']):
        _fail('HEAD da base ou do trabalhador mudou.')
    return worker


def _blocking(db, rid, except_sid=None):
    return [row for row in db.all('SELECT step_id,state FROM isolated_workspace_steps WHERE run_id=?', (rid,))
            if row['step_id'] != except_sid and row['state'] in _PENDING]


def configure_run(db, user, rid, enabled):
    """Configure before preparation. Safe inside caller's BEGIN; never commits."""
    if type(enabled) is not bool:
        _fail('enabled deve ser booleano.', 422)
    root, config = _scope(db, user, rid)
    if config and bool(config['enabled']) != enabled:
        if db.one('SELECT step_id FROM isolated_workspace_steps WHERE run_id=? LIMIT 1', (rid,)):
            _fail('Nao altere o modo depois de preparar uma etapa.')
    head = _git(_repo(root), 'rev-parse', 'HEAD') if enabled else ''
    if config:
        if bool(config['enabled']) == enabled:
            return status(db, user, rid)
        db.execute('UPDATE isolated_workspace_runs SET enabled=?,head=?,updated_at=? WHERE run_id=?',
                   (int(enabled), head, utcnow(), rid))
    else:
        now = utcnow()
        db.execute('INSERT INTO isolated_workspace_runs(run_id,user_id,organization_id,root,enabled,head,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?)', (rid, user, current_organization(db, rid), str(root), int(enabled), head, now, now))
    return status(db, user, rid)


def _names(worker):
    raw = _git(worker, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    result = []
    for line in raw.split('\0'):
        if not line:
            continue
        if len(line) < 4 or line[:2] not in _VALID_STATUS or line[2] != ' ':
            _fail('Exclusoes, renomeacoes ou conflitos Git exigem revisao manual.')
        result.append(line[3:])
    if len(result) > _MAX_FILES:
        _fail('Limite de 30 arquivos de alteracoes excedido.')
    return result


def _text(root, relative, *, missing=False):
    path = _safe_path(root, relative, parent_may_be_missing=missing)
    if not path.exists() and missing:
        return None
    if path.stat().st_nlink > 1:
        _fail('Hardlinks nao podem ser integrados.')
    with path.open('rb') as handle:
        raw = handle.read(_MAX_FILE_BYTES + 1)
    if len(raw) > _MAX_FILE_BYTES or b'\x00' in raw:
        _fail('Arquivo binario ou maior que 32 KB exige revisao manual.')
    try:
        raw.decode('utf-8')
    except UnicodeDecodeError:
        _fail('Arquivo binario exige revisao manual.')
    return raw


def _baseline(worker):
    names = _git(worker, 'ls-files', '-z').split('\0')
    if len(names) > 10001:
        _fail('Repositorio excede o limite de 10000 arquivos de baseline.')
    result = {}
    for relative in names:
        if not relative:
            continue
        parts = relative.split('/')
        if any(part in ('', '.', '..', '.git') for part in parts):
            _fail('Caminho Git invalido.')
        path = worker
        for part in parts:
            path = path / part
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                _fail('Repositorio com links exige revisao manual.')
        if not path.is_file() or not path.resolve().is_relative_to(worker.resolve()):
            _fail('Submodulos e objetos especiais exigem revisao manual.')
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
        result[relative] = digest.hexdigest()
    return result


def _write_file(root, relative, raw, expected):
    dest = _safe_path(root, relative, parent_may_be_missing=True)
    before = _text(root, relative, missing=True)
    if _sha(before) != expected:
        _fail('Conflito: arquivo principal mudou durante a integracao.')
    created = []
    _parents(root, relative, created)
    fd, name = tempfile.mkstemp(prefix='.central-integrate-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        _safe_path(root, relative, parent_may_be_missing=True)
        if _sha(_text(root, relative, missing=True)) != expected:
            _fail('Conflito concorrente no destino.')
        if before is None:
            # Atomic no-clobber creation; never overwrite a concurrently added file.
            os.link(name, dest)
        else:
            os.chmod(name, dest.stat().st_mode & 0o777)
            os.replace(name, dest)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def prepare_step(db, user, rid, sid):
    root, config = _scope(db, user, rid)
    step, role = _step(db, user, rid, sid, execution=True)
    if not config or not config['enabled'] or role not in _IMPLEMENTERS:
        if config and config['enabled'] and role == 'review' and _blocking(db, rid):
            _fail('Aguarde a integracao dos trabalhadores antes da revisao.')
        return str(root)
    with _locked(root):
        root, config = _scope(db, user, rid)
        row = _session(db, rid, sid)
        if row:
            worker = _verify(root, config, row, rid, sid)
            if row['state'] != 'active':
                _fail('Etapa ja finalizada; nao execute novamente neste worktree.')
            return str(worker)
        if _blocking(db, rid):
            _fail('Outra etapa isolada aguarda finalizacao ou integracao.')
        if _git(root, 'rev-parse', 'HEAD') != config['head']:
            _fail('HEAD principal mudou depois de configurar a tarefa.')
        first = not db.one('SELECT step_id FROM isolated_workspace_steps WHERE run_id=? LIMIT 1', (rid,))
        if first and _git(root, 'status', '--porcelain=v1', '--untracked-files=all'):
            _fail('O primeiro trabalhador exige repositorio principal limpo.')
        base, group, worker = _paths(root, rid, sid)
        if worker.exists():
            _fail('Destino existente sem registro; nenhuma adocao automatica foi realizada.')
        seed = json.loads(config['approved_json'])
        if len(seed) > _MAX_FILES:
            _fail('Baseline aprovado excede 30 arquivos; revise manualmente.')
        payloads, total = {}, 0
        for relative, digest in seed.items():
            raw = _text(root, relative)
            if _sha(raw) != digest:
                _fail('Um arquivo previamente aprovado mudou no projeto principal.')
            total += len(raw)
            payloads[relative] = raw
        if total > _MAX_TOTAL_BYTES:
            _fail('Baseline aprovado excede 320 KB.')
        now = utcnow()
        db.execute('INSERT INTO isolated_workspace_steps(run_id,step_id,user_id,folder,head,state,created_at,updated_at) '
                   "VALUES(?,?,?,?,?,'preparing',?,?)", (rid, sid, user, str(worker), config['head'], now, now))
        # Persist preparing before touching Git. An interrupted prepare is never adopted.
        try:
            hooks = _ignore_container(root, base)
            group.mkdir(exist_ok=True)
            _git(root, '-c', 'core.hooksPath=' + str(hooks), 'worktree', 'add', '--detach', str(worker), config['head'])
            if not _registered(root, worker):
                _fail('Git nao confirmou o novo worktree.')
            baseline = _baseline(worker)
            for relative, raw in payloads.items():
                before = _text(worker, relative, missing=True)
                _write_file(worker, relative, raw, _sha(before))
                baseline[relative] = _sha(raw)
            _scope(db, user, rid)
            db.execute("UPDATE isolated_workspace_steps SET state='active',baseline_json=?,seed_json=?,updated_at=? "
                       'WHERE run_id=? AND step_id=?', (json.dumps(baseline, sort_keys=True), json.dumps(sorted(seed)), utcnow(), rid, sid))
        except Exception:
            db.execute("UPDATE isolated_workspace_steps SET state='manual_recovery',updated_at=? WHERE run_id=? AND step_id=?",
                       (utcnow(), rid, sid))
            raise
        return str(worker)


def execution_folder(db, user, rid, sid):
    root, config = _scope(db, user, rid)
    _, role = _step(db, user, rid, sid, execution=True)
    if not config or not config['enabled']:
        return str(root)
    if role not in _IMPLEMENTERS:
        if role == 'review' and _blocking(db, rid):
            _fail('Revisao bloqueada ate concluir a integracao.')
        return str(root)
    row = _session(db, rid, sid)
    if not row or row['state'] != 'active':
        _fail('Prepare a etapa isolada antes de executar ferramentas.')
    return str(_verify(root, config, row, rid, sid))


def checkpoint_folder(db, user, rid, sid):
    """Read-only path resolution for resume; does not authorize worker execution."""
    root, config = _scope(db, user, rid, parked=_PARKED | {'failed', 'paused_limit'})
    step = db.one('SELECT * FROM steps WHERE id=? AND run_id=?', (sid, rid))
    if not step:
        _fail('Etapa nao pertence a tarefa.', 404)
    agent = db.one('SELECT * FROM agents WHERE id=? AND user_id=?', (step['agent_id'], user)) if step['kind'] == 'agent' else None
    if step['kind'] == 'agent' and not agent:
        _fail('Agente nao pertence a conta.', 404)
    from .agent_registry import effective_specialty
    role = effective_specialty(agent) if agent else None
    if not config or not config['enabled'] or role not in _IMPLEMENTERS:
        return str(root)
    row = _session(db, rid, sid)
    if not row:
        _fail('Checkpoint sem workspace persistido; nao redirecione para a raiz.')
    return str(_verify(root, config, row, rid, sid))


def _changes(root, worker, row):
    baseline = json.loads(row['baseline_json'])
    names = sorted(set(_names(worker)) | set(json.loads(row['seed_json'])))
    entries, total = [], 0
    for relative in names:
        raw = _text(worker, relative)
        after = _sha(raw)
        before_hash = baseline.get(relative)
        if after == before_hash:
            continue
        before = _text(root, relative, missing=True)
        if _sha(before) != before_hash:
            _fail('Conflito: o projeto principal divergiu do baseline da etapa.')
        total += len(raw) + (len(before) if before else 0)
        if total > _MAX_TOTAL_BYTES or len(entries) >= _MAX_FILES:
            _fail('Limite de arquivos/bytes de integracao excedido.')
        diff = ''.join(difflib.unified_diff(
            (before or b'').decode('utf-8').splitlines(keepends=True),
            raw.decode('utf-8').splitlines(keepends=True),
            fromfile='base/' + relative, tofile='worker/' + relative))
        entries.append(dict(path=relative, before_sha256=before_hash, after_sha256=after,
                            bytes=len(raw), diff_preview=diff[:2800], diff_truncated=len(diff) > 2800))
    return entries


def _summary(row):
    state = row['state']
    return dict(step_id=row['step_id'], folder=row['folder'], state=state, status=state,
                pending_review=state in ('pending_review', 'reviewed'),
                changed_files=[e['path'] for e in json.loads(row['review_json'] or '[]')])


def finish_step(db, user, rid, sid):
    root, config = _scope(db, user, rid)
    _, role = _step(db, user, rid, sid)
    if not config or not config['enabled'] or role not in _IMPLEMENTERS:
        return dict(state='shared', status='shared', pending_review=False, changed_files=[])
    with _locked(root):
        row = _session(db, rid, sid)
        if not row:
            _fail('Etapa isolada nao preparada.')
        worker = _verify(root, config, row, rid, sid)
        if row['state'] in ('pending_review', 'reviewed', 'approved', 'unchanged'):
            return _summary(row)
        entries = _changes(root, worker, row)
        state = 'pending_review' if entries else 'unchanged'
        db.execute('UPDATE isolated_workspace_steps SET state=?,review_json=?,updated_at=? WHERE run_id=? AND step_id=?',
                   (state, json.dumps(entries), utcnow(), rid, sid))
        return _summary(_session(db, rid, sid))


def review(db, user, rid, sid):
    """Operator only. A new review revokes any prior unused confirmation."""
    root, config = _scope(db, user, rid, parked=_PARKED)
    _step(db, user, rid, sid)
    with _locked(root):
        row = _session(db, rid, sid)
        if not config or not config['enabled'] or not row or row['state'] not in ('pending_review', 'reviewed'):
            _fail('Etapa nao esta pendente de revisao.')
        worker = _verify(root, config, row, rid, sid)
        entries = _changes(root, worker, row)
        if not entries:
            _fail('Nenhuma diferenca aplicavel; nao aprove um plano vazio.')
        confirmation = secrets.token_urlsafe(32)
        db.execute("UPDATE isolated_workspace_steps SET state='reviewed',review_json=?,token_hash=?,expires_at=?,updated_at=? "
                   'WHERE run_id=? AND step_id=?', (json.dumps(entries), _sha(confirmation.encode()),
                                                  time.time() + _EXPIRY_SECONDS, utcnow(), rid, sid))
        return dict(run_id=rid, step_id=sid, state='reviewed', status='reviewed', files=entries,
                    confirmation=confirmation, expires_in_seconds=_EXPIRY_SECONDS)


def _manifest(entries):
    return [(e['path'], e['before_sha256'], e['after_sha256']) for e in entries]


def approve(db, user, rid, sid, confirmation):
    """Operator-only promotion; partial/interrupted application requires recovery."""
    root, config = _scope(db, user, rid, parked=_PARKED)
    _step(db, user, rid, sid)
    with _locked(root):
        root, config = _scope(db, user, rid, parked=_PARKED)
        row = _session(db, rid, sid)
        if not row or row['state'] != 'reviewed' or not row['token_hash']:
            _fail('Confirmacao ausente, consumida ou estado exige revisao manual.')
        if (not isinstance(confirmation, str) or len(confirmation) > 200
                or not hmac.compare_digest(row['token_hash'], _sha(confirmation.encode()))):
            _fail('Confirmacao incorreta.', 403)
        if time.time() > row['expires_at']:
            _fail('Confirmacao expirada; gere nova revisao.')
        worker = _verify(root, config, row, rid, sid)
        entries = _changes(root, worker, row)
        if _manifest(entries) != _manifest(json.loads(row['review_json'])):
            _fail('Trabalhador ou base mudou depois da revisao.')
        if not entries:
            _fail('Plano vazio nao pode ser aplicado.')
        # Durable token consumption before any filesystem mutation; never replay.
        claimed = db.execute("UPDATE isolated_workspace_steps SET state='applying',token_hash=NULL,expires_at=NULL,updated_at=? "
                             "WHERE run_id=? AND step_id=? AND state='reviewed' AND token_hash=?",
                             (utcnow(), rid, sid, row['token_hash']))
        if claimed != 1:
            _fail('Outra aprovacao consumiu esta confirmacao.')
        db.event(rid, 'workspace_validation', dict(passed=False, results=[], workspace='root',
                                                 reason='isolated_promotion_requires_revalidation', step_id=sid))
        approved = json.loads(config['approved_json'])
        try:
            for entry in entries:
                _scope(db, user, rid, parked=_PARKED)
                if _git(root, 'rev-parse', 'HEAD') != config['head']:
                    _fail('HEAD principal mudou durante a integracao.')
                raw = _text(worker, entry['path'])
                if _sha(raw) != entry['after_sha256']:
                    _fail('Trabalhador mudou durante a integracao.')
                _write_file(root, entry['path'], raw, entry['before_sha256'])
                approved[entry['path']] = entry['after_sha256']
                db.event(rid, 'workspace_action_result', dict(
                    step_id=sid, success=True, workspace='root', isolation_promoted=True,
                    summary=dict(action='replace' if entry['before_sha256'] else 'write', path=entry['path']),
                    before_sha256=entry['before_sha256'], after_sha256=entry['after_sha256'],
                    bytes=entry['bytes'], output='Alteracao isolada promovida pelo operador.'))
            # Commit session, accumulated seed and audit invalidation together.
            with db.lock:
                db.conn.execute('SAVEPOINT isolated_promotion')
                try:
                    db.execute('UPDATE isolated_workspace_runs SET approved_json=?,updated_at=? WHERE run_id=?',
                               (json.dumps(approved, sort_keys=True), utcnow(), rid))
                    db.execute("UPDATE isolated_workspace_steps SET state='approved',updated_at=? WHERE run_id=? AND step_id=?",
                               (utcnow(), rid, sid))
                    db.event(rid, 'workspace_validation', dict(passed=False, results=[], workspace='root',
                                                             reason='isolated_promotion_requires_revalidation', step_id=sid))
                    db.conn.execute('RELEASE SAVEPOINT isolated_promotion')
                except BaseException:
                    db.conn.execute('ROLLBACK TO SAVEPOINT isolated_promotion')
                    db.conn.execute('RELEASE SAVEPOINT isolated_promotion')
                    raise
        except Exception:
            db.execute("UPDATE isolated_workspace_steps SET state='manual_recovery',updated_at=? WHERE run_id=? AND step_id=?",
                       (utcnow(), rid, sid))
            raise
        return dict(applied=True, state='approved', status='approved', pending_review=False,
                    files=[e['path'] for e in entries], git_commit_created=False, worker_preserved=True)


def status(db, user, rid, sid=None):
    root, config = _scope(db, user, rid, parked=_PARKED | {'failed', 'paused_limit', 'completed'})
    if sid is not None:
        step = db.one('SELECT id FROM steps WHERE id=? AND run_id=?', (sid, rid))
        if not step:
            _fail('Etapa nao pertence a tarefa.', 404)
        row = _session(db, rid, sid)
        return _summary(row) if row else dict(step_id=sid, folder=str(root), state='shared', status='shared', pending_review=False, changed_files=[])
    rows = db.all('SELECT * FROM isolated_workspace_steps WHERE run_id=? ORDER BY created_at,step_id', (rid,))
    return dict(run_id=rid, enabled=bool(config and config['enabled']), root=str(root),
                pending_review=any(r['state'] in ('pending_review', 'reviewed') for r in rows),
                steps=[_summary(row) for row in rows])


def promotion_applied(db, user, rid, sid):
    """Operator/engine reconciliation; never substitute this for tool scope."""
    root, config = _scope(db, user, rid, parked=_PARKED | {'failed', 'paused_limit', 'completed'})
    step = db.one('SELECT id FROM steps WHERE id=? AND run_id=?', (sid, rid))
    if not step:
        _fail('Etapa nao pertence a tarefa.', 404)
    row = _session(db, rid, sid)
    if not config or not config['enabled'] or not row or row['state'] != 'approved':
        return False
    _verify(root, config, row, rid, sid)
    return all(_sha(_text(root, entry['path'], missing=True)) == entry['after_sha256']
               for entry in json.loads(row['review_json'] or '[]'))
