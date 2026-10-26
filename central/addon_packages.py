"""Bounded static inspection. No subprocess, network, extraction or imports."""
import io
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
from urllib.parse import urlsplit
import zipfile
import zlib

MAX_UPLOAD = 8 * 1024 * 1024
SKILL_TOTAL = 1024 * 1024
SKILL_FILE = 256 * 1024
SKILL_COUNT = 100
VSIX_TOTAL = 32 * 1024 * 1024
VSIX_COUNT = 1000


class InvalidPackage(ValueError):
    pass


def reject():
    # Never interpolate an imported field/path/content into errors.
    raise InvalidPackage('Pacote inválido ou acima dos limites documentados.')


def safe_name(value):
    if (not isinstance(value, str) or not value or len(value) > 240
            or '\\' in value or ':' in value or any(ord(c) < 32 for c in value)):
        reject()
    parts = value.split('/')
    for part in parts:
        if (part in ('', '.', '..') or part.endswith((' ', '.'))
                or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                    *('COM'+str(i) for i in range(1, 10)), *('LPT'+str(i) for i in range(1, 10))}):
            reject()
    if len(parts) > 12:
        reject()
    return unicodedata.normalize('NFC', value).casefold()


def unique_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                reject()
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: reject())
    except (ValueError, UnicodeError, RecursionError):
        reject()
    if not isinstance(data, dict):
        reject()
    return data


def text(value, maximum=200, empty=False):
    if (not isinstance(value, str) or len(value) > maximum
            or (not empty and not value.strip()) or '\x00' in value):
        reject()
    return value


def version(value):
    value = text(value, 80)
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', value):
        reject()
    return value


def zip_members(raw, kind):
    count = SKILL_COUNT if kind == 'skill' else VSIX_COUNT
    total_limit = SKILL_TOTAL if kind == 'skill' else VSIX_TOTAL
    file_limit = SKILL_FILE if kind == 'skill' else MAX_UPLOAD
    result, seen, total = {}, {}, 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > count:
                reject()
            for info in infos:
                if '\x00' in info.orig_filename or info.flag_bits & 1:
                    reject()
                safe_name(info.orig_filename.rstrip('/'))
                if info.external_attr & 0x400:  # Windows reparse-point attribute
                    reject()
                name = info.filename.rstrip('/') if info.is_dir() else info.filename
                key = safe_name(name)
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    reject()
                if (stat.S_ISDIR(mode) and not info.is_dir()) or key in seen:
                    reject()
                seen[key] = info.is_dir()
                total += info.file_size
                if (info.file_size > file_limit or total > total_limit
                        or (info.file_size > 1024 * max(info.compress_size, 1))):
                    reject()
                if info.is_dir():
                    if info.file_size:
                        reject()
                    continue
                with archive.open(info) as entry:
                    content = entry.read(file_limit + 1)
                if len(content) != info.file_size or len(content) > file_limit:
                    reject()
                result[name] = content
            # Reject file/directory collisions irrespective of entry order.
            for key in seen:
                parts = key.split('/')
                if any(seen.get('/'.join(parts[:i])) is False for i in range(1, len(parts))):
                    reject()
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError, EOFError, zlib.error):
        reject()
    return result


def skill(files):
    # Optional single containing directory, with no unrelated siblings.
    if 'SKILL.md' not in files:
        roots = {name.split('/')[0] for name in files}
        if len(roots) != 1 or not all('/' in name for name in files):
            reject()
        files = {name.split('/', 1)[1]: body for name, body in files.items()}
    if 'SKILL.md' not in files or len(files['SKILL.md']) > 64 * 1024:
        reject()
    try:
        source = files['SKILL.md'].decode('utf-8-sig').replace('\r\n', '\n')
    except UnicodeError:
        reject()
    if '\x00' in source or not source.startswith('---\n') or '\n---\n' not in source[4:]:
        reject()
    header, body = source[4:].split('\n---\n', 1)
    meta = {}
    # Bounded metadata subset. Tool declarations are inert, never permissions.
    tool_list = False
    metadata_map = False
    for line in header.splitlines():
        if not line.strip():
            continue
        if metadata_map and line.startswith('  '):
            nested = re.fullmatch(r'  ([a-zA-Z0-9_-]{1,64}):\s*(.+)', line)
            if not nested or nested[1] in meta['metadata'] or len(meta['metadata']) >= 32:
                reject()
            value = nested[2].strip()
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except ValueError:
                    reject()
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("''", "'")
            elif value[0] in '!&*[{>|':
                reject()
            meta['metadata'][nested[1]] = text(value, 1000)
            continue
        metadata_map = False
        if line == 'metadata:':
            if 'metadata' in meta:
                reject()
            meta['metadata'] = {}
            metadata_map = True
            tool_list = False
            continue
        if tool_list and line.startswith('  - '):
            value = text(line[4:].strip(), 300)
            if len(meta['allowed-tools']) >= 32 or value[0] in '!&*[{>|':
                reject()
            meta['allowed-tools'].append(value)
            continue
        tool_list = False
        if line == 'allowed-tools:':
            if 'allowed-tools' in meta:
                reject()
            meta['allowed-tools'] = []
            tool_list = True
            continue
        match = re.fullmatch(r'(name|description|version|license|allowed-tools|user-invocable|disable-model-invocation|argument-hint):\s*(.+)', line)
        if not match or match[1] in meta:
            reject()
        value = match[2].strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                reject()
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        elif value[0] in '!&*[{>|':
            reject()
        meta[match[1]] = value
    if not {'name', 'description'} <= meta.keys():
        reject()
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', text(meta['name'], 64)):
        reject()
    # Editor hints are metadata only; they grant no permissions in the Central.
    for field in ('user-invocable', 'disable-model-invocation'):
        if field in meta:
            if meta[field] not in ('true', 'false'):
                reject()
            meta[field] = meta[field] == 'true'
    if 'argument-hint' in meta:
        text(meta['argument-hint'], 1000)
    if 'license' in meta:
        text(meta['license'], 300)
    if 'allowed-tools' in meta and not isinstance(meta['allowed-tools'], list):
        text(meta['allowed-tools'], 1000)
    text(meta['description'], 1000)
    text(body, 65536)
    nested_version = meta.get('metadata', {}).get('version')
    if nested_version and 'version' in meta and meta['version'] != nested_version:
        reject()
    meta['version'] = version(meta.get('version', nested_version or '1.0.0'))
    return dict(meta, files=sorted(files), file_count=len(files), instructions=body,
                execution_enabled=False)


