"""Read one Skill from an explicitly connected Git repository, without checkout."""
import base64
import io
import json
import re
import zipfile
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import HTTPException

from . import addon_packages as packages
from .git_gateway import Gateway, RemoteRejected, connection
from .git_integrations import REPOSITORY

MAX_TREE_ENTRIES = 5000
MAX_SKILL_FILES = 100
MAX_SKILL_BYTES = 1024 * 1024
MAX_SKILL_FILE = 256 * 1024
MAX_SKILL_MARKDOWN = 64 * 1024
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


def parse_repository_url(value):
    """Accept only canonical HTTPS GitHub/GitLab repository or tree URLs."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid repository URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("invalid repository URL") from None
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.query
            or parsed.fragment or port not in (None, 443) or parsed.netloc.lower() != parsed.hostname):
        raise ValueError("invalid repository URL")
    host = (parsed.hostname or "").lower()
    parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
    if any(not _SEGMENT.fullmatch(p) or p in (".", "..") or "/" in p or "\\" in p for p in parts):
        raise ValueError("invalid repository path")
    if host == "github.com" and len(parts) >= 2:
        service, repo_parts = "github", parts[:2]
        rest = parts[2:]
        if repo_parts[1].endswith(".git"):
            repo_parts[1] = repo_parts[1][:-4]
        if rest:
            if len(rest) < 2 or rest[0] != "tree":
                raise ValueError("unsupported GitHub URL")
            ref, path = rest[1], rest[2:]
        else:
            ref, path = None, []
    else:
        raise ValueError("unsupported Git host")
    repository = "/".join(repo_parts)
    if not REPOSITORY.fullmatch(repository) or any(p in (".", "..") for p in repo_parts):
        raise ValueError("invalid repository")
    if ref is not None and (not _SEGMENT.fullmatch(ref) or ref in (".", "..")):
        raise ValueError("invalid branch")
    return service, repository, ref, "/".join(path)


def _json_object(data):
    if not isinstance(data, dict):
        raise ValueError("invalid Git response")
    return data


def _tree(gateway, commit, path):
    if gateway.github:
        endpoint = "/git/trees/" + commit + "?recursive=1"
        data, _ = gateway.request("GET", endpoint)
        if (data.get("truncated") or not isinstance(data.get("tree"), list)
                or len(data["tree"]) > MAX_TREE_ENTRIES):
            raise ValueError("Git tree is truncated")
        return data["tree"]
    # GitLab's API is paginated; reject incomplete/oversized repository trees.
    entries = []
    for page in range(1, 51):
        endpoint = "/repository/tree?ref=" + commit + "&recursive=true&per_page=100&page=" + str(page)
        data, headers = gateway.request("GET", endpoint)
        if not isinstance(data, list):
            raise ValueError("invalid Git tree")
        entries.extend(data)
        if len(entries) > MAX_TREE_ENTRIES:
            raise ValueError("Git tree too large")
        if not headers.get("x-next-page"):
            return entries
    raise ValueError("Git tree too large")


def _find_skill_root(tree, prefix):
    candidates = []
    for item in tree:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("invalid Git tree entry")
        path = item["path"]
        if path.startswith("/") or "\\" in path or any(p in (".", "..") for p in path.split("/")):
            raise ValueError("unsafe Git tree path")
        if prefix and not (path == prefix or path.startswith(prefix + "/")):
            continue
        if path.endswith("SKILL.md") and (path == "SKILL.md" or path.endswith("/SKILL.md")):
            candidates.append(path[:-len("SKILL.md")].rstrip("/"))
    # An explicit folder link must contain one root Skill; a repository link is
    # accepted only when it identifies one unambiguous Skill.
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise ValueError("link must identify exactly one Skill")
    return candidates[0]


def import_preview(db, security, user, connection_id, repository_url, transport=None):
    try:
        service, repository, ref, prefix = parse_repository_url(repository_url)
        row = connection(db, user, connection_id)
        if row["service"] != service or row["repository"].casefold() != repository.casefold():
            raise ValueError("Git connection does not match repository")
        gateway = Gateway(row, security, transport)
        if ref is None:
            metadata, _ = gateway.request("GET", "/")
            ref = _json_object(metadata).get("default_branch")
        if not isinstance(ref, str) or not _SEGMENT.fullmatch(ref):
            raise ValueError("invalid default branch")
        commit = gateway.branch_sha(ref)
        tree = _tree(gateway, commit, prefix)
        root = _find_skill_root(tree, prefix)
        skill_path = (root + "/" if root else "") + "SKILL.md"
        chosen = []
        for item in tree:
            path = item["path"]
            if path == skill_path or (root and path.startswith(root + "/")) or (not root and "/" not in path):
                if item.get("type") == "tree":
                    continue
                # Refuse symlinks, submodules, and any non-regular Git object.
                if item.get("type") != "blob" or item.get("mode") not in ("100644", "100755"):
                    raise ValueError("non-regular Git object")
                chosen.append(item)
        if len(chosen) > MAX_SKILL_FILES or not any(x["path"] == skill_path for x in chosen):
            raise ValueError("Skill file limits exceeded")
        declared_total = 0
        for item in chosen:
            size = item.get("size")
            per_file = MAX_SKILL_MARKDOWN if item["path"] == skill_path else MAX_SKILL_FILE
            if type(size) is not int or size < 0 or size > per_file:
                raise ValueError("Skill file size exceeds limits")
            declared_total += size
        if declared_total > MAX_SKILL_BYTES:
            raise ValueError("Skill package exceeds limits")
        buffer = io.BytesIO()
        total = 0
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in chosen:
                full = item["path"]
                relative = full[len(root) + 1:] if root else full
                if not relative or relative.startswith("/") or any(p in (".", "..") for p in relative.split("/")):
                    raise ValueError("unsafe Skill file path")
                blob, _ = gateway.request("GET", "/git/blobs/" + item["sha"] if gateway.github else "/repository/blobs/" + item["sha"])
                blob = _json_object(blob)
                if blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
                    raise ValueError("invalid Git blob")
                raw = base64.b64decode(blob["content"], validate=True)
                limit = MAX_SKILL_MARKDOWN if relative == "SKILL.md" else MAX_SKILL_FILE
                if len(raw) > limit or total + len(raw) > MAX_SKILL_BYTES:
                    raise ValueError("Skill contents exceed limits")
                total += len(raw)
                archive.writestr(relative, raw)
        packed = buffer.getvalue()
        if len(packed) > packages.MAX_UPLOAD:
            raise ValueError("Skill archive exceeds limit")
        details = packages.inspect("skill", "skill.zip", packed)
        source = {"provider": service, "repository": repository, "ref": ref,
                  "commit": commit, "path": root or "."}
        return packed, details, source
    except HTTPException:
        raise
    except (httpx.HTTPError, RemoteRejected, ValueError, TypeError, KeyError, IndexError,
            json.JSONDecodeError, zipfile.BadZipFile) as exc:
        # Keep credentials, API bodies, URLs, and private repository paths out of errors.
        raise HTTPException(422 if isinstance(exc, ValueError) else 502,
                            "Não foi possível validar uma Skill neste repositório conectado.") from None
