# Resource versions: integration contract

`central.resource_versions` is a static lifecycle sidecar for imported Skills,
VSIX packages and MCP manifests. It never starts a process, connects to a server,
installs an extension, activates a resource or grants permissions.

The parent must register exported `SCHEMA` as migration 20 using the normal
checksummed migration ledger. Imports do not create tables. HTTP routes, CSRF,
authentication, request limits and UI confirmation remain parent responsibilities.
Pass the authenticated **user ID string**, never a caller-supplied owner ID.

## Calls

- `preview_update(db, security, user, resource_id, filename, raw)` returns
  `resource_id`, `current`, `new`, `bindings_will_be_removed`, `activation_required`.
  This performs bounded static inspection and quota checks without mutations.
- `apply_update(db, security, user, rid, filename, raw,
  expected_current_sha256, confirmed_new_sha256)` revalidates everything inside
  `BEGIN IMMEDIATE`. Pass the exact current/new SHA-256 from the reviewed preview.
- `list_versions(db, security, user, resource_id)` returns archived review records
  including `revision_id`, `created_at`, `operation`, SHA-256, original state,
  version, byte size and static counts. Current is not an archived revision.
- `rollback(db, security, user, rid, revision_id, expected_current_sha256,
  confirmed_target_sha256)` authenticates the selected archive and restores it as
  a new change. It archives the current version instead of rewriting history.

Mutation responses contain `resource_id`, `archived_revision_id`, `current`,
`bindings_removed` and `activation_required`. Both operations always leave the
resource **inactive**, remove every binding on that resource and record an audit
entry atomically. Old activation/bindings are never replayed on rollback.
Provider credentials and account grants are not touched. Activation remains a
separate existing Catalog operation; only its existing official supported MCP
runtime may activate. An imported declaration cannot extend that runtime.

## Boundaries and storage

Only the original owner may version a resource. Private scope and the owner's
personal organization with current admin membership and no other members are supported. Shared
organizations are rejected even for an original owner/admin; first unshare via
the existing separately confirmed scope operation. No ownership, kind, package
name, VSIX publisher or official MCP server identity can change through updates.

Catalog payload and metadata encryption are reused. Archives preserve old
encrypted payload/metadata, digest, byte size, origin and state. An encrypted
authenticated snapshot binds those fields to the revision/resource/owner IDs.
Payload digest/size and inspected metadata are checked before use. SQL triggers
reject history updates and direct history deletion while the parent resource
exists. No automatic pruning or separate revision deletion API is supplied.
Explicit resource deletion through the existing authorized `Catalog.delete`
remains available: `ON DELETE CASCADE` removes its revisions and bindings.
SQLite deletes the parent before applying the foreign-key cascade, so the guarded
revision trigger allows that cascade. Tests verify both direct-deletion protection
and owner-authorized resource deletion after update/rollback. Existing Catalog
organization authorization rules still govern resource deletion; the sidecar
does not introduce a new deletion permission or endpoint.

Public responses contain static allowlisted summaries only: no payload,
ciphertext, freeform descriptions/instructions, endpoints, source paths, schemas
or credentials. Newly inspected metadata replaces old metadata; old source and
installation facts remain only in the encrypted archive. Update origin is
`local_upload_update`; rollback restores the selected archive's origin.

Maximum: **20 versions including current**, **64 MiB per owner including all
current resources and archived payload byte sizes**. Ciphertext overhead is not
counted, matching Catalog's logical payload accounting. A full history blocks
further update/rollback; it is never silently truncated. Each change adds the
new payload size because the previous current becomes an archive. Unchanged
payload replacement/rollback is rejected. Other resources' quota usage is
included. **Existing Catalog imports currently count only current resources:**
the parent must include `resource_revisions.byte_size` in all import quota checks
to enforce the same account cap across every entry point. This sidecar enforces
it for all its own writes and does not modify Catalog.

CAS uses the package content digest required by this API. It catches concurrent
changes to different bytes but is not a monotonic generation token: an A→B→A
cycle has the same content digest. Owner/scope and current metadata/state are
revalidated under the lock regardless. Call outside an existing transaction.

HTTP errors: 404 for unavailable owner/resource/revision, 403 for disallowed
shared scope, 422 for invalid or changed package identity, 409 for stale or
unconfirmed digest, integrity failure, no-op or quota exhaustion. Errors never
echo imported contents or decryption diagnostics.

## Verification

`python -m pytest tests/test_resource_versions.py -q` uses file-backed SQLite,
real Catalog/Fernet encryption and independent connections for CAS contention.
It covers all three package kinds, inactive rollback, binding invalidation,
foreign identity/scope denial, immutable history, quotas and atomic audit failure.
These are static lifecycle tests, not installation or live MCP runtime proof.
