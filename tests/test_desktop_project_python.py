"""Frozen app launchers must never serve as generated-project interpreters."""
import os
from pathlib import Path
import sys

from fastapi import HTTPException
import pytest

from central import workspace_tools as tools


REAL_PYTHON = Path(getattr(sys, '_base_executable', sys.executable)).resolve()
PYTHON_NAME = 'python.exe' if os.name == 'nt' else 'python3'
VENV_PYTHON = Path('.venv') / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'fixture executable')
    path.chmod(0o755)
    return path


@pytest.fixture
def frozen_project(tmp_path, monkeypatch):
    project = tmp_path / 'authorized'
    project.mkdir()
    bundled = executable(tmp_path / 'bundled' / PYTHON_NAME)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(bundled))
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'host')
    monkeypatch.setenv('PATH', '')
    return project, bundled


def spec(project, code, **extra):
    return tools.command_spec(str(project), {'command': code, **extra})


@pytest.mark.parametrize('command', ['python_compile', 'python_test', 'venv_create'])
def test_missing_external_python_is_optional_and_fails_clearly(frozen_project, command):
    project, _ = frozen_project
    with pytest.raises(HTTPException) as error:
        spec(project, command)
    assert error.value.status_code == 422
    assert 'Python para projetos' in error.value.detail
    assert 'aplicativo Central não exige Python externo' in error.value.detail


@pytest.mark.parametrize('command', ['python_compile', 'python_test', 'pip_package', 'pip_requirements'])
def test_authorized_venv_preferred_over_path_and_backend(frozen_project, monkeypatch, tmp_path, command):
    project, bundled = frozen_project
    local = executable(project / VENV_PYTHON)
    external = executable(tmp_path / 'external' / PYTHON_NAME)
    monkeypatch.setenv('PATH', str(external.parent))
    (project / 'requirements.txt').write_text('pytest==8.4.2\n', encoding='utf-8')
    result = spec(project, command, package='pytest==8.4.2')
    assert result['argv'][0] == str(local)
    assert str(bundled) not in result['argv']


def test_frozen_venv_creation_uses_external_and_subsequent_compile_uses_venv(
        frozen_project, monkeypatch, tmp_path):
    project, bundled = frozen_project
    external = executable(tmp_path / 'external' / PYTHON_NAME)
    monkeypatch.setenv('PATH', os.pathsep.join([str(bundled.parent), str(external.parent)]))
    assert spec(project, 'venv_create')['argv'] == [str(external), '-m', 'venv', '.venv']
    local = executable(project / VENV_PYTHON)
    assert spec(project, 'python_compile')['argv'][0] == str(local)
    with pytest.raises(HTTPException) as error:
        spec(project, 'venv_create')
    assert error.value.status_code == 409


def test_path_lookup_rejects_relative_entries_and_same_backend_file(frozen_project, monkeypatch):
    project, bundled = frozen_project
    monkeypatch.setenv('PATH', os.pathsep.join(['relative-directory', str(bundled.parent)]))
    with pytest.raises(HTTPException) as error:
        spec(project, 'python_compile')
    assert error.value.status_code == 422


def test_venv_cannot_alias_bundled_application(frozen_project):
    project, bundled = frozen_project
    local = project / VENV_PYTHON
    local.parent.mkdir(parents=True)
    os.link(bundled, local)
    with pytest.raises(HTTPException) as error:
        spec(project, 'python_compile')
    assert error.value.status_code == 422


def test_non_python_project_commands_do_not_require_python(frozen_project, monkeypatch):
    project, _ = frozen_project
    monkeypatch.setattr(tools.shutil, 'which', lambda name: '/tools/npm' if name.startswith('npm') else '/tools/git')
    (project / 'package.json').write_text('{}', encoding='utf-8')
    assert spec(project, 'npm_build')['argv'][-2:] == ['run', 'build']
    assert spec(project, 'git_status')['argv'][-2:] == ['status', '--short']


def test_docker_python_commands_never_need_external_host_python(frozen_project, monkeypatch):
    project, bundled = frozen_project
    monkeypatch.setenv('CENTRAL_COMMAND_RUNNER', 'docker')
    for command in ('python_compile', 'python_test', 'venv_create', 'pip_package'):
        result = spec(project, command, package='pytest==8.4.2')
        assert result['argv'][0] == 'python3'
        assert str(bundled) not in result['argv']


def test_unfrozen_web_keeps_its_current_interpreter(frozen_project, monkeypatch):
    project, bundled = frozen_project
    monkeypatch.setattr(sys, 'frozen', False)
    assert spec(project, 'python_compile')['argv'][0] == str(bundled)
    assert spec(project, 'venv_create')['argv'][0] == str(bundled)


def test_real_external_python_creates_venv_compiles_and_reports_bad_source(
        frozen_project, monkeypatch):
    project, bundled = frozen_project
    # Host Python is an explicit local dependency of this integration test,
    # independent from the fake frozen executable. No pip/network downloads.
    monkeypatch.setenv('PATH', str(REAL_PYTHON.parent) + os.pathsep + os.environ.get('PATH', ''))
    (project / 'hello.py').write_text('print("generated project")\n', encoding='utf-8')
    assert spec(project, 'venv_create')['argv'][0] != str(bundled)
    created = tools.execute(str(project), {'action': 'command', 'command': 'venv_create'})
    assert created['success'], created
    compiled = tools.execute(str(project), {'action': 'command', 'command': 'python_compile'})
    assert compiled['success'], compiled
    assert Path(spec(project, 'python_compile')['argv'][0]) == project / VENV_PYTHON
    (project / 'bad.py').write_text('def broken(:\n', encoding='utf-8')
    broken = tools.execute(str(project), {'action': 'command', 'command': 'python_compile'})
    assert broken['success'] is False
    assert broken['exit_code'] != 0
    assert 'SyntaxError' in broken['output']