def vsix(files):
    if 'extension/package.json' not in files or len(files['extension/package.json']) > 256 * 1024:
        reject()
    package = unique_json(files['extension/package.json'])
    for field in ('name', 'publisher'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', text(package.get(field), 128)):
            reject()
    engines = package.get('engines')
    if not isinstance(engines, dict):
        reject()
    engine = text(engines.get('vscode'), 120)
    if not re.fullmatch(r'[0-9xXvV.*^~<>=| +\-]+', engine) or not re.search(r'\d+\.\d+', engine):
        reject()
    minimum = re.fullmatch(r'(?:\^|~|>=)?(\d+\.\d+\.\d+)', engine.strip())
    dependencies = package.get('extensionDependencies', [])
    if not isinstance(dependencies, list) or len(dependencies) > 100:
        reject()
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', text(x, 260)) for x in dependencies):
        reject()
    extension_pack = package.get('extensionPack', [])
    if not isinstance(extension_pack, list) or len(extension_pack) > 100:
        reject()
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', text(x, 260)) for x in extension_pack):
        reject()
    contributes = package.get('contributes', {})
    if not isinstance(contributes, dict):
        reject()
    commands = contributes.get('commands', [])
    if not isinstance(commands, list) or len(commands) > 200:
        reject()
    cleaned = []
    for command in commands:
        if not isinstance(command, dict):
            reject()
        cleaned.append({'command': text(command.get('command'), 200),
                        'title': text(command.get('title'), 300)})
    return {'name': package['name'], 'publisher': package['publisher'],
            'version': version(package.get('version')),
            'description': text(package.get('description', ''), 2000, empty=True),
            'vscode_range': engine, 'minimum_vscode': minimum[1] if minimum else None,
            'dependencies': dependencies, 'extension_pack': extension_pack, 'commands': cleaned,
            'file_count': len(files), 'execution_enabled': False, 'installed': False}


def mcp(raw):
    if len(raw) > 128 * 1024:
        reject()
    data = unique_json(raw)
    if data.get('name') == 'io.github.ChromeDevTools/chrome-devtools-mcp':
        package_fields = {
            'registryType', 'registryBaseUrl', 'identifier', 'version',
            'transport',
        }
        if (set(data) != {'$schema', 'name', 'title', 'description',
                          'repository', 'version', 'packages'}
                or data.get('version') != '1.0.1'
                or not isinstance(data.get('repository'), dict)
                or data['repository'].get('url') !=
                'https://github.com/ChromeDevTools/chrome-devtools-mcp'
                or data['repository'].get('source') != 'github'
                or not isinstance(data.get('packages'), list)
                or len(data['packages']) != 1):
            reject()
        package = data['packages'][0]
        optional_environment = {'environmentVariables'}
        if (not isinstance(package, dict)
                or set(package) not in (package_fields, package_fields | optional_environment)
                or package.get('registryType') != 'npm'
                or package.get('registryBaseUrl') != 'https://registry.npmjs.org'
                or package.get('identifier') != 'chrome-devtools-mcp'
                or package.get('version') != '1.0.1'
                or package.get('transport') != {'type': 'stdio'}
                or package.get('environmentVariables', []) != []):
            reject()
        return {
            'name': 'Chrome DevTools MCP',
            'version': '1.0.1',
            'transport': 'stdio',
            'tools': [],
            'permissions': ['workspace.read'],
            'server_id': 'chrome-devtools',
            'execution_enabled': False,
            'tools_verified': False,
        }
    allowed = {'name', 'version', 'transport', 'endpoint', 'tools', 'permissions'}
    if set(data) - allowed or not {'name', 'version', 'transport', 'tools', 'permissions'} <= data.keys():
        reject()
    text(data['name'], 100)
    version(data['version'])
    if data['transport'] not in ('stdio', 'streamable-http', 'sse'):
        reject()
    if data['transport'] == 'stdio':
        if 'endpoint' in data:
            reject()
    else:
        endpoint = text(data.get('endpoint'), 1024)
        try:
            parsed = urlsplit(endpoint)
            port = parsed.port
        except ValueError:
            reject()
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(c.isspace() for c in endpoint) or '\\' in endpoint or port == 0):
            reject()
    permissions = data['permissions']
    if (not isinstance(permissions, list) or len(permissions) > 4
            or any(x not in ('workspace.read', 'workspace.write', 'network', 'external.write') for x in permissions)):
        reject()
    tools = data['tools']
    if not isinstance(tools, list) or len(tools) > 100:
        reject()
    names = set()
    for tool in tools:
        if not isinstance(tool, dict) or set(tool) != {'name', 'description', 'inputSchema'}:
            reject()
        name = text(tool['name'], 100)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in names:
            reject()
        names.add(name)
        text(tool['description'], 1000, empty=True)
        schema = tool['inputSchema']
        if not isinstance(schema, dict) or schema.get('type') != 'object':
            reject()
        properties = schema.get('properties', {})
        required = schema.get('required', [])
        if not isinstance(properties, dict) or len(properties) > 100:
            reject()
        if any(not isinstance(value, dict) for value in properties.values()):
            reject()
        if (not isinstance(required, list) or any(not isinstance(x, str) for x in required)
                or len(set(required)) != len(required) or not set(required) <= properties.keys()):
            reject()
        # No reference resolution, credentials or arbitrary extension fields.
        def check(value, depth=0):
            if depth > 12:
                reject()
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ('$ref', '$dynamicRef', '$id', 'default', 'examples'):
                        reject()
                    check(child, depth + 1)
            elif isinstance(value, list):
                if len(value) > 100:
                    reject()
                for child in value:
                    check(child, depth + 1)
        check(schema)
    return dict(data, execution_enabled=False, tools_verified=False)


