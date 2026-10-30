"""Verify human-approved, conflict-safe promotion of worker worktree changes."""
from pathlib import Path

import pytest

from central.worker_worktrees import prepare, WorktreeError
from central.worker_worktree_reviews import prepare_review, apply_review, inspect_review
from test_worker_worktrees import repo, git


def test_review_then_promote_with_one_use_approval(repo):
    original = (repo / 'app.txt').read_bytes()
    worker = Path(prepare(repo, 'job1', 'frontend1')['path'])
    (worker / 'app.txt').write_text('updated by worker\n', encoding='utf-8')
    first = prepare_review(repo, 'job1', 'frontend1')
    assert first['files'][0]['path'] == 'app.txt'
    assert (repo / 'app.txt').read_bytes() == original
    with pytest.raises(WorktreeError, match='Confirmação incorreta'):
        apply_review(repo, first['plan_id'], 'wrong')
    result = apply_review(repo, first['plan_id'], first['confirmation'])
    assert result['applied'] and not result['git_commit_created']
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'updated by worker\n'
    assert (worker / 'app.txt').is_file()
    assert inspect_review(repo, first['plan_id'])['state'] == 'applied'
    with pytest.raises(WorktreeError, match='consumido'):
        apply_review(repo, first['plan_id'], first['confirmation'])


def test_new_nested_text_file_is_allowed_only_after_review(repo):
    worker = Path(prepare(repo, 'job1', 'backend1')['path'])
    nested = worker / 'src' / 'components'
    nested.mkdir(parents=True)
    (nested / 'api.ts').write_text('export const online = true;\n', encoding='utf-8')
    plan = prepare_review(repo, 'job1', 'backend1')
    assert plan['files'][0]['before_sha256'] is None
    apply_review(repo, plan['plan_id'], plan['confirmation'])
    assert (repo / 'src' / 'components' / 'api.ts').is_file()
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'base\n'


def test_conflict_refuses_changed_primary_repo(repo):
    worker = Path(prepare(repo, 'job2', 'coder1')['path'])
    (worker / 'app.txt').write_text('worker\n', encoding='utf-8')
    review = prepare_review(repo, 'job2', 'coder1')
    (repo / 'app.txt').write_text('operator edit\n', encoding='utf-8')
    with pytest.raises(WorktreeError, match='limpo|limpo|limpo|limpo|principal'):
        apply_review(repo, review['plan_id'], review['confirmation'])
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'operator edit\n'


def test_changed_worker_invalidates_confirmation(repo):
    worker = Path(prepare(repo, 'job2', 'coder2')['path'])
    (worker / 'app.txt').write_text('A\n', encoding='utf-8')
    review = prepare_review(repo, 'job2', 'coder2')
    (worker / 'app.txt').write_text('B\n', encoding='utf-8')
    with pytest.raises(WorktreeError, match='mudou'):
        apply_review(repo, review['plan_id'], review['confirmation'])
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'base\n'


def test_deletion_or_rename_needs_manual_review(repo):
    worker = Path(prepare(repo, 'job2', 'coder3')['path'])
    (worker / 'app.txt').unlink()
    with pytest.raises(WorktreeError, match='Renomeações|exclusões'):
        prepare_review(repo, 'job2', 'coder3')


def test_secrets_and_binary_files_never_get_promoted(repo):
    worker = Path(prepare(repo, 'job3', 'coder1')['path'])
    (worker / 'secret.key').write_text('not shared', encoding='utf-8')
    with pytest.raises(WorktreeError, match='reservado|credencial'):
        prepare_review(repo, 'job3', 'coder1')
    (worker / 'secret.key').unlink()
    (worker / 'image.png').write_bytes(b'\x89PNG\r\n')
    with pytest.raises(WorktreeError, match='Extensão'):
        prepare_review(repo, 'job3', 'coder1')


def test_stale_head_is_rejected_without_changes(repo):
    worker = Path(prepare(repo, 'job3', 'coder2')['path'])
    (worker / 'app.txt').write_text('new content\n', encoding='utf-8')
    plan = prepare_review(repo, 'job3', 'coder2')
    (repo / 'another.txt').write_text('new unrelated\n', encoding='utf-8')
    git(repo, 'add', 'another.txt')
    git(repo, 'commit', '-qm', 'operator commit')
    with pytest.raises(WorktreeError, match='HEADs divergentes'):
        apply_review(repo, plan['plan_id'], plan['confirmation'])
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'base\n'


