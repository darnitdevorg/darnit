# Authoring a Pluggable Store Backend

Feature 033 exposes four per-artifact Protocols that alternative
backends can satisfy. This document explains how to distribute a
backend as a Python package that darnit discovers automatically.

## What you can back with a plugin

| Kind         | Protocol            | Discovery group             |
|--------------|---------------------|-----------------------------|
| project      | `ProjectStateStore` | `darnit.stores.project`     |
| attestation  | `AttestationStore`  | `darnit.stores.attestation` |
| report       | `ReportStore`       | `darnit.stores.report`      |
| audit cache  | `AuditCacheStore`   | `darnit.stores.cache`       |

Each Protocol lives in `darnit.stores.protocols`. All four inherit from
a `Store` base carrying a single `close()` method.

## Minimal example: an S3-backed `AttestationStore`

### Package layout

```
my-s3-store/
  pyproject.toml
  src/my_s3_store/
    __init__.py
    backend.py
```

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-s3-store"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["boto3"]

[project.entry-points."darnit.stores.attestation"]
s3 = "my_s3_store.backend:S3AttestationStore"

[tool.hatch.build.targets.wheel]
packages = ["src/my_s3_store"]
```

### `src/my_s3_store/backend.py`

```python
from __future__ import annotations

import boto3


class S3AttestationStore:
    """Writes attestation bundles to an S3 bucket."""

    def __init__(self, *, bucket: str, prefix: str = "", **_) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._s3 = boto3.client("s3")

    def write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None:
        # content_type maps to filename extension per feature 033 R-004:
        #   application/vnd.in-toto+json          -> .intoto.json
        #   application/vnd.dev.sigstore.bundle+json -> .sigstore.json
        ext = ".sigstore.json" if "sigstore" in content_type else ".intoto.json"
        key = f"{self._prefix}{bundle_id}{ext}"
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=bundle_bytes,
            ContentType=content_type,
        )

    def close(self) -> None:
        # boto3 clients hold no persistent connection; nothing to release.
        return None
```

### Selecting the backend in `.baseline.toml`

```toml
[stores.attestation]
backend = "s3"
bucket = "my-attestations"
prefix = "openssf-baseline"
```

Any keys beyond `backend` are passed as keyword arguments to the
backend's constructor.

Environment variables can be interpolated with `$VAR`:

```toml
[stores.attestation]
backend = "s3"
bucket = "$ATTESTATION_BUCKET"
```

## Protocol contracts (must-read)

Every backend must uphold these invariants:

* **`close()` idempotence (FR-019).** `store.close(); store.close()` must
  not raise. The audit driver's `close_all()` calls it exactly once per
  instantiated store, but tests may double-close.
* **`AuditCacheStore.write` must not raise (FR-011).** Cache writes are
  best-effort; the audit run must not fail because a cache backend
  hiccuped. Swallow backend exceptions internally.
* **`AuditCacheStore.read` returns `None` on miss/corruption.** Do not
  raise on a missing key or malformed payload; return `None` and let
  the caller run a fresh audit.
* **Lazy construction (SC-004).** Backends whose artifact class the
  current audit never touches are never constructed. Keep `__init__`
  cheap; do not open connections until first `read`/`write`.
* **`ProjectStateStore.read_project()` returns `None` when there is no
  seeded project state.** The reader treats `None` as "no `.project/`".
* **Backends may accept a `repo_path` kwarg.** The selector passes it
  when the backend's `__init__` signature accepts it and falls back
  transparently when it doesn't.

## Testing your backend

darnit ships `darnit-testchecks` with in-memory reference
implementations for all four kinds -- use them as a behavior baseline.
Then write an integration test that pip-installs your package, calls
`resolve_stores(StoresConfig(attestation=StoreBlock(backend="s3", ...)),
repo_path=tmp_path)`, and asserts on your backend's observable state
after an audit run.

Reference: `tests/darnit/stores/fixtures/example_store_plugin_pkg/`
plus `tests/darnit/stores/test_us3_plugin_*.py`.

## Error surfaces you may see

| Exception                | When                                            |
|--------------------------|-------------------------------------------------|
| `StoreNotInstalled`      | TOML names a backend not registered             |
| `StoreProtocolMismatch`  | Registered class missing a required method     |
| `StoreNameCollision`    | Two packages register the same name/group     |
| `StoreOperationError`    | Backend raised during read/write (except cache) |

`StoreNotInstalled` and `StoreProtocolMismatch` fire at
`resolve_stores` time, before any control runs -- so a misconfigured
backend never wastes an audit.

## Performance notes

Two costs, both small:

* **Entry-point discovery** is a one-time per-process cost paid at
  framework load. `importlib.metadata.entry_points(group=...)` scans
  installed dist-info metadata; on a fresh venv with ~50 installed
  packages we measure single-digit milliseconds. The `discover_stores`
  wrapper caches the result per group so subsequent audits in the same
  process pay zero.
* **Lazy instantiation** adds one dict lookup per audit run per
  artifact class. A store whose kind the run never touches is never
  constructed at all -- ideal for expensive-to-open backends (network
  clients, DB connections). The bundle's per-property accessor memoizes,
  so second access is a straight attribute read.

Practical implication: your `__init__` cost is charged to the first
audit in a process that actually uses the artifact class you back --
never to zero-config runs, never to audits that skip your kind. Keep
`__init__` cheap and open connections on first `write` if the backend
is expensive to establish.

---

# Writing artifacts outside the repo (feature 034)

Feature 034 ships two additional filesystem-backed backends inside
darnit-core alongside the in-repo defaults. Both are selectable from
`.baseline.toml` under any `[stores.<kind>]` block; both write outside
the audited repository. They exist because the in-repo defaults land
attestations, reports, and audit-cache under `<repo>/.darnit/`, which
is often not where an operator wants them (backups, CI artifact
directories, XDG-idiomatic locations).

## `local-fs`: arbitrary root path

Points a store at any local filesystem path. Config:

```toml
[stores.attestation]
backend = "local-fs"
root    = "/absolute/path"   # or "~/subpath", or "$VAR/subpath"
```

Path resolution runs in this order at store construction:

1. `$VAR` interpolation via darnit's env-subst helper. A missing
   variable raises `KeyError` immediately -- a typo does NOT silently
   expand to `""`. This is deliberate: `root` is a compliance-critical
   config value; loud failure beats surprise empty writes.
2. `~` expansion via `os.path.expanduser`.
3. Absolute `Path.resolve()`.

Directory creation is deferred to the first write. Filename
sanitization is inherited from the in-repo default -- a bundle_id
containing `../../etc/foo` produces a sanitized filename inside
`root`, not a path escape.

### Example: CI runner with persistent cache + report artifacts

```toml
[stores.cache]
backend = "local-fs"
root    = "$RUNNER_CACHE_DIR/darnit"