def inspect(kind, filename, raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_UPLOAD:
        reject()
    if kind == 'skill':
        if filename == 'SKILL.md':
            files = {'SKILL.md': raw}
        elif filename.lower().endswith('.zip') and len(raw) <= SKILL_TOTAL:
            files = zip_members(raw, kind)
        else:
            reject()
        return skill(files)
    if kind == 'vsix' and filename.lower().endswith('.vsix'):
        return vsix(zip_members(raw, kind))
    if kind == 'mcp' and filename.lower().endswith('.json'):
        return mcp(raw)
    reject()


def folder_package(db, user_id, relative):
    """Explicit local read, only under an existing full-access workspace grant."""
    from .computer_access import policy, scoped_path, allowed_folder
    from fastapi import HTTPException
    grant = policy(db, user_id)
    if grant['mode'] != 'full' or not grant['folder']:
        raise HTTPException(403, 'Importar pasta exige acesso completo à pasta autorizada em Computador.')
    root = allowed_folder(grant['folder'])
    selected = scoped_path(root, relative, allow_root=True)
    if not selected.is_dir():
        reject()
    files, pending, total, entries = {}, [selected], 0, 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as scan:
            for item in scan:
                entries += 1
                if entries > SKILL_COUNT:
                    reject()
                path = Path(item.path)
                rel = path.relative_to(selected).as_posix()
                safe_name(rel)
                # Reuse restricted names, symlink/junction and root checks.
                checked = scoped_path(root, path.relative_to(Path(root)).as_posix())
                if item.is_dir(follow_symlinks=False):
                    pending.append(checked)
                elif item.is_file(follow_symlinks=False):
                    before = path.lstat()
                    if before.st_size > SKILL_FILE:
                        reject()
                    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
                    with os.fdopen(fd, 'rb') as stream:
                        opened = os.fstat(stream.fileno())
                        if not stat.S_ISREG(opened.st_mode) or (before.st_ino, before.st_dev) != (opened.st_ino, opened.st_dev):
                            reject()
                        raw = stream.read(SKILL_FILE + 1)
                    scoped_path(root, path.relative_to(Path(root)).as_posix())
                    if len(raw) > SKILL_FILE:
                        reject()
                    total += len(raw)
                    if total > SKILL_TOTAL:
                        reject()
                    files[rel] = raw
                else:
                    reject()
    skill(files)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(files.items()):
            archive.writestr(name, raw)
    return output.getvalue()
