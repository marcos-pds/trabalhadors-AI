"""Local authenticated endpoints; imported bytes never become executable code."""
import asyncio
from urllib.parse import unquote, urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from .addon_catalog import Catalog
from .addon_git_import import (GitConnectionRequired, import_skill_previews as git_skill_previews)
from .addon_marketplace import search as marketplace_search
from . import addon_packages as packages
from .computer_access import local_only
from .ops import audit
from .database import uid, utcnow
from . import vscode_install


def router(db, security, current_user):
    catalog = Catalog(db, security)

    def actor(request: Request, user=Depends(current_user)):
        local_only(request)
        if request.method not in ('GET', 'HEAD'):
            if request.headers.get('x-central-request') != '1':
                raise HTTPException(403, 'Cabeçalho de proteção obrigatório.')
            origin = request.headers.get('origin')
            if origin:
                try:
                    a, b = urlsplit(origin), urlsplit(str(request.url))
                    origin_tuple = lambda x: (x.scheme, x.hostname, x.port or (443 if x.scheme == 'https' else 80))
                    valid = origin_tuple(a) == origin_tuple(b) and not a.username and not a.password
                except ValueError:
                    valid = False
                if not valid:
                    raise HTTPException(403, 'Origem não autorizada.')
        return user['id']

    api = APIRouter(prefix='/api/resources', tags=['Skills, VSIX e configurações MCP'])

    async def raw_body(request, limit):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > limit:
                raise HTTPException(413, 'Arquivo acima do limite permitido.')
        return bytes(raw)

    async def body(request, fields):
        try:
            data = packages.unique_json(await raw_body(request, 4096))
            if set(data) != set(fields):
                packages.reject()
            for key in fields:
                if key in ('enabled', 'consent'):
                    if type(data[key]) is not bool:
                        packages.reject()
                elif key == 'organization_id' and data[key] is None:
                    continue
                else:
                    packages.text(data[key], 2048 if key == 'repository_url' else 300)
            return data
        except (packages.InvalidPackage, TypeError):
            raise HTTPException(422, 'Solicitação inválida.') from None

    @api.get('')
    def listing(user=Depends(actor)):
        return catalog.list(user)

    @api.post('/preview/{kind}')
    async def preview(kind: str, request: Request, user=Depends(actor)):
        raw = await raw_body(request, packages.MAX_UPLOAD)
        filename = unquote(request.headers.get('x-resource-filename', ''))
        return catalog.preview(user, kind, filename, raw)

    @api.post('/preview-folder')
    async def folder(request: Request, user=Depends(actor)):
        data = await body(request, ['relative_path'])
        try:
            raw = packages.folder_package(db, user, data['relative_path'])
            return catalog.preview(user, 'skill', 'skill.zip', raw, origin='authorized_folder')
        except (packages.InvalidPackage, OSError, ValueError):
            raise HTTPException(422, 'Pasta inválida ou acima dos limites permitidos.') from None

    @api.post('/preview-git')
    async def git_preview(request: Request, user=Depends(actor)):
        try:
            data = packages.unique_json(await raw_body(request, 4096))
            if not isinstance(data, dict) or set(data) not in (
                    {'repository_url'}, {'repository_url', 'connection_id'}):
                packages.reject()
            repository_url = packages.text(data['repository_url'], 2048)
            connection_id = packages.text(data['connection_id'], 300) if data.get('connection_id') else None
        except (packages.InvalidPackage, TypeError):
            raise HTTPException(422, 'Solicitação inválida.') from None
        try:
            entries = await asyncio.to_thread(
                git_skill_previews, db, security, user, connection_id, repository_url)
        except GitConnectionRequired as required:
            return {'requires_connection': True, 'provider': required.service,
                    'repository': required.repository}
        if len(entries) == 1:
            entry = entries[0]
            return catalog.preview(user, 'skill', 'skill.zip', entry['raw'],
                                   origin='git_repository', source=entry['source'])
        return catalog.preview_many(user, entries)

    @api.post('/marketplace/search')
    async def marketplace(request: Request, user=Depends(actor)):
        data = await body(request, ['query', 'consent'])
        if data['consent'] is not True:
            raise HTTPException(403, 'Consinta o envio do termo ao Marketplace.')
        return await asyncio.to_thread(marketplace_search, data['query'])

    @api.delete('/previews/{key}')
    def cancel_preview(key: str, user=Depends(actor)):
        return catalog.cancel_preview(user, key)

    @api.post('/previews/{key}/confirm')
    async def confirm(key: str, request: Request, user=Depends(actor)):
        data = await body(request, ['confirmation'])
        return catalog.confirm(user, key, data['confirmation'])

    @api.get('/vscode/targets')
    def vscode_targets(user=Depends(actor)):
        return vscode_install.list_targets()

    async def vscode_action(resource_id, data, user, action):
        row = catalog._row(user, resource_id, write=True)
        if row['kind'] != 'vsix' or row['owner_id'] != user or row['organization_id']:
            raise HTTPException(403, 'Instalação local exige um VSIX pessoal do próprio usuário.')
        if row['state'] == 'revoked' and action == 'installed':
            raise HTTPException(409, 'Reimporte o VSIX antes de instalá-lo no Visual Studio Code.')
        if data['confirmation'] != row['sha256'] or data['consent'] is not True:
            raise HTTPException(409, 'Confirme separadamente a instalação ou desinstalação e revise os riscos.')
        filename, raw = catalog.payload(row)
        if action == 'installed':
            operation = vscode_install.install_vsix
        else:
            operation = vscode_install.uninstall_vsix
        try:
            result = await asyncio.to_thread(operation, data['target_id'], filename, raw)
        except vscode_install.VscodeError as exc:
            metadata = vscode_install.addon_packages.inspect('vsix', filename, raw)
            db.execute('INSERT INTO vscode_install_events VALUES(?,?,?,?,?,?,?,?,?)',
                       (uid(), resource_id, user, data['target_id'],
                        metadata['publisher'] + '.' + metadata['name'], metadata['version'],
                        action, 'failed', utcnow()))
            audit(db, user, 'vscode_'+action+'_failed', 'ai_resource', resource_id)
            raise HTTPException(502, str(exc)) from None
        db.execute('INSERT INTO vscode_install_events VALUES(?,?,?,?,?,?,?,?,?)',
                   (uid(), resource_id, user, result['target_id'], result['extension_id'],
                    result['extension_version'] if action == 'installed' else metadata_version(filename, raw),
                    action, 'succeeded', utcnow()))
        audit(db, user, 'vscode_'+action, 'ai_resource', resource_id)
        return result

    def metadata_version(filename, raw):
        return vscode_install.addon_packages.inspect('vsix', filename, raw)['version']

    @api.post('/{resource_id}/vscode/install')
    async def vscode_install_resource(resource_id: str, request: Request, user=Depends(actor)):
        data = await body(request, ['target_id', 'confirmation', 'consent'])
        return await vscode_action(resource_id, data, user, 'installed')

    @api.post('/{resource_id}/vscode/uninstall')
    async def vscode_uninstall_resource(resource_id: str, request: Request, user=Depends(actor)):
        data = await body(request, ['target_id', 'confirmation', 'consent'])
        return await vscode_action(resource_id, data, user, 'uninstalled')

    @api.get('/{resource_id}')
    def detail(resource_id: str, user=Depends(actor)):
        return catalog.get(user, resource_id)

    @api.get('/{resource_id}/availability')
    def availability(resource_id: str, run_id: str, agent_id: str, user=Depends(actor)):
        return catalog.availability(user, resource_id, run_id, agent_id)

    @api.post('/{resource_id}/state')
    async def state(resource_id: str, request: Request, user=Depends(actor)):
        data = await body(request, ['state', 'confirmation'])
        return catalog.state(user, resource_id, data['state'], data['confirmation'])

    @api.post('/{resource_id}/sharing')
    async def sharing(resource_id: str, request: Request, user=Depends(actor)):
        data = await body(request, ['organization_id', 'confirmation'])
        return catalog.share(user, resource_id, data['organization_id'], data['confirmation'])

    @api.post('/{resource_id}/bindings')
    async def bindings(resource_id: str, request: Request, user=Depends(actor)):
        data = await body(request, ['target_kind', 'target_id', 'enabled'])
        return catalog.bind(user, resource_id, data['target_kind'], data['target_id'], data['enabled'])

    @api.delete('/{resource_id}')
    def delete(resource_id: str, user=Depends(actor)):
        return catalog.delete(user, resource_id)

    @api.get('/{resource_id}/export')
    def export(resource_id: str, user=Depends(actor)):
        row = catalog._row(user, resource_id)
        filename, raw = catalog.payload(row)
        extension = ('md' if filename == 'SKILL.md' else 'zip') if row['kind'] == 'skill' else ('vsix' if row['kind'] == 'vsix' else 'json')
        download_name = 'SKILL.md' if row['kind'] == 'skill' and extension == 'md' else 'resource.' + extension
        audit(db, user, 'resource_exported', 'ai_resource', resource_id)
        return Response(raw, media_type='application/octet-stream', headers={
            'Content-Disposition': 'attachment; filename="' + download_name + '"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    return api
