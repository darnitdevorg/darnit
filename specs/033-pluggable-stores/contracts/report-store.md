# Contract: `ReportStore` Protocol

**Owner**: `packages/darnit/src/darnit/stores/protocols.py`

**Registered under**: `darnit.stores.report` entry-point group

**Stability**: Public API. The three write methods are stable. Additional formats are additive Protocol extensions.

## Purpose

Persist audit reports in the three supported formats. In v0, this Protocol has no in-tree consumer (see #341); it exists so downstream features that write reports (starting with #341's CLI SARIF/Markdown emit) can consume through the Protocol without having to introduce the abstraction retroactively.

## TOML surface

```toml
[stores.report]
backend = "s3"
bucket = "my-fleet-reports"
region = "us-east-1"
prefix = "audits/$AUDIT_DATE/"
```

## Methods

### `close(self) -> None`

Inherited from `Store`.

### `write_markdown(self, report_id: str, content: str) -> None`

Persist a Markdown-formatted audit report.

- **`report_id`**: Stable identifier correlating the report with the audit run.
- **`content`**: The full Markdown text.
- **Raises**: `StoreOperationError` on backend failure.
- **Atomicity**: Per-call atomic.
- **Concurrency**: Sync in v0.

### `write_json(self, report_id: str, content: str) -> None`

Persist a JSON audit report. Same shape as `write_markdown`; the content is a JSON string.

### `write_sarif(self, report_id: str, content: str) -> None`

Persist a SARIF-formatted audit report. Same shape as above; the content is a SARIF JSON string.

## Failure semantics

Per FR-011:

| Failure | Consequence |
|---------|-------------|
| `write_*` raises | Audit-run error with the store's error and the format name (so the operator knows which of three writes failed). |
| `close()` raises | Logged; framework does NOT re-raise. |

## Consumers

- v0: none in the darnit tree. Filesystem default exists to enable #341 (CLI SARIF/Markdown emit) to write through the Protocol.
- Future callers should route report persistence through this Protocol rather than direct file I/O.

## Filesystem default

`darnit.stores.defaults.report.FilesystemReportStore(root: Path)`:

- Writes to `<root>/<report_id>.md`, `<root>/<report_id>.json`, `<root>/<report_id>.sarif` respectively.
- `close()` is a no-op.
- If `root` does not exist at write time, creates it (like the pre-feature behavior of `open(path, "w")` in a made-up directory would fail).

## Non-goals for v0

- Format registration (three formats, always these three, per Protocol design decision).
- Read-back of reports.
- Cross-format atomicity (each write independent).
- Format conversion (that's the formatter's job; the store persists what it's given).
