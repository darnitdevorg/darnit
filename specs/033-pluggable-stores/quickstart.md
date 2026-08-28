# Quickstart: pluggable stores

Three worked examples: operator selects a backend, plugin author distributes one, operator backs out.

## Example 1: Operator selects a Postgres backend for project state

The operator's fleet already runs `darnit audit` against many repositories. They want project state (the CNCF `.project/` YAML tree) to live in a shared Postgres instance instead of being duplicated on-disk in every repo checkout.

### Prerequisites

- A published Python package that registers a `ProjectStateStore` implementation under `darnit.stores.project`. For this example, assume that package is called `darnit-store-postgres` (see #391 for the actual implementation once it lands).
- `pip install darnit-store-postgres` in the environment where `darnit audit` runs.

### `.baseline.toml`

```toml
extends = "openssf-baseline"

[stores.project]
backend = "postgres"
dsn = "$PG_DSN"
schema = "darnit"
```

`$PG_DSN` gets substituted from `os.environ["PG_DSN"]` at load time; if it is unset, it substitutes as empty string (which the Postgres backend will reject with a clear error at connect time).

### What happens at audit time

1. Framework loads `.baseline.toml`. The `[stores.project]` block validates as `StoreBlock(backend="postgres", ...)`. `$PG_DSN` substitutes.
2. Framework calls `discover_stores("darnit.stores.project")` (once, at framework-load time). Finds one entry point named `postgres` registered by `darnit-store-postgres`.
3. Framework instantiates `PostgresProjectStateStore(dsn="postgres://...", schema="darnit")` lazily on first project-state read.
4. `DotProjectReader` uses the store; `read_project()` returns the `ProjectConfig` loaded from Postgres, not from the local `.project/` directory.
5. At audit end, framework calls `store.close()` exactly once (releases the connection pool).

### Verification

- `.project/` on local disk is not touched. `strace`-style inspection or a spy on `open()` would confirm zero reads.
- The audit's control verdicts are identical to what they would be if the same data lived at `.project/project.yaml`. Fixture-driven equivalence test (SC-002) proves this.

## Example 2: Plugin author distributes a new AttestationStore

An operator wants attestations shipped to their internal S3 bucket. No such backend exists. They author one.

### Package layout

```text
darnit-store-s3-attestation/
├── pyproject.toml
├── README.md
└── src/darnit_store_s3_attestation/
    ├── __init__.py
    └── backend.py
```

### `pyproject.toml`

```toml
[project]
name = "darnit-store-s3-attestation"
version = "0.1.0"
dependencies = ["boto3>=1.34"]

[project.entry-points."darnit.stores.attestation"]
s3 = "darnit_store_s3_attestation.backend:S3AttestationStore"
```

### `backend.py`

```python
import boto3
from darnit.stores.protocols import AttestationStore


class S3AttestationStore:  # duck-typed against Protocol; no explicit inheritance needed
    def __init__(self, *, bucket: str, region: str, prefix: str = ""):
        self._bucket = bucket
        self._prefix = prefix
        self._client = boto3.client("s3", region_name=region)

    def write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None:
        key = f"{self._prefix}{bundle_id}.intoto.json"  # naming stays in the plugin
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=bundle_bytes,
            ContentType=content_type,
        )

    def close(self) -> None:
        # boto3 clients hold connection pools; explicit close is a no-op
        # in newer boto3 versions, but we call it for symmetry.
        pass


# Sanity check (also run in the plugin's own tests):
assert isinstance(S3AttestationStore(bucket="test", region="us-east-1"), AttestationStore)
```

### Install and verify

```sh
pip install -e .
python -c "
from darnit.stores.discovery import discover_stores
found = discover_stores('darnit.stores.attestation')
print(found)  # {'s3': <class 'darnit_store_s3_attestation.backend.S3AttestationStore'>}
"
```

### `.baseline.toml`

```toml
[stores.attestation]
backend = "s3"
bucket = "my-fleet-attestations"
region = "us-east-1"
prefix = "audits/$AUDIT_DATE/"
```

### What happens at audit time

Same shape as Example 1: framework discovers, operator selects, framework instantiates lazily, calls `store.write(bundle_id, bytes, content_type)` for each generated attestation, calls `store.close()` at audit end.

## Example 3: Operator backs out

The operator experimented with the Postgres project-state backend from Example 1 and wants to revert.

### Change

Remove the `[stores.project]` block from `.baseline.toml`. Do NOT need to uninstall the plugin package; the plugin is only consulted when it's actively selected.

### What happens at audit time

- Framework loads `.baseline.toml`. `stores.project` is `None`.
- Framework uses `FilesystemProjectStateStore(repo_path)` (the default). Reads/writes go to `.project/project.yaml` and `.project/maintainers.yaml` in the local repo.
- `PostgresProjectStateStore` is never instantiated. `close()` never called on it (there is no instance to close).

### Verification

- Audit behaves identically to how it did before the operator ever tried the Postgres backend.
- If the `.project/` directory is missing from the local repo (because it was migrated to Postgres and never re-checked-in), `read_project()` returns `None` and the affected controls resolve WARN with a message identifying the missing `.project/` -- the same behavior as if the operator started with an empty checkout.

## Failure-mode diagnostics quick reference

| Symptom | What it means | Fix |
|---------|---------------|-----|
| `StoreNotInstalled: no store registered under 'darnit.stores.project' with name 'postgres'` | Selected a backend whose plugin isn't installed. | `pip install darnit-store-postgres`, or remove/change the `[stores.project]` selection. |
| `StoreProtocolMismatch: 'postgres' does not satisfy ProjectStateStore (missing method 'write_maintainers')` | Plugin's registered class is out of date with the current Protocol. | Update the plugin package (`pip install -U darnit-store-postgres`), or file an issue against the plugin's maintainer. |
| `StoreNameCollision: two entry points register 's3' under 'darnit.stores.attestation': darnit-store-s3-attestation, my-other-plugin` | Two installed plugins claim the same short name. | Uninstall one, or rename the entry point in one plugin's `pyproject.toml`. |
| Log line "AttestationStore.write failed" but audit reports success | This should never happen -- see FR-012 (no silent fallback). If seen, file a bug against darnit. |
| Cache read log line "cache read failed, treating as miss" | Best-effort cache path per FR-011. Not a compliance error; audit continues. If frequent, investigate the cache backend. |

## Where to look next

- Contracts: `contracts/` -- exhaustive field, method, and failure-mode tables for each Protocol.
- Data model: `data-model.md` -- the schema types this feature adds.
- Research decisions: `research.md` -- why entry-point discovery at framework-load, why `_StoreBundle` in `_run_audit`, why `darnit.core.env_subst`.
- Consumer of this abstraction: [#391](https://github.com/darnitdevorg/darnit/issues/391) -- first non-filesystem `ProjectStateStore` (Postgres).
