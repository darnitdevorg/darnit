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
