"""Read one Skill from an explicitly connected Git repository, without checkout."""
import base64
import io
import json
import re
import zipfile
from urllib.parse import quote, unquote, urlsplit

import httpx
from fastapi import HTTPException

from . import addon_packages as packages
from .git_gateway import Gateway, RemoteRejected, connection
from .git_integrations import REPOSITORY

MAX_TREE_ENTRIES = 50000
MAX_SKILL_FILES = 100
MAX_SKILL_BYTES = 1024 * 1024
MAX_SKILL_FILE = 256 * 1024
MAX_SKILL_MARKDOWN = 64 * 1024
MAX_BATCH_SKILLS = 50

class GitConnectionRequired(Exception):
    def __init__(self, service, repository):
        self.service = service
        self.repository = repository


class MultipleSkillsFound(Exception):
    pass


class NoSkillFound(Exception):
    pass


class GitRateLimited(Exception):
    pass


class SkillFolderRequired(Exception):
    pass


class PublicGithubGateway:
    """Read a fixed public GitHub API origin without credentials or redirects."""
    github = True

    def __init__(self, repository, transport=None):
        if not REPOSITORY.fullmatch(repository) or repository.count("/") != 1:
            raise ValueError("invalid GitHub repository")
        self.base = "https://api.github.com/repos/" + repository
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Central-de-Trabalhadores-IA",
        }
        self.transport = transport

    def request(self, method, suffix, payload=None):
        if method != "GET" or (suffix and not suffix.startswith("/")) or suffix.startswith("//"):
            raise ValueError("invalid public GitHub request")
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False,
                          transport=self.transport) as client:
            with client.stream(method, self.base + suffix, headers=self.headers) as response:
                if not 200 <= response.status_code < 300:
                    retry_after = response.headers.get("retry-after")
                    remaining = response.headers.get("x-ratelimit-remaining")
                    if (response.status_code == 429 or retry_after is not None
                            or remaining == "0"):
                        raise GitRateLimited
                    raise RemoteRejected(response.status_code)
                raw = bytearray()
                limit = 8 * 1024 * 1024 if "/git/trees/" in suffix and "recursive=1" in suffix else 2 * 1024 * 1024
                for chunk in response.iter_bytes(65536):
                    raw.extend(chunk)
                    if len(raw) > limit:
                        raise ValueError("Git response exceeds limit")
                return json.loads(raw), dict(response.headers)

    def branch_sha(self, branch):
        data, _ = self.request("GET", "/branches/" + quote(branch, safe=""))
        sha = data["commit"]["sha"]
        if not isinstance(sha, str) or not re.fullmatch(r"[a-fA-F0-9]{40,64}", sha):
            raise ValueError("invalid branch SHA")
        return sha.lower()


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
        tree_sha = commit
        if path:
            # Resolve an explicitly supplied folder one directory at a time. This
            # avoids GitHub's truncated recursive tree for large public repos.
            for segment in path.split("/"):
                data, _ = gateway.request("GET", "/git/trees/" + tree_sha)
                entries = data.get("tree") if isinstance(data, dict) else None
                if not isinstance(entries, list) or len(entries) > MAX_TREE_ENTRIES:
                    raise ValueError("Invalid Git directory tree")
                matches = [item for item in entries
                           if isinstance(item, dict) and item.get("path") == segment]
                if len(matches) != 1 or matches[0].get("type") != "tree":
                    raise NoSkillFound
                tree_sha = matches[0].get("sha")
                if not isinstance(tree_sha, str) or not re.fullmatch(r"[A-Fa-f0-9]{40,64}", tree_sha):
                    raise ValueError("Invalid Git tree SHA")
        endpoint = "/git/trees/" + tree_sha + "?recursive=1"
        data, _ = gateway.request("GET", endpoint)
        if (not isinstance(data, dict) or not isinstance(data.get("tree"), list)
                or len(data["tree"]) > MAX_TREE_ENTRIES):
            raise SkillFolderRequired
        complete = not bool(data.get("truncated"))
        if not complete and path:
            raise SkillFolderRequired
        entries = data["tree"]
        if path:
            entries = [dict(item, path=path + "/" + item["path"])
                       for item in entries
                       if isinstance(item, dict) and isinstance(item.get("path"), str)]
        return entries, complete
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
            return entries, True
    raise ValueError("Git tree too large")


