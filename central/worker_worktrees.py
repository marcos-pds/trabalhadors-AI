"""Safe, explicit Git worktree lifecycle for individual Central workers.

This stage is *operator controlled*. It does not automatically route agent tools,
merge code, alter the current branch or remove a dirty worker tree. Git worktrees
are NOT a process/security sandbox.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading

from .computer_access import allowed_folder

_RESERVED = '.central-worker-worktrees'
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
_MUTEX = threading.RLock()


class WorktreeError(RuntimeError):
    pass


def _git(cwd, *args):
    git = shutil.which('git.exe' if os.name == 'nt' else 'git') or shutil.which('git')
    if not git:
        raise WorktreeError('Instale o Git no PATH antes de preparar worktrees.')
    # Repository-selection variables must not override the authorized cwd.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    try:
        result = subprocess.run(
            [git, *args], cwd=str(cwd), env=env,
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorktreeError('Falha ao executar Git dentro da pasta autorizada.') from exc
    if result.returncode:
        raise WorktreeError(
            'Git recusou a operação: ' + (result.stderr or result.stdout).strip()[-600:])
    # Preserve leading whitespace in Git porcelain status (e.g. ' M file').
    return result.stdout.rstrip('\r\n')


def _not_link(path):
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise WorktreeError('Link simbólico ou junção detectado na estrutura dos worktrees.')
    if path.exists() and not path.is_dir():
        raise WorktreeError('A pasta de worktrees contém um objeto não diretório.')


def _repo(folder):
    root = Path(allowed_folder(str(folder))).resolve(strict=True)
    metadata = root / '.git'
    _not_link(metadata)
    if not metadata.is_dir():
        raise WorktreeError('Esta operação exige a raiz de um repositório Git não bare.')
    top = _git(root, 'rev-parse', '--show-toplevel')
    if os.path.normcase(str(Path(top).resolve())) != os.path.normcase(str(root)):
        raise WorktreeError('A pasta autorizada deve ser exatamente a raiz do repositório Git.')
    if _git(root, 'rev-parse', '--is-bare-repository') != 'false':
        raise WorktreeError('Repositórios bare não são suportados.')
    return root


def _ids(run_id, step_id):
    if not (isinstance(run_id, str) and isinstance(step_id, str)
            and _ID.fullmatch(run_id) and _ID.fullmatch(step_id)):
        raise WorktreeError('IDs devem conter apenas letras, números, hífen e underscore.')
    if run_id == step_id:
        raise WorktreeError('Identificadores de execução e etapa devem ser diferentes.')


def _paths(root, run_id, step_id):
    _ids(run_id, step_id)
    base = root / _RESERVED
    group = base / run_id
    target = group / step_id
    for path in (base, group, target):
        _not_link(path)
    return base, group, target


def _registered(root, target):
    listing = _git(root, 'worktree', 'list', '--porcelain', '-z')
    roots = [line[len('worktree '):] for line in listing.split('\0')
             if line.startswith('worktree ')]
    registered = any(os.path.normcase(str(Path(item).resolve())) ==
                     os.path.normcase(str(target.resolve())) for item in roots)
    if not registered:
        return False
    # A registered directory can have its .git file replaced independently.
    metadata = target / '.git'
    if metadata.is_symlink() or not metadata.is_file():
        raise WorktreeError('Metadados do worktree invalidos.')
    common = Path(_git(target, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    top = Path(_git(target, 'rev-parse', '--show-toplevel'))
    git_dir = Path(_git(target, 'rev-parse', '--absolute-git-dir'))
    registry = root / '.git' / 'worktrees'
    _not_link(registry)
    _not_link(git_dir)
    backlink = git_dir / 'gitdir'
    if (git_dir.parent.resolve() != registry.resolve()
            or backlink.is_symlink() or not backlink.is_file()
            or Path(backlink.read_text(encoding='utf-8').rstrip('\r\n')).resolve()
            != metadata.resolve()):
        raise WorktreeError('Metadados do worktree nao correspondem ao registro.')
    if common.resolve() != (root / '.git').resolve() or top.resolve() != target.resolve():
        raise WorktreeError('Metadados do worktree apontam para outro repositorio.')
    return True


def _ignore_container(root, base):
    info = root / '.git' / 'info'
    _not_link(info)
    if not info.is_dir():
        raise WorktreeError('Diretório de metadados do Git inválido.')
    exclude = info / 'exclude'
    if exclude.is_symlink() or (hasattr(exclude, 'is_junction') and exclude.is_junction()):
        raise WorktreeError('Arquivo Git exclude inválido.')
    if exclude.exists() and not exclude.is_file():
        raise WorktreeError('Git exclude não é um arquivo regular.')
    existing = exclude.read_text(encoding='utf-8') if exclude.exists() else ''
    rule = '/.central-worker-worktrees/'
    if rule not in existing.splitlines():
        with exclude.open('a', encoding='utf-8') as handle:
            handle.write(('\n' if existing and not existing.endswith('\n') else '') + rule + '\n')
    base.mkdir(exist_ok=True)
    hooks = base / '.no-hooks'
    _not_link(hooks)
    hooks.mkdir(exist_ok=True)
    return hooks


def _status(root, target):
    # Git worktree remove also discards ignored files unless we guard them.
    return _git(target, 'status', '--porcelain', '--untracked-files=all',
                '--ignored=matching')


def prepare(folder, run_id, step_id):
    """Prepare a clean detached Git checkout without touching primary HEAD.

    The operator must intentionally invoke this operation; it never starts
    automatically from a model message or an unapproved task.
    """
    with _MUTEX:
        root = _repo(folder)
        base, group, target = _paths(root, run_id, step_id)
        if target.exists():
            if not _registered(root, target):
                raise WorktreeError('Destino já existe e não pertence a um worktree registrado.')
            return dict(inspect(root, run_id, step_id), reused=True)
        if _git(root, 'status', '--porcelain', '--untracked-files=all'):
            raise WorktreeError('Repositório base possui mudanças; salve ou revise antes de criar worktrees.')
        hooks = _ignore_container(root, base)
        group.mkdir(exist_ok=True)
        # All args are individually validated; no shell or user-controlled Git flags.
        _git(root, '-c', 'core.hooksPath=' + str(hooks), 'worktree', 'add',
             '--detach', str(target), 'HEAD')
        if not target.is_dir() or not _registered(root, target):
            raise WorktreeError('Git não confirmou o novo worktree.')
        return dict(inspect(root, run_id, step_id), reused=False)


def inspect(folder, run_id, step_id):
    root = _repo(folder)
    _, _, target = _paths(root, run_id, step_id)
    if not target.is_dir() or not _registered(root, target):
        raise WorktreeError('Worktree não foi encontrado para esta execução/etapa.')
    state = _status(root, target)
    names = [line[:240] for line in state.splitlines()[:100]]
    return {
        'root': str(root),
        'path': str(target),
        'run_id': run_id, 'step_id': step_id,
        'head': _git(target, 'rev-parse', 'HEAD'),
        'clean': not bool(state), 'changes': names,
        'truncated': len(state.splitlines()) > 100,
    }


def remove_clean(folder, run_id, step_id):
    """Never force-remove, reset, commit, merge or discard worker changes."""
    with _MUTEX:
        status = inspect(folder, run_id, step_id)
        if not status['clean']:
            raise WorktreeError('Worktree contém alterações; nenhuma exclusão foi realizada.')
        root = Path(status['root'])
        _git(root, 'worktree', 'remove', status['path'])
        return {'removed': True, 'path': status['path']}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Gerenciamento manual de Git worktrees da Central')
    parser.add_argument('action', choices=('prepare', 'inspect', 'remove-clean'))
    parser.add_argument('--repo', required=True, help='Raiz Git explicitamente escolhida pelo operador')
    parser.add_argument('--run', required=True, help='Identificador da execução')
    parser.add_argument('--step', required=True, help='Identificador do trabalhador')
    parser.add_argument('--confirm-remove', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            result = prepare(args.repo, args.run, args.step)
        elif args.action == 'inspect':
            result = inspect(args.repo, args.run, args.step)
        else:
            if not args.confirm_remove:
                raise WorktreeError('A remoção exige --confirm-remove, sem --force.')
            result = remove_clean(args.repo, args.run, args.step)
    except WorktreeError as exc:
        parser.exit(2, 'Worktree não alterado ou operação interrompida: ' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
