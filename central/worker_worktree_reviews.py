"""Explicit review/one-use approval before copying isolated worker edits.

An operator-only CLI/API-independent foundation: NO automatic model authority,
no git merge/reset/commit/push. Rejects changed bases, changed worktrees,
symlinks, binary/secret paths, renames, deletions and concurrent application.
"""
import argparse
import difflib
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from uuid import uuid4

from .worker_worktrees import (_repo, _paths, _registered, _git, _MUTEX,
                               WorktreeError)
from .computer_access import RESTRICTED_NAMES

_PLAN_RE = re.compile(r'[0-9a-f]{32}\Z')
_SAFE_FILE = re.compile(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){0,11}\Z')
_ALLOWED_SUFFIX = frozenset({
    '.py', '.ts', '.tsx', '.js', '.jsx', '.css', '.html', '.json',
    '.md', '.txt', '.yaml', '.yml', '.toml', '.sql', '.xml', '.ini',
    '.csv', '.go', '.rs', '.java', '.cpp', '.h'
})
_VALID_STATUS = frozenset({'??', ' M', 'M ', 'MM', 'A ', 'AM', ' A'})
_MAX_FILES = 30
_MAX_FILE_BYTES = 32000
_MAX_TOTAL_BYTES = 320000
_EXPIRY_SECONDS = 1800


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _store(root):
    meta = root / '.git'
    folder = meta / 'central-merge-plans'
    if folder.is_symlink() or (hasattr(folder, 'is_junction') and folder.is_junction()):
        raise WorktreeError('Diretório de aprovação é link ou junção.')
    folder.mkdir(exist_ok=True)
    if not folder.is_dir():
        raise WorktreeError('Diretório de aprovação inválido.')
    return folder


def _plan_path(root, plan_id):
    if not isinstance(plan_id, str) or not _PLAN_RE.fullmatch(plan_id):
        raise WorktreeError('Identificador do plano inválido.')
    return _store(root) / (plan_id + '.json')


