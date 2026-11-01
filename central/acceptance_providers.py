"""Operator-only acceptance lab bridge to existing, read-only API credentials.

Lab descriptors never contain source endpoints, account IDs or credentials.
Only ciphertext is snapshotted; decryption occurs inside the streaming call.
This module never initializes/migrates a Central database or creates a key.
"""
from contextlib import aclosing
import asyncio
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import sqlite3
import threading
from types import MappingProxyType
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

from .providers import ProviderClient, ProviderError
from .worker_checkpoint import WorkerPaused

API_KINDS = frozenset({
    'openai', 'anthropic', 'gemini', 'deepseek', 'grok', 'mistral',
    'openrouter', 'groq', 'cerebras', 'sambanova', 'huggingface',
    'cloudflare', 'nvidia', 'together', 'fireworks', 'perplexity',
    'cohere', 'deepinfra', 'novita', 'zai', 'modelscope', 'siliconflow',
    'compatible',
})
LAB_BASE_URL = 'https://lab.invalid'


@dataclass(frozen=True, repr=False)
class _Selected:
    lab_id: str
    source_id: str
    owner: str
    kind: str
    model: str
    endpoint: str
    ciphertext: str
    priority: int
    input_price: float | None
    output_price: float | None


def _regular_file(path):
    if (path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())
            or not path.is_file()):
        raise ValueError('Fonte deve ser um arquivo regular existente, sem links.')


def _model(value):
    return (isinstance(value, str) and 0 < len(value) <= 256 and value == value.strip()
            and not any(ord(c) < 32 for c in value) and 'codex' not in value.casefold())


def _endpoint(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() for c in value):
        return False
    try:
        url = urlsplit(value)
        host = url.hostname
        if (url.scheme != 'https' or not host or url.username or url.password or url.query or url.fragment
                or '\\' in value or url.port == 0 or host.lower().rstrip('.') in ('localhost', 'localhost.localdomain')
                or host.lower().rstrip('.').endswith(('.localhost', '.local'))):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return '.' in host
    except ValueError:
        return False