[stores.report]
backend = "local-fs"
root    = "$RUNNER_ARTIFACTS_DIR/darnit-reports"
```

- First-run: cache write goes to `$RUNNER_CACHE_DIR/darnit/`; next-run
  cache read hits because the runner restored the cache directory
  between jobs.
- Reports land where the runner's artifact-upload step already looks.
  Markdown / JSON / SARIF each become their own file under that root;
  one info log line per format.

### Multi-repo templating

Darnit has no org-level or user-level config file. If you want the
same `[stores.<kind>]` block active on 30 repos, use one of:

1. **Env-var interpolation (easiest)**. Keep `root = "$DARNIT_ATT_ROOT"`
   in every repo's `.baseline.toml`. Set `DARNIT_ATT_ROOT` once per
   machine (shell profile, systemd unit, CI runner env). The 30 repos
   share the destination without duplicating the literal path.
2. **CI/CD templating**. Your workflow rewrites `.baseline.toml` before
   invoking `darnit audit`.
3. **Cookiecutter / repo-init tool**. One-shot copy the block into
   each repo when you first onboard it.

### The `.project/` layer (FR-009)

Neither `local-fs` nor `user-local` is registered under
`darnit.stores.project`. `.project/project.yaml` is the CNCF
`.project/` spec's canonical repo-committable artifact and stays in
the repo by design. If you write `[stores.project] backend = "local-fs"`
in `.baseline.toml`, `resolve_stores` raises `StoreNotInstalled`
before any control runs -- the misconfiguration surfaces at audit
start, not in a confusing runtime failure. Redirecting project state
outside the repo means governance tooling can no longer find it, so
this is not supported.

## `user-local`: platform-conventional root

Points a store at the platform-idiomatic user-scoped location. No
`root` config needed. Example:

```toml
[stores.attestation]
backend = "user-local"

[stores.report]
backend = "user-local"

[stores.cache]
backend = "user-local"
```

Resolved paths per platform:

| Platform | Attestations / Reports (data) | Cache |
|---|---|---|
| Linux (XDG defaults) | `~/.local/share/darnit/...` | `~/.cache/darnit/...` |
| Linux (`XDG_DATA_HOME=/X`) | `/X/darnit/...` | (see `XDG_CACHE_HOME`) |
| macOS | `~/Library/Application Support/darnit/...` | `~/Library/Caches/darnit/...` |
| Windows | `%LOCALAPPDATA%\darnit\Data\...` | `%LOCALAPPDATA%\darnit\Cache\...` |
| Unknown | XDG fallback (same as Linux) | XDG fallback |

Passing a `root` kwarg to a `user-local` backend logs a warning and
uses the platform default anyway. Less disruptive than a hard error
for operators who copied a snippet from a `local-fs` example.

## Logging

Every successful outside-repo write emits one info-level log line to
the `darnit.stores.local` logger:

```
INFO darnit.stores.local: wrote attestation (local-fs): /home/mike/darnit-attestations/acme-widget-baseline-attestation.intoto.json
```

The in-repo `Filesystem*Store` defaults do NOT emit to this logger, so
zero-config audits stay log-silent under `darnit.stores.local`.

## Zero-config unchanged

If you do NOT add `[stores.*]` blocks, artifacts continue to land in
`<repo>/.darnit/` exactly as before this feature. `local-fs` and
`user-local` are opt-in.

## Troubleshooting

- **`KeyError: DARNIT_ATT_ROOT`**: the env var referenced in `root`
  isn't set. `local-fs` fails fast on missing vars by design. Export
  the variable or use a literal path.
- **`StoreOperationError: [local-fs attestation @ ...]`**: the
  resolved `root` is unwritable, the disk is full, or the file is
  locked. The error message names the backend, kind, and resolved path
  so the operator can correlate. Darnit does NOT silently fall back
  to the in-repo default.
- **File landed with `_`s in the name**: your identifier contained
  filesystem-unsafe characters. The store sanitized them to prevent
  path traversal. Rename the caller's identifier for cleaner output.
