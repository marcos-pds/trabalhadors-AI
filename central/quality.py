"""Read-only QA checks on generated TypeScript/React source prior to applying files.

This is not a full TypeScript compiler. It catches direct relative imports that
target missing files or named/default exports, using proposal contents first.
It never runs a shell, executes model code, or modifies the user's project.
"""
import re
from pathlib import PurePosixPath

TS_FILES=('.tsx','.ts','.jsx','.js')
IMPORT=re.compile(
    r'\bimport\s+(?!\()(?P<spec>(?:type\s+)?(?:[\w$*{},\s]+?))\s+from\s+'
    r'(?P<quote>["\'])(?P<module>\.[^"\']+)(?P=quote)',re.M)
BARE_IMPORT=re.compile(r'\bimport\s*["\'](\.[^"\']+)["\']')
EXPORTED=re.compile(r'\bexport\s+(?:declare\s+)?(?:async\s+)?'
                    r'(?:const|let|var|function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)')
BRACE_EXPORT=re.compile(r'\bexport\s*(?:type\s*)?\{([^}]+)\}',re.M)
DEFAULT_EXPORT=re.compile(r'\bexport\s+default\b')
NAMES=re.compile(r'^(?:type\s+)?([A-Za-z_$][\w$]*)(?:\s+as\s+[A-Za-z_$][\w$]*)?$')


def exported_symbols(source):
    symbols=set(EXPORTED.findall(source))
    for m in BRACE_EXPORT.finditer(source):
        for item in m.group(1).split(','):
            p=item.strip()
            if not p:continue
            pieces=re.split(r'\s+as\s+',p,flags=re.I)
            public=pieces[-1].strip().removeprefix('type ').strip()
            if re.fullmatch(r'[A-Za-z_$][\w$]*',public):
                symbols.add(public)
    return symbols, bool(DEFAULT_EXPORT.search(source) or 'default' in symbols)


def requested_symbols(spec):
    """Return (named symbols, default requested); ignore namespace and type-only bundles."""
    item=spec.strip()
    item=re.sub(r'^type\s+', '',item)
    named=set()
    has_default=False
    if '{' in item:
        inner=item.split('{',1)[1].split('}',1)[0]
        for part in inner.split(','):
            name=part.strip().removeprefix('type ').strip()
            name=re.split(r'\s+as\s+',name,flags=re.I)[0].strip()
            if re.fullmatch(r'[A-Za-z_$][\w$]*',name):
                named.add(name)
        left=item.split('{',1)[0].strip().strip(',')
        if left and left!='*' and not left.startswith('* as'):
            has_default=True
    elif not item.startswith('*') and re.fullmatch(r'[A-Za-z_$][\w$]*',item):
        has_default=True
    return named,has_default


def _resolve(from_file,import_path):
    if not import_path.startswith('.'):return None
    base=PurePosixPath(from_file).parent
    stack=[]
    for part in [*base.parts,*PurePosixPath(import_path).parts]:
        if part in ('','.'):continue
        if part=='..':
            if not stack:return None
            stack.pop()
        else:stack.append(part)
    normalized='/'.join(stack)
    if not normalized.startswith('frontend/'):return None
    candidates=[normalized] if normalized.endswith(TS_FILES) else [
        normalized+suffix for suffix in TS_FILES]+[
        normalized+'/index'+suffix for suffix in TS_FILES]
    return candidates


def inspect_sources(read_file,changes):
    """Collect issues from proposed TS files overlaid on the actual workspace.

    read_file(relative_path) -> str|None, with caller enforcing the sandbox.
    """
    by_path={path:content for path,content in changes.items()
             if isinstance(content,str) and path.endswith(TS_FILES)}
    issues=[]
    seen=set()
    for file,source in by_path.items():
        for match in IMPORT.finditer(source):
            target=_resolve(file,match.group('module'))
            if target is None:continue
            resolved=None;module_source=None
            for path in target:
                if path in by_path:
                    resolved=path;module_source=by_path[path];break
                contents=read_file(path)
                if contents is not None:
                    resolved=path;module_source=contents;break
            if not resolved:
                error=f'{file}: módulo relativo não encontrado: {match.group("module")}'
                if error not in seen:seen.add(error);issues.append(error)
                continue
            named,default=requested_symbols(match.group('spec'))
            exports,has_default=exported_symbols(module_source)
            missing=sorted(named-exports)
            if default and not has_default:
                missing.append('default')
            for name in missing:
                error=(f'{file}: importação {name} não existe em {resolved}. '
                       'Ajuste import/export antes de aplicar.')
                if error not in seen:seen.add(error);issues.append(error)
        for m in BARE_IMPORT.finditer(source):
            target=_resolve(file,m.group(1))
            if target is not None and not any(
                p in by_path or read_file(p) is not None for p in target):
                error=f'{file}: módulo relativo não encontrado: {m.group(1)}'
                if error not in seen:seen.add(error);issues.append(error)
    return issues[:25]
