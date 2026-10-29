"""Real Git worktrees on Windows/Linux; no network or provider credentials."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from central.worker_worktrees import WorktreeError, prepare, inspect, remove_clean

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='Git não instalado')


def git(folder, *args):
    p = subprocess.run(['git', *args], cwd=folder, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    base = tmp_path / 'project'
    base.mkdir()
    git(base, 'init', '-q')
    git(base, 'config', 'user.email', 'tests@example.invalid')
    git(base, 'config', 'user.name', 'Test Runner')
    (base / 'app.txt').write_text('base\n', encoding='utf-8')
    git(base, 'add', 'app.txt')
    git(base, 'commit', '-qm', 'initial commit')
    yield base
    # An unclean tree is intentionally preserved by production code;
    # pytest removes its own dedicated tmp_path afterwards.


def test_two_agents_have_independent_detached_worktrees(repo):
    head = git(repo, 'rev-parse', 'HEAD')
    first = prepare(repo, 'run-123', 'frontend-worker')
    second = prepare(repo, 'run-123', 'backend-worker')
    assert first['head'] == second['head'] == head
    assert first['path'] != second['path']
    Path(first['path'], 'app.txt').write_text('frontend\n', encoding='utf-8')
    assert Path(second['path'], 'app.txt').read_text(encoding='utf-8') == 'base\n'
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'base\n'
    assert inspect(repo, 'run-123', 'frontend-worker')['clean'] is False
    assert inspect(repo, 'run-123', 'backend-worker')['clean'] is True
    assert git(repo, 'status', '--porcelain', '--untracked-files=all') == ''
    assert prepare(repo, 'run-123', 'backend-worker')['reused'] is True
    assert remove_clean(repo, 'run-123', 'backend-worker')['removed']


def test_remove_refuses_modified_and_untracked_files(repo):
    path = Path(prepare(repo, 'run-123', 'step-one')['path'])
    (path / 'app.txt').write_text('edited\n', encoding='utf-8')
    with pytest.raises(WorktreeError, match='alterações'):
        remove_clean(repo, 'run-123', 'step-one')
    assert path.joinpath('app.txt').read_text(encoding='utf-8') == 'edited\n'
    git(path, 'restore', 'app.txt')
    (path / 'untracked.txt').write_text('keep me', encoding='utf-8')
    with pytest.raises(WorktreeError, match='alterações'):
        remove_clean(repo, 'run-123', 'step-one')
    assert (path / 'untracked.txt').is_file()
    (path / 'untracked.txt').unlink()
    assert remove_clean(repo, 'run-123', 'step-one')['removed'] is True
    assert not path.exists()


@pytest.mark.parametrize('run, step', [
    ('../secret', 'frontend'), ('run', '../../secret'), ('-force', 'other'),
    ('run', 'work/tree'), ('run', 'bad\\name'), ('run', 'run'),
])
def test_untrusted_names_never_leave_repo(repo, run, step):
    with pytest.raises(WorktreeError):
        prepare(repo, run, step)
    assert not (repo / '.central-worker-worktrees').exists()


def test_cannot_prepare_with_dirty_primary_project(repo):
    (repo / 'app.txt').write_text('uncommitted\n', encoding='utf-8')
    with pytest.raises(WorktreeError, match='mudanças'):
        prepare(repo, 'r1', 'w2')
    assert not (repo / '.central-worker-worktrees').exists()
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'uncommitted\n'


def test_existing_directory_is_never_overwritten(repo):
    root = repo / '.central-worker-worktrees' / 'r1'
    root.mkdir(parents=True)
    (root / 'w2').mkdir()
    with pytest.raises(WorktreeError, match='já existe'):
        prepare(repo, 'r1', 'w2')
    assert (root / 'w2').is_dir()


def test_reject_other_repo_and_missing_worktree(repo, tmp_path):
    sub = repo / 'subdirectory'
    sub.mkdir()
    with pytest.raises(WorktreeError, match='raiz'):
        prepare(sub, 'r1', 'w2')
    with pytest.raises(WorktreeError, match='não foi encontrado'):
        inspect(repo, 'r1', 'w2')


def test_reject_root_symlink_and_internal_link(repo, tmp_path):
    fake = repo / '.central-worker-worktrees'
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        fake.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('Sistema não permite symlink sem privilégios')
    with pytest.raises(WorktreeError, match='Link'):
        prepare(repo, 'r1', 'w2')
    assert not (outside / 'r1').exists()


@pytest.mark.skipif(os.name == 'nt', reason='Hook POSIX não é portável para Windows')
def test_git_checkout_hooks_are_disabled(repo):
    hooks = repo / '.git' / 'hooks'
    hook = hooks / 'post-checkout'
    marker = repo / 'bad-hook-ran'
    hook.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n', encoding='utf-8')
    hook.chmod(0o755)
    result = prepare(repo, 'run99', 'agent77')
    assert result['clean']
    assert not marker.exists()
