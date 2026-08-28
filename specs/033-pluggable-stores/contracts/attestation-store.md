# Contract: `AttestationStore` Protocol

**Owner**: `packages/darnit/src/darnit/stores/protocols.py`

**Registered under**: `darnit.stores.attestation` entry-point group

**Stability**: Public API. Write-only surface in v0; read-back is an additive extension if needed.

## Purpose

Persist attestation bundles produced by darnit-baseline's attestation generator. Attestations are consumed downstream by other tooling (Sigstore, in-toto verifiers, GUAC ingestion), not by darnit itself.

## TOML surface

```toml
[stores.attestation]
backend = "s3"
bucket = "my-fleet-attestations"
region = "us-east-1"
access_key_id = "$AWS_ACCESS_KEY_ID"
secret_access_key = "$AWS_SECRET_ACCESS_KEY"
```

## Methods

### `close(self) -> None`

Inherited from `Store`.

### `write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None`

Persist an attestation bundle.

- **`bundle_id`**: Stable, filesystem-safe identifier that correlates the bundle with the audit run that produced it. Recommended shape: `<owner>-<repo>-<audit-run-id>-<control-id>`. Backends MAY encode this into their storage key however they want (path segment, object key, primary key); the framework does not care.
- **`bundle_bytes`**: The serialized attestation. Framework provides the exact bytes it would have written to disk under the filesystem default.
- **`content_type`**: Media type of the bundle. Common values: `"application/vnd.in-toto+json"` for in-toto Statement v1, `"application/vnd.dev.sigstore.bundle+json"` for Sigstore bundles.
- **Raises**: `StoreOperationError` on any backend failure. Framework surfaces the error as an audit-run failure; the attestation is NOT reported as persisted.
- **Atomicity**: Per-call atomic (write commits or does not; no partial state).
- **Concurrency**: Sync in v0. Single-caller assumed within an audit run.

## Failure semantics

Per FR-011:

| Failure | Consequence |
|---------|-------------|
| `write` raises | Audit-run error surfaced with the store's error message. Attestation is NOT reported as persisted. |
| `close()` raises | Logged; framework does NOT re-raise. |

Rationale for stricter-than-cache semantics: an attestation that quietly failed to persist is a compliance record that quietly didn't happen. Constitution II demands the error be visible.

## Consumers

- `packages/darnit-baseline/src/darnit_baseline/attestation/generator.py::generate_attestation_from_results` -- sole call site today; the hard-coded `open(output_path, 'w')` at line 138 becomes `attestation_store.write(bundle_id, bundle_bytes, content_type)`.
- Future callers who write attestations (a fleet MCP server that batches audits, a re-attestation tool) should also consume through this Protocol.

## Filesystem default

`darnit.stores.defaults.attestation.FilesystemAttestationStore(root: Path)`:

- Writes each bundle to `<root>/<bundle_id>.<ext>` where `<ext>` is derived from `content_type` (e.g., `.intoto.json` for in-toto, `.sigstore.json` for Sigstore).
- `root` defaults to `.darnit/attestations/`.
- `close()` is a no-op.

## Non-goals for v0

- Read-back / enumeration of stored bundles (add `list_bundles()` as an additive Protocol extension if needed).
- Delete operations.
- Cross-bundle atomicity (each `write()` is independent).
- Signature validation (that's the downstream verifier's job; the store is a dumb persistence surface).