def _find_skill_roots(tree, prefix):
    candidates = {}
    for item in tree:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("invalid Git tree entry")
        path = item["path"]
        if path.startswith("/") or "\\" in path or any(p in (".", "..") for p in path.split("/")):
            raise ValueError("unsafe Git tree path")
        if prefix and not (path == prefix or path.startswith(prefix + "/")):
            continue
        if not prefix and any(part.casefold() in {'tests', 'test', '__tests__', 'fixtures'}
                              for part in path.split('/')[:-1]):
            continue
        if path.endswith("SKILL.md") and (path == "SKILL.md" or path.endswith("/SKILL.md")):
            root = path[:-len("SKILL.md")].rstrip("/")
            candidates[root] = item.get("sha")
    if not candidates:
        raise NoSkillFound

    # Byte-identical copies under agent/editor folders represent one logical Skill.
    by_blob = {}
    for root, blob_sha in candidates.items():
        key = blob_sha.lower() if isinstance(blob_sha, str) and re.fullmatch(
            r"[A-Fa-f0-9]{40,64}", blob_sha) else "path:" + root
        by_blob.setdefault(key, []).append(root)

    def rank(path):
        if path == "skill":
            return (0, path)
        return (1, len(path.split("/")), path.casefold())

    groups = []
    for paths in by_blob.values():
        paths = sorted(paths)
        groups.append((min(paths, key=rank), paths, len(paths) > 1))
    return sorted(groups, key=lambda group: (group[0].casefold(), group[0]))


def _find_skill_root(tree, prefix):
    roots = _find_skill_roots(tree, prefix)
    if len(roots) != 1:
        raise MultipleSkillsFound
    return roots[0]




def _pack_skill(gateway, tree, service, repository, ref, commit, group, scan_complete,
                blob_cache=None):
    root, skill_paths, identical_copies = group
    blob_cache = blob_cache if blob_cache is not None else {}
    skill_path = (root + "/" if root else "") + "SKILL.md"
    chosen = []
    for item in tree:
        path = item["path"]
        if path == skill_path or (root and path.startswith(root + "/")) or (not root and "/" not in path):
            if item.get("type") == "tree":
                continue
            if item.get("type") != "blob" or item.get("mode") not in ("100644", "100755"):
                raise ValueError("non-regular Git object")
            chosen.append(item)
    if not any(x["path"] == skill_path for x in chosen):
        raise ValueError("Skill file limits exceeded")
    declared_total = 0
    instructions_only = len(chosen) > MAX_SKILL_FILES
    for item in chosen:
        size = item.get("size")
        per_file = MAX_SKILL_MARKDOWN if item["path"] == skill_path else MAX_SKILL_FILE
        if type(size) is not int or size < 0:
            raise ValueError("Skill file size exceeds limits")
        if size > per_file:
            if item['path'] == skill_path:
                raise ValueError("Skill markdown exceeds limits")
            instructions_only = True
        declared_total += size
    if declared_total > MAX_SKILL_BYTES:
        instructions_only = True
    omitted_files = []
    if instructions_only:
        omitted_files = [item['path'][len(root) + 1:] if root else item['path']
                         for item in chosen if item['path'] != skill_path]
        chosen = [item for item in chosen if item['path'] == skill_path]
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in chosen:
            full = item["path"]
            relative = full[len(root) + 1:] if root else full
            if not relative or relative.startswith("/") or any(p in (".", "..") for p in relative.split("/")):
                raise ValueError("unsafe Skill file path")
            blob_sha = item.get("sha")
            if not isinstance(blob_sha, str) or not re.fullmatch(r"[A-Fa-f0-9]{40,64}", blob_sha):
                raise ValueError("invalid Git blob SHA")
            cache_key = blob_sha.lower()
            raw = blob_cache.get(cache_key)
            if raw is None:
                blob, _ = gateway.request("GET", "/git/blobs/" + cache_key)
                blob = _json_object(blob)
                if blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
                    raise ValueError("invalid Git blob")
                raw = base64.b64decode(blob["content"].replace("\n", "").replace("\r", ""), validate=True)
                blob_cache[cache_key] = raw
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
    if instructions_only:
        source.update(import_mode='instructions_only', omitted_file_count=len(omitted_files),
                      omitted_files=omitted_files[:100])
    if len(skill_paths) > 1:
        source["skill_paths"] = skill_paths[:20]
        source["skill_paths_truncated"] = len(skill_paths) > 20
        source["identical_copies"] = identical_copies
    if not scan_complete:
        source["scan_complete"] = False
    return packed, details, source