def _price(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Preco da API de origem invalido.')
    return float(value)


class SourceProviders:
    """Read-only snapshot for one credential owner; no live SQLite connection."""
    __slots__ = ('_key_path', '_selected')

    def __init__(self, key_path, selected):
        self._key_path = key_path
        self._selected = MappingProxyType({item.lab_id: item for item in selected})

    @classmethod
    def load(cls, data_dir, user_id=None, kinds=None):
        if user_id is not None and (not isinstance(user_id, str) or not user_id or len(user_id) > 256):
            raise ValueError('Informe um user_id de origem valido.')
        if kinds is None:
            requested = API_KINDS
        else:
            if isinstance(kinds, (str, bytes)):
                raise ValueError('kinds deve ser uma colecao explicita de APIs permitidas.')
            try:
                requested = frozenset(kinds)
            except TypeError:
                raise ValueError('kinds invalido.') from None
            if not requested or not requested <= API_KINDS:
                raise ValueError('Tipo de provedor nao permitido para o laboratorio de APIs.')
        root = Path(data_dir).expanduser()
        if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
            raise ValueError('Diretorio de origem nao pode ser link ou juncao.')
        root = root.resolve(strict=True)
        source = root / 'central.sqlite3'
        key_path = root / 'secret.key'
        _regular_file(source)
        _regular_file(key_path)  # existence only: never read/decrypt the key during load
        connection = None
        try:
            connection = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
            connection.execute('PRAGMA trusted_schema=OFF')
            connection.execute('PRAGMA query_only=ON')
            connection.row_factory = sqlite3.Row
            table = connection.execute("SELECT type,sql FROM sqlite_schema WHERE name='providers'").fetchone()
            if not table or table['type'] != 'table' or 'VIRTUAL TABLE' in table['sql'].upper():
                raise ValueError('Tabela de provedores de origem invalida.')
            rows = connection.execute(
                'SELECT id,user_id,kind,model,base_url,api_key_enc,priority,input_price,output_price '
                'FROM providers WHERE enabled=1 AND typeof(api_key_enc)=\'text\' '
                'AND length(trim(api_key_enc))>0 LIMIT 5001').fetchall()
            if len(rows) > 5000:
                raise ValueError('Fonte excede o limite de provedores do laboratorio.')
        except sqlite3.Error:
            raise ValueError('Nao foi possivel ler provedores de origem em modo somente leitura.') from None
        finally:
            if connection is not None:
                connection.close()
        # Owner selection precedes optional kind filtering: hiding another
        # owner's kind must not silently choose whose credentials will be used.
        eligible = [row for row in rows if row['kind'] in API_KINDS and _model(row['model'])]
        owners = {row['user_id'] for row in eligible}
        if user_id is None:
            if len(owners) != 1:
                raise ValueError('Selecione um unico proprietario de credenciais com user_id.')
            user_id = next(iter(owners))
        selected = []
        for row in eligible:
            if row['user_id'] != user_id or row['kind'] not in requested:
                continue
            if not isinstance(row['id'], str) or not isinstance(row['user_id'], str):
                raise ValueError('Identificador de provedor de origem invalido.')
            if not _endpoint(row['base_url']):
                raise ValueError('API de origem exige endpoint HTTPS remoto sem credenciais na URL.')
            if type(row['priority']) is not int or not 0 <= row['priority'] <= 1000000:
                raise ValueError('Prioridade de provedor de origem invalida.')
            lab_id = 'lab-api-' + hashlib.sha256(json.dumps(
                [row['user_id'], row['id']], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:32]
            selected.append(_Selected(lab_id, row['id'], row['user_id'], row['kind'], row['model'], row['base_url'], row['api_key_enc'],
                                      row['priority'], _price(row['input_price']), _price(row['output_price'])))
        if not selected:
            raise ValueError('Nenhuma API permitida, habilitada e com credencial foi selecionada.')
        selected.sort(key=lambda item: (item.priority, item.lab_id))
        if len({item.lab_id for item in selected}) != len(selected):
            raise ValueError('Identificador de provedor duplicado.')
        return cls(key_path, selected)

    @property
    def descriptors(self):
        """Fresh dictionaries safe to insert into the lab DB; never add key fields."""
        return [dict(id=item.lab_id, name='API ' + item.kind, kind=item.kind, model=item.model,
                     base_url=LAB_BASE_URL, priority=item.priority, enabled=1,
                     input_price=item.input_price, output_price=item.output_price)
                for item in self._selected.values()]

    def client(self, max_calls=80, timeout=90):
        return _Bridge(self._key_path, self._selected, max_calls, timeout)


class _Bridge:
    __slots__ = ('_key_path', '_selected', '_limit', '_calls', '_lock', '_timeout')

    def __init__(self, key_path, selected, max_calls, timeout):
        if type(max_calls) is not int or not 1 <= max_calls <= 10000:
            raise ValueError('max_calls deve ser um inteiro finito entre 1 e 10000.')
        self._key_path = key_path
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError('Timeout de API deve ser finito, positivo e no maximo 300 segundos.')
        self._timeout = timeout
        self._selected = selected
        self._limit = max_calls
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def calls(self):
        with self._lock:
            return self._calls

    def _request(self, provider, model):
        if not isinstance(provider, dict):
            raise ProviderError('acceptance_policy', 'Provedor nao selecionado no laboratorio.', False)
        identifier = provider.get('id')
        item = self._selected.get(identifier) if isinstance(identifier, str) else None
        if (item is None or provider.get('kind') != item.kind or provider.get('model') != item.model
                or model != item.model or not _model(model) or item.kind not in API_KINDS
                or provider.get('base_url', LAB_BASE_URL) != LAB_BASE_URL
                or provider.get('enabled', 1) != 1):
            raise ProviderError('acceptance_policy', 'Provedor, tipo ou modelo difere da selecao autorizada.', False)
        outbound = dict(id=item.lab_id, kind=item.kind, model=item.model, base_url=item.endpoint)
        if '_structured_actions' in provider:
            if type(provider['_structured_actions']) is not bool:
                raise ProviderError('acceptance_policy', 'Formato de resposta invalido.', False)
            outbound['_structured_actions'] = provider['_structured_actions']
        if '_max_tokens' in provider:
            value = provider['_max_tokens']
            if type(value) is not int or not 1 <= value <= 8192:
                raise ProviderError('acceptance_policy', 'Limite de tokens invalido.', False)
            outbound['_max_tokens'] = value
        return item, outbound

    async def stream(self, provider, api_key, model, system, messages):
        """ProviderClient-compatible signature; the lab api_key is ignored."""
        item, outbound = self._request(provider, model)
        with self._lock:
            if self._calls >= self._limit:
                raise WorkerPaused('Limite de chamadas do laboratorio atingido; retome em um novo segmento.')
            self._calls += 1  # failed/cancelled attempts also consume the finite budget
        credential = None
        stream = None
        try:
            # Recheck revocation/rotation before each call; a snapshot is not a
            # continuing authorization to use a disabled or replaced API key.
            database = self._key_path.parent / 'central.sqlite3'
            connection = None
            try:
                _regular_file(database)
                connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
                connection.execute('PRAGMA trusted_schema=OFF')
                connection.execute('PRAGMA query_only=ON')
                current = connection.execute('SELECT kind,model,base_url,api_key_enc,enabled FROM providers WHERE id=? AND user_id=?',
                                             (item.source_id, item.owner)).fetchone()
                if current != (item.kind, item.model, item.endpoint, item.ciphertext, 1):
                    raise ProviderError('acceptance_policy', 'API de origem revogada ou alterada.', False)
            except (sqlite3.Error, OSError, ValueError):
                raise ProviderError('acceptance_policy', 'API de origem indisponivel para verificacao.', False) from None
            finally:
                if connection is not None:
                    connection.close()
            try:
                _regular_file(self._key_path)
                with self._key_path.open('rb') as handle:
                    key = handle.read(1025)
                if len(key) > 1024:
                    raise ValueError('invalid key')
                credential = Fernet(key.strip()).decrypt(item.ciphertext.encode()).decode('utf-8')
                del key
                if not credential.strip() or len(credential) > 16384:
                    raise ValueError('invalid credential')
            except Exception:
                raise ProviderError('authentication', 'Credencial de origem indisponivel ou invalida.', False) from None
            stream = ProviderClient().stream(outbound, credential, item.model, system, messages)
            # Hold enough text to redact a credential even if the upstream API
            # echoes it across SSE chunks; never forward that value to the lab.
            pending = ''
            # A stream sending keepalives can defeat an inactivity timeout.
            # Bound the entire response so the engine can try another API.
            async with asyncio.timeout(self._timeout), aclosing(stream):
                async for token in stream:
                    if not isinstance(token, str):
                        raise ProviderError('response', 'Resposta da API invalida.', False)
                    pending += token
                    while credential in pending:
                        start = pending.index(credential)
                        if start:
                            yield pending[:start]
                        yield '[redacted]'
                        pending = pending[start + len(credential):]
                    safe = len(pending) - len(credential) + 1
                    if safe > 0:
                        yield pending[:safe]
                        pending = pending[safe:]
                if pending:
                    yield pending
        except TimeoutError:
            raise ProviderError('timeout', 'Tempo total da API selecionada excedido.', True) from None
        except ProviderError as exc:
            categories = {'acceptance_policy', 'acceptance_limit', 'authentication', 'credits',
                          'rate_limit', 'unavailable', 'request', 'response', 'timeout', 'network',
                          'context_limit', 'model_unavailable'}
            category = exc.category if exc.category in categories else 'response'
            status = exc.http_status if type(exc.http_status) is int and 100 <= exc.http_status <= 599 else None
            raise ProviderError(category, 'Falha na API selecionada (' + category + ').', exc.retryable is True, status) from None
        except Exception:
            raise ProviderError('response', 'Falha na API selecionada.', False) from None
        finally:
            # Python strings cannot be zeroized; do not retain plaintext on the
            # reusable bridge/source objects, descriptors, files, events or logs.
            credential = None
            stream = None
