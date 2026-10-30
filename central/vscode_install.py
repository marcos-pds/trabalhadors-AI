"""Explicit local VS Code CLI operations for reviewed VSIX packages."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading

from . import addon_packages

_LOCK = threading.RLock()
_VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
_MAX_LIST_BYTES = 2 * 1024 * 1024


class VscodeError(Exception):
    """Sanitized operational failure; never contains child-process output."""


def candidate_paths(env=None):
    env = os.environ if env is None else env
    roots = []
    for key in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        value = env.get(key)
        if value:
            roots.append(Path(value) / "Programs" / "Microsoft VS Code" if key == "LOCALAPPDATA"
                         else Path(value) / "Microsoft VS Code")
    seen, result = set(), []
    for root in roots:
        exe = root / "Code.exe"
        try:
            # Require the resolved binary to remain directly in the canonical,
            # standard installation directory.
            expected_root = root.resolve(strict=True)
            resolved = exe.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        normalized = os.path.normcase(str(resolved))
        if (normalized not in seen and resolved.is_file() and resolved.name.casefold() == "code.exe"
                and resolved.parent == expected_root and expected_root.name.casefold() == "microsoft vs code"):
            seen.add(normalized)
            result.append(resolved)
    return result


def target_id(executable):
    return hashlib.sha256(os.path.normcase(str(Path(executable).resolve())).encode()).hexdigest()[:32]


def _environment():
    keys = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATH")
    return {key: os.environ[key] for key in keys if os.environ.get(key)}


def run_cli(executable, arguments, timeout=20):
    try:
        result = subprocess.run([str(executable), *arguments], shell=False, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                                check=False, cwd=str(Path(executable).parent), env=_environment(),
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        raise VscodeError("Não foi possível concluir a operação do VS Code no limite de tempo.") from None
    if len(result.stdout) > _MAX_LIST_BYTES or result.returncode != 0:
        raise VscodeError("O VS Code recusou a operação ou retornou uma resposta acima do limite.")
    return result.stdout.decode("utf-8", errors="replace")


def _version(executable):
    output = run_cli(executable, ["--version"])
    first = output.splitlines()[0].strip() if output.splitlines() else ""
    if not _VERSION.fullmatch(first):
        raise VscodeError("O executável selecionado não apresentou uma versão reconhecida do VS Code.")
    return first


def _installed(executable):
    output = run_cli(executable, ["--list-extensions", "--show-versions"])
    if len(output.encode("utf-8")) > _MAX_LIST_BYTES:
        raise VscodeError("A lista de extensões excede o limite permitido.")
    rows = {}
    for line in output.splitlines()[:5000]:
        item = line.strip()
        if not item:
            continue
        extension_id, sep, version = item.partition("@")
        if not sep:
            extension_id, version = item, ""
        if re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", extension_id):
            rows[extension_id.casefold()] = {"id": extension_id, "version": version[:80]}
    return list(rows.values())


def _target(target):
    for executable in candidate_paths():
        if target_id(executable) == target:
            version = _version(executable)
            return executable, version, _installed(executable)
    raise VscodeError("O destino do VS Code não está mais disponível. Atualize a lista de destinos.")


def list_targets():
    targets = []
    for executable in candidate_paths():
        try:
            version = _version(executable)
            installed = _installed(executable)
        except VscodeError:
            continue
        targets.append({"target_id": target_id(executable), "name": "Visual Studio Code",
                        "version": version, "installed_extensions": installed})
    return targets


def _extension_identity(metadata):
    return f"{metadata['publisher']}.{metadata['name']}"


def _review_installable(metadata):
    if metadata.get("dependencies") or metadata.get("extension_pack"):
        raise VscodeError("Este pacote declara dependências/extensões adicionais; instale-as e revise o pacote manualmente no VS Code.")


def install_vsix(executable_id, filename, raw):
    metadata = addon_packages.inspect("vsix", filename, raw)
    _review_installable(metadata)
    identity = _extension_identity(metadata)
    with _LOCK:
        executable, vscode_version, before = _target(executable_id)
        with tempfile.TemporaryDirectory(prefix="central-vsix-") as directory:
            package_path = Path(directory) / "reviewed.vsix"
            package_path.write_bytes(raw)
            run_cli(executable, ["--install-extension", str(package_path)], timeout=120)
        after = _installed(executable)
        installed = {entry["id"].casefold(): entry for entry in after}.get(identity.casefold())
        if not installed or installed["version"] != metadata["version"]:
            raise VscodeError("A instalação não pôde ser confirmada na versão revisada.")
    return {"installed": True, "target_id": executable_id, "target_name": "Visual Studio Code",
            "vscode_version": vscode_version, "extension_id": identity,
            "extension_version": installed["version"], "previous_version": next(
                (item["version"] for item in before if item["id"].casefold() == identity.casefold()), None)}


def uninstall_vsix(executable_id, filename, raw):
    metadata = addon_packages.inspect("vsix", filename, raw)
    identity = _extension_identity(metadata)
    with _LOCK:
        executable, vscode_version, before = _target(executable_id)
        if not any(item["id"].casefold() == identity.casefold() for item in before):
            raise VscodeError("A extensão não está instalada neste destino do VS Code.")
        run_cli(executable, ["--uninstall-extension", identity], timeout=120)
        after = _installed(executable)
        if any(item["id"].casefold() == identity.casefold() for item in after):
            raise VscodeError("O VS Code ainda informa que a extensão está instalada.")
    return {"uninstalled": True, "target_id": executable_id, "target_name": "Visual Studio Code",
            "vscode_version": vscode_version, "extension_id": identity}
