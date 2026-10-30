# AI Motion Studio: interfaces and artifact contracts

Roadmap item 10 delivers framework-independent Python contracts in
`central.motion_contracts`. It does not deliver media generation. All four
adapters represent pending services: the module never executes commands,
contacts endpoints, installs packages, loads models, or claims a completed render.
No API routes, migrations, or production integration are included.

## Public interfaces

- `MotionConfig(comfy_endpoint=None, allow_remote=False, comfy_root=None)`:
  explicit configuration, separate from job manifests.
- `capability_inventory(config=None)`: one entry per implemented adapter,
  separating `contract_implemented`, `installed`, `version`, `version_source`,
  `endpoint_configured`, `service_status="pending"`, and
  `execution_supported=False`.
- `validate_manifest(manifest, project_root)`: validates a Python JSON object
  and returns a detached copy. Raises `ContractError` with bounded messages that
  do not echo submitted values.
- `scoped_path(project_root, relative, output=False)`: validates an artifact path
  against an explicit existing absolute project directory; returns a `Path`.
- `plan_jobs(manifest, project_root, config=None)`: returns immutable `JobPlan`
  objects, optionally containing immutable `CommandPlan(argv, cwd, shell=False)`.
  There is no runner or enqueue implementation.

Discovery uses `shutil.which` for `ffmpeg`, `whisperx`, and `remotion`.
WhisperX version comes from installed Python package metadata when its executable
is present. Other versions remain `None`; no version subprocess runs. ComfyUI
presence means the explicit `comfy_root` contains a local, non-linked `main.py`.
It does not verify Wan weights, custom nodes, GPU support, dependency health,
service connectivity, or compatibility. Executables on PATH are trusted discovery
inputs, not verified binaries. Inventory contains no executable paths.

## Version 1 manifest

```json
{
  "schema_version": 1,
  "project_id": "demo",
  "artifacts": [
    {
      "id": "source", "kind": "video", "path": "source.mp4",
      "provenance": {"source": "local"}
    },
    {
      "id": "delivery", "kind": "video", "path": "out/delivery.mp4",
      "provenance": {
        "source": "planned", "job_id": "encode", "inputs": ["source"]
      }
    }
  ],
  "jobs": [
    {
      "id": "encode", "adapter": "ffmpeg", "stage": "encode",
      "inputs": ["source"], "outputs": ["delivery"],
      "params": {"profile": "h264"}
    }
  ]
}
```

The caller supplies `project_root` separately; a manifest cannot override it.
Unknown fields, including credentials, endpoint overrides, shell flags, raw argv,
and claimed completion statuses, are rejected. IDs begin with a letter and contain
at most 64 ASCII letters, digits, underscores, or hyphens.

Artifacts have one of these kinds/formats: `workflow` (`.json`), `composition`
(`.tsx`, `.jsx`, `.ts`, `.js`), `video` (`.mp4`), `audio` (`.wav`), or `captions`
(`.json`). These are declared formats; media contents are not decoded or verified.
Local provenance can include a lowercase 64-character `sha256` assertion. The
validator checks its syntax, not the file's digest. Planned provenance requires
exact producer job ID and ordered input artifact IDs. These IDs are local artifact
links, not URLs. Planned artifacts do not imply existing outputs.

Jobs form a DAG supplied in dependency order. Every output has exactly one
producer; each declared planned artifact must be produced. Input references must
exist and planned inputs must come from earlier jobs. Paths cannot collide under
case-insensitive comparison. Each job produces exactly one artifact.

| Adapter | Stage | Inputs → output | Required params |
| --- | --- | --- | --- |
| `comfyui_wan` | `generate` | One workflow → video | `model="wan"`, integer `seed` 0–4294967295, `frames` 1–4096, `fps` 1–120 |
| `remotion` | `compose` | Exactly one composition, optional video/audio/captions → video | Composition identifier `composition`, integer `fps` 1–120 |
| `whisperx` | `transcribe` | One audio/video → captions | `language`: en/pt/es/fr/de/it/ja; `model`: tiny/base/small/medium/large-v3 |
| `ffmpeg` | `encode` | One video → video, or one audio/video → audio | `profile="h264"` or `"pcm_s16le"`, matching output kind |