def import_skill_previews(db, security, user, connection_id, repository_url, transport=None):
    """Discover distinct Skills and return inert package snapshots for one batch review."""
    try:
        service, repository, ref, prefix = parse_repository_url(repository_url)
        if connection_id:
            row = connection(db, user, connection_id)
            if row["service"] != service or row["repository"] != "*" and row["repository"].casefold() != repository.casefold():
                raise ValueError("Git connection does not match repository")
            gateway = Gateway(row, security, transport, repository=repository)
        else:
            if service != "github":
                raise GitConnectionRequired(service, repository)
            gateway = PublicGithubGateway(repository, transport)
        if ref is None:
            metadata, _ = gateway.request("GET", "" if service == "github" else "/")
            ref = _json_object(metadata).get("default_branch")
        if not isinstance(ref, str) or not _SEGMENT.fullmatch(ref):
            raise ValueError("invalid default branch")
        commit = gateway.branch_sha(ref)
        tree, scan_complete = _tree(gateway, commit, prefix)
        roots = _find_skill_roots(tree, prefix)
        if len(roots) > MAX_BATCH_SKILLS:
            raise HTTPException(413, "O repositório contém Skills demais para uma única revisão; importe por uma pasta específica.")
        previews = []
        blob_cache = {}
        for group in roots:
            raw, details, source = _pack_skill(
                gateway, tree, service, repository, ref, commit, group,
                scan_complete, blob_cache)
            previews.append({"raw": raw, "metadata": details, "source": source})
        return previews
    except GitConnectionRequired:
        raise
    except SkillFolderRequired:
        raise HTTPException(
            422,
            "O repositório é grande demais para localizar Skills pela raiz. Cole o link direto da pasta que contém o SKILL.md.",
        ) from None
    except GitRateLimited:
        raise HTTPException(
            429,
            "O GitHub limitou temporariamente as consultas públicas. Aguarde e tente novamente ou conecte um token com acesso de leitura.",
            headers={"Retry-After": "60"},
        ) from None
    except RemoteRejected as exc:
        if connection_id and service == "github" and exc.status in (401, 403, 404):
            return import_skill_previews(db, security, user, None, repository_url, transport)
        if exc.status in (401, 403, 404):
            raise GitConnectionRequired(service, repository) from None
        raise HTTPException(502, "Não foi possível consultar o repositório Git.") from None
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(502, "Não foi possível consultar o repositório Git.") from None
    except NoSkillFound:
        raise HTTPException(422, "Não foi encontrada nenhuma Skill neste link.") from None
    except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError, zipfile.BadZipFile):
        raise HTTPException(422, "Não foi possível validar as Skills deste repositório.") from None


def import_preview(db, security, user, connection_id, repository_url, transport=None):
    try:
        service, repository, ref, prefix = parse_repository_url(repository_url)
        if connection_id:
            row = connection(db, user, connection_id)
            if row["service"] != service or row["repository"] != "*" and row["repository"].casefold() != repository.casefold():
                raise ValueError("Git connection does not match repository")
            gateway = Gateway(row, security, transport, repository=repository)
        else:
            if service != "github":
                raise GitConnectionRequired(service, repository)
            gateway = PublicGithubGateway(repository, transport)
        if ref is None:
            metadata, _ = gateway.request("GET", "" if service == "github" else "/")
            ref = _json_object(metadata).get("default_branch")
        if not isinstance(ref, str) or not _SEGMENT.fullmatch(ref):
            raise ValueError("invalid default branch")
        commit = gateway.branch_sha(ref)
        tree, scan_complete = _tree(gateway, commit, prefix)
        return _pack_skill(gateway, tree, service, repository, ref, commit,
                           _find_skill_root(tree, prefix), scan_complete)
    except GitConnectionRequired:
        raise
    except SkillFolderRequired:
        raise HTTPException(
            422,
            "O repositório é grande demais para localizar Skills pela raiz. Cole o link direto da pasta que contém o SKILL.md.",
        ) from None
    except GitRateLimited:
        raise HTTPException(
            429,
            "O GitHub limitou temporariamente as consultas públicas. Aguarde e tente novamente ou conecte um token com acesso de leitura.",
            headers={"Retry-After": "60"},
        ) from None
    except RemoteRejected as exc:
        if connection_id and service == "github" and exc.status in (401, 403, 404):
            # Fine-grained tokens only cover their configured owner/repositories.
            # A failed token must not block a safe anonymous read of a public repo.
            return import_preview(db, security, user, None, repository_url, transport)
        if exc.status in (401, 403, 404):
            raise GitConnectionRequired(service, repository) from None
        raise HTTPException(502, "Não foi possível consultar o repositório Git.") from None
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(502, "N\u00e3o foi poss\u00edvel consultar o reposit\u00f3rio Git.") from None
    except MultipleSkillsFound:
        raise HTTPException(422, "Este repositório contém várias Skills. Informe o link da pasta específica que contém o SKILL.md desejado.") from None
    except NoSkillFound:
        raise HTTPException(422, "Não foi encontrada uma Skill neste link. Informe a pasta que contém o SKILL.md.") from None
    except (ValueError, TypeError, KeyError, IndexError,
            json.JSONDecodeError, zipfile.BadZipFile):
        # Keep credentials, API bodies, URLs, and private repository paths out of errors.
        raise HTTPException(422, "N\u00e3o foi poss\u00edvel validar uma Skill neste reposit\u00f3rio.") from None