def test_no_merge_when_parent_is_symbolic_link(repo, tmp_path):
    worker = Path(prepare(repo, 'job4', 'coder1')['path'])
    nested = worker / 'src'
    nested.mkdir()
    (nested / 'view.ts').write_text('const ready = true;', encoding='utf-8')
    plan = prepare_review(repo, 'job4', 'coder1')
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (repo / 'src').symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('Symlinks indisponíveis nesta plataforma')
    with pytest.raises(WorktreeError, match='limpo|link|Conflito'):
        apply_review(repo, plan['plan_id'], plan['confirmation'])
    assert not (outside / 'view.ts').exists()


def test_review_files_persist_without_storing_raw_confirmation(repo):
    worker = Path(prepare(repo, 'job5', 'coder1')['path'])
    (worker / 'app.txt').write_text('change\n', encoding='utf-8')
    plan = prepare_review(repo, 'job5', 'coder1')
    record = inspect_review(repo, plan['plan_id'])
    assert record['state'] == 'prepared'
    path = repo / '.git' / 'central-merge-plans' / (plan['plan_id'] + '.json')
    assert path.is_file()
    assert plan['confirmation'] not in path.read_text(encoding='utf-8')


def test_repeated_directory_and_filename_components(repo):
    worker = Path(prepare(repo, 'job6', 'coder1')['path'])
    (worker / 'same.txt').mkdir()
    (worker / 'same.txt' / 'same.txt').write_text('nested text', encoding='utf-8')
    plan = prepare_review(repo, 'job6', 'coder1')
    apply_review(repo, plan['plan_id'], plan['confirmation'])
    assert (repo / 'same.txt' / 'same.txt').read_text(encoding='utf-8') == 'nested text'


def test_nul_bytes_are_rejected_even_with_text_extension(repo):
    worker = Path(prepare(repo, 'job6', 'coder2')['path'])
    (worker / 'app.txt').write_bytes(b'text\x00binary')
    with pytest.raises(WorktreeError, match='binario'):
        prepare_review(repo, 'job6', 'coder2')
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'base\n'


def test_rollback_preserves_concurrent_operator_edit(repo, monkeypatch):
    import central.worker_worktree_reviews as reviews
    worker = Path(prepare(repo, 'job6', 'coder3')['path'])
    (worker / 'app.txt').write_text('worker edit', encoding='utf-8')
    (worker / 'z.txt').write_text('second file', encoding='utf-8')
    plan = prepare_review(repo, 'job6', 'coder3')
    original = reviews._safe_path

    def concurrent_edit(root, relative, **kwargs):
        if root == worker and relative == 'z.txt' and (repo / 'app.txt').read_bytes() == b'worker edit':
            (repo / 'app.txt').write_text('operator edit', encoding='utf-8')
            raise WorktreeError('injected failure')
        return original(root, relative, **kwargs)

    monkeypatch.setattr(reviews, '_safe_path', concurrent_edit)
    with pytest.raises(WorktreeError, match='injected'):
        apply_review(repo, plan['plan_id'], plan['confirmation'])
    assert (repo / 'app.txt').read_text(encoding='utf-8') == 'operator edit'
    assert not (repo / 'z.txt').exists()
    assert inspect_review(repo, plan['plan_id'])['state'] == 'manual_recovery'


def test_corrupt_plan_non_object_is_rejected(repo):
    worker = Path(prepare(repo, 'job6', 'coder4')['path'])
    (worker / 'app.txt').write_text('change', encoding='utf-8')
    plan = prepare_review(repo, 'job6', 'coder4')
    path = repo / '.git' / 'central-merge-plans' / (plan['plan_id'] + '.json')
    path.write_text('[]', encoding='utf-8')
    with pytest.raises(WorktreeError, match='corrompido'):
        inspect_review(repo, plan['plan_id'])


@pytest.mark.parametrize('relative', ['.git./config.txt', 'src./app.txt', 'NUL.txt', 'com1/app.txt'])
def test_windows_path_aliases_are_rejected(repo, relative):
    from central.worker_worktree_reviews import _safe_path
    with pytest.raises(WorktreeError):
        _safe_path(repo, relative, parent_may_be_missing=True)


def test_apply_preserves_existing_file_permissions(repo):
    import os
    import stat
    if os.name == 'nt':
        pytest.skip('POSIX permission bits unavailable on Windows')
    (repo / 'app.txt').chmod(0o755)
    git(repo, 'add', 'app.txt')
    git(repo, 'commit', '-qm', 'make executable')
    worker = Path(prepare(repo, 'modesrun', 'worker1')['path'])
    (worker / 'app.txt').write_text('updated', encoding='utf-8')
    plan = prepare_review(repo, 'modesrun', 'worker1')
    apply_review(repo, plan['plan_id'], plan['confirmation'])
    assert stat.S_IMODE((repo / 'app.txt').stat().st_mode) == 0o755