def _write_record(path, value):
    # Never expose confirmation token in the file; record writes replace atomically.
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')
    fd, name = tempfile.mkstemp(prefix='.central-approval-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _safe_path(root, relative, *, parent_may_be_missing=False):
    if not isinstance(relative, str) or not _SAFE_FILE.fullmatch(relative):
        raise WorktreeError('Nome de arquivo Git fora do conjunto seguro.')
    parts = relative.split('/')
    if any(part in ('.', '..') or part.lower() in RESTRICTED_NAMES
           or part.lower().startswith('.env') or part.lower() == '.central-worker-worktrees'
           for part in parts):
        raise WorktreeError('Arquivo reservado ou credencial fora do escopo.')
    result = root
    for part in parts:
        result = result / part
        if result.is_symlink() or (hasattr(result, 'is_junction') and result.is_junction()):
            raise WorktreeError('Symlink/junção não pode ser integrado.')
        if result.exists() and not (result.is_dir() if part != parts[-1] else result.is_file()):
            raise WorktreeError('Conflito: objeto existente tem tipo inesperado.')
        if not result.exists() and not parent_may_be_missing:
            raise WorktreeError('Caminho de origem inexistente.')
    if result.suffix.lower() not in _ALLOWED_SUFFIX:
        raise WorktreeError('Extensão não autorizada para integrar.')
    return result


def _git_changes(worktree):
    status = _git(worktree, 'status', '--porcelain=v1', '--untracked-files=all')
    if not status:
        raise WorktreeError('O trabalhador não tem mudanças para integrar.')
    lines = status.splitlines()
    if len(lines) > _MAX_FILES:
        raise WorktreeError('Limite de arquivos por integração atingido.')
    changes = []
    seen = set()
    for line in lines:
        if len(line) < 4 or line[:2] not in _VALID_STATUS or line[2] != ' ':
            raise WorktreeError('Renomeações, exclusões ou alterações Git complexas exigem revisão manual.')
        relative = line[3:]
        if relative in seen:
            raise WorktreeError('Arquivo repetido no status Git.')
        seen.add(relative)
        changes.append(relative)
    return changes


def _snapshot(root, worktree):
    if _git(root, 'status', '--porcelain=v1', '--untracked-files=all'):
        raise WorktreeError('Projeto principal não está limpo; preserve alterações antes de revisar.')
    head = _git(root, 'rev-parse', 'HEAD')
    if _git(worktree, 'rev-parse', 'HEAD') != head:
        raise WorktreeError('HEADs divergentes. Reconcile mudanças manualmente.')
    entries, total = [], 0
    for relative in _git_changes(worktree):
        source = _safe_path(worktree, relative)
        destination = _safe_path(root, relative, parent_may_be_missing=True)
        raw = source.read_bytes()
        if len(raw) > _MAX_FILE_BYTES:
            raise WorktreeError('Arquivo editado ultrapassa 32 KB.')
        try:
            new_text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise WorktreeError('Arquivos binários não são integrados automaticamente.') from exc
        total += len(raw)
        if total > _MAX_TOTAL_BYTES:
            raise WorktreeError('Limite total de bytes excedido.')
        if destination.exists():
            before = destination.read_bytes()
            try:
                old_text = before.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise WorktreeError('Arquivo base contém conteúdo binário.') from exc
        else:
            before, old_text = None, ''
        if raw == before:
            continue
        diff = ''.join(difflib.unified_diff(
            old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile='base/' + relative, tofile='worker/' + relative))
        entries.append({
            'path': relative,
            'before_sha256': _sha(before) if before is not None else None,
            'after_sha256': _sha(raw),
            'bytes': len(raw),
            'diff_preview': diff[:2800],
            'diff_truncated': len(diff) > 2800,
        })
    if not entries:
        raise WorktreeError('Nenhuma diferença aplicável encontrada.')
    return head, entries


def _worker(root, run_id, step_id):
    _, _, target = _paths(root, run_id, step_id)
    if not target.is_dir() or not _registered(root, target):
        raise WorktreeError('Worktree não pertence ao par run/step informado.')
    return target


def prepare_review(folder, run_id, step_id):
    """Produce an immutable review and one-time human confirmation secret."""
    with _MUTEX:
        root = _repo(folder)
        worker = _worker(root, run_id, step_id)
        head, entries = _snapshot(root, worker)
        plan_id = uuid4().hex
        confirmation = secrets.token_urlsafe(32)
        record = {
            'id': plan_id, 'run_id': run_id, 'step_id': step_id,
            'root': str(root), 'head': head, 'files': entries,
            'token_hash': _sha(confirmation.encode('utf-8')),
            'state': 'prepared', 'created_at': time.time(),
        }
        path = _plan_path(root, plan_id)
        if path.exists():
            raise WorktreeError('O identificador de revisão já existe.')
        _write_record(path, record)
        return {
            'plan_id': plan_id, 'confirmation': confirmation,
            'expires_in_seconds': _EXPIRY_SECONDS,
            'run_id': run_id, 'step_id': step_id, 'head': head,
            'files': entries,
            'message': 'Revise os diffs e só então use apply com a confirmação de uso único.'
        }


def inspect_review(folder, plan_id):
    root = _repo(folder)
    path = _plan_path(root, plan_id)
    if not path.is_file() or path.is_symlink():
        raise WorktreeError('Plano de revisão inexistente.')
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise WorktreeError('Plano de revisão corrompido.') from exc
    if record.get('root') != str(root) or record.get('id') != plan_id:
        raise WorktreeError('Plano pertence a outro repositório.')
    return record


def _parents(root, relative, created):
    current = root
    for part in relative.split('/')[:-1]:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise WorktreeError('Pai do arquivo foi convertido em link.')
        if not current.exists():
            current.mkdir()
            created.append(current)
        if not current.is_dir():
            raise WorktreeError('Pai do arquivo não é diretório.')


def apply_review(folder, plan_id, confirmation):
    """Copy verified text changes only after a real explicit one-use approval.

    Git changes are deliberately NOT committed, staged, merged or pushed. A
    partially applied batch is rolled back if possible; interrupted batches
    fail closed and require manual inspection instead of automatic retry.
    """
    with _MUTEX:
        root = _repo(folder)
        record = inspect_review(root, plan_id)
        if record.get('state') != 'prepared':
            raise WorktreeError('Plano já consumido, cancelado ou em revisão manual.')
        if not isinstance(confirmation, str) or not hmac.compare_digest(
                record.get('token_hash', ''), _sha(confirmation.encode('utf-8'))):
            raise WorktreeError('Confirmação incorreta.')
        if time.time() - record.get('created_at', 0) > _EXPIRY_SECONDS:
            raise WorktreeError('Confirmação expirada. Gere uma nova revisão.')
        worker = _worker(root, record['run_id'], record['step_id'])
        head, fresh = _snapshot(root, worker)
        if head != record['head'] or [
                (e['path'], e['before_sha256'], e['after_sha256'])
                for e in fresh] != [
                (e['path'], e['before_sha256'], e['after_sha256'])
                for e in record['files']]:
            raise WorktreeError('A base ou a árvore de trabalho mudou após a revisão.')
        store = _store(root)
        lock_path = store / '.apply-in-progress'
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError as exc:
            raise WorktreeError('Outra integração está ativa ou exige recuperação manual.') from exc
        backups, created_dirs, temporary = [], [], []
        plan_path = _plan_path(root, plan_id)
        try:
            # Durable state before any mutation prevents a crashed apply replay.
            record['state'] = 'applying'
            _write_record(plan_path, record)
            for entry in record['files']:
                relative = entry['path']
                source = _safe_path(worker, relative)
                dest = _safe_path(root, relative, parent_may_be_missing=True)
                raw = source.read_bytes()
                if _sha(raw) != entry['after_sha256']:
                    raise WorktreeError('Trabalhador alterou o arquivo durante a integração.')
                before = dest.read_bytes() if dest.exists() else None
                if (_sha(before) if before is not None else None) != entry['before_sha256']:
                    raise WorktreeError('Conflito: arquivo principal mudou.')
                _parents(root, relative, created_dirs)
                fd, tmp = tempfile.mkstemp(prefix='.central-merge-', dir=dest.parent)
                temporary.append(tmp)
                with os.fdopen(fd, 'wb') as file:
                    file.write(raw)
                    file.flush()
                    os.fsync(file.fileno())
                if dest.exists() and _sha(dest.read_bytes()) != entry['before_sha256']:
                    raise WorktreeError('Conflito concorrente no arquivo principal.')
                if not dest.exists() and before is not None:
                    raise WorktreeError('Arquivo principal removido durante integração.')
                os.replace(tmp, dest)
                temporary.remove(tmp)
                backups.append((dest, before))
            record['state'] = 'applied'
            record['applied_at'] = time.time()
            _write_record(plan_path, record)
            return {'applied': True, 'plan_id': plan_id,
                    'files': [e['path'] for e in record['files']],
                    'git_commit_created': False, 'worker_preserved': True}
        except BaseException:
            rollback_failed = False
            for path, previous in reversed(backups):
                try:
                    if previous is None:
                        path.unlink()
                    else:
                        path.write_bytes(previous)
                except OSError:
                    rollback_failed = True
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            record['state'] = 'manual_recovery' if rollback_failed else 'failed'
            _write_record(plan_path, record)
            raise
        finally:
            for tmp in temporary:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
            lock_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Revisão explícita de alterações isoladas')
    parser.add_argument('action', choices=('plan', 'inspect', 'apply'))
    parser.add_argument('--repo', required=True)
    parser.add_argument('--run', help='ID da execução ao planejar')
    parser.add_argument('--step', help='ID da etapa ao planejar')
    parser.add_argument('--plan-id', help='Plano existente')
    parser.add_argument('--confirmation', help='Confirmação de uso único ao aplicar')
    args = parser.parse_args(argv)
    try:
        if args.action == 'plan':
            result = prepare_review(args.repo, args.run, args.step)
        elif args.action == 'inspect':
            row = inspect_review(args.repo, args.plan_id)
            result = {key: value for key, value in row.items() if key != 'token_hash'}
        else:
            result = apply_review(args.repo, args.plan_id, args.confirmation)
    except (WorktreeError, TypeError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