WhisperX captions must use the input file's stem and `.json` suffix, matching its
CLI output convention. WhisperX's default alignment behavior is represented by
the CLI invocation; diarization and its authentication are outside this version.
Remotion's entrypoint and composition ID appear in the CLI plan. Additional media
links record dependencies only; a future service must define their props/binding
convention. They are not automatically injected into the composition.

ComfyUI emits a declarative `service_operation="enqueue_workflow"` with the
configured endpoint and artifact IDs, rather than a shell command. The validated
manifest supplies workflow/parameters to a future service. This is not a ready
`/prompt` HTTP payload: workflow node mapping, Wan weight verification, parameter
binding, queue polling, cancellation, and output collection remain service work.
Arbitrary workflow execution is not authorized by validation.

## Planning states and commands

`unavailable` means a required runtime is absent or ComfyUI is unconfigured.
`blocked` means the runtime is present but a dependency is unavailable/blocked.
`planned` means prerequisites were discovered and the service is still pending.
No state in this interface means queued, running, succeeded, or completed.
A remote endpoint alone does not prove installation or readiness: ComfyUI plans
still require explicit local discovery. No health check is performed.

CLI plans contain separate string argv entries and an explicit project cwd;
no shell string or arbitrary user arguments are accepted. FFmpeg disables stdin,
uses no-overwrite mode and an input `file` protocol allowlist. Remotion plans use
`render`, H.264, and a bounded FPS. WhisperX plans request JSON and the validated
output directory. A plan is descriptive, not permission to launch it.

## Bounds and filesystem/network policy

Manifests allow at most 256 KiB of serialized JSON, 128 artifacts, 64 jobs,
16 input references per job, 12 levels of nesting, and 12,000 visited values.
Strings are bounded; non-JSON values, cycles, floating-point values, and oversized
integers are rejected. Callers decoding untrusted JSON must bound input bytes
before parsing and reject duplicate JSON object keys; this interface accepts
already-decoded objects.

Artifact paths are portable relative paths of at most 240 characters with ASCII
letters, digits, spaces, underscores, hyphens, periods, and `/` separators. Empty
segments, traversal, absolute paths, backslashes, drive-relative paths, UNC/device
paths, NTFS alternate streams, DOS device names, short-name aliases, trailing
spaces/periods, symlinks, and Windows reparse points are rejected. The explicit
root and its existing ancestors are also checked for links/aliases. Local inputs
must be existing regular files with one hard link. Outputs must not exist;
nonexistent output directories are permitted but never created by this module.

Manifests cannot contain endpoint URLs or common credential literal patterns.
Do not put secrets in identifiers, filenames, or manifest text; lexical checks
cannot identify every arbitrary secret. Explicit ComfyUI configuration permits
HTTP(S) loopback endpoints by default. Remote hosts require `allow_remote=True`.
Userinfo, query strings, fragments, non-root paths, and credential-bearing endpoint
forms remain forbidden even with remote opt-in. No DNS resolution or HTTP call
occurs. Explicit remote policy is configuration, not proof of endpoint trust.

Filesystem validation is a planning-time snapshot. Future executors must repeat
validation at file-open time, prevent symlink/reparse-point races, sandbox trusted
runtimes, enforce network/download policy, bound resource use, verify provenance
hashes, create output directories safely, and verify actual outputs before
recording success. Media containers, workflow JSON and executable compositions
are not inspected for embedded network references or executable behavior here.
WhisperX may need model downloads and Remotion compositions can run code; those
policies belong to the pending service and must be enforced before any execution.

## Verification

Run `.venv/Scripts/python.exe -m pytest tests/test_motion_contracts.py -q`.
Tests use inert files and discovery stubs; they cover adapter schemas, DAG links,
missing runtimes, blocked dependencies, argv plans, path escapes/aliases,
credentials/endpoints, manifest bounds, and output noncreation. A real symlink
case skips when the OS denies link creation; reparse detection is tested without
requiring that privilege. No media tools or paid models are invoked.
