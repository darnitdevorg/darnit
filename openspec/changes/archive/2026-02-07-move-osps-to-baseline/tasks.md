## Tasks

### Group 1: Move attestation module to darnit-baseline

- [ ] Copy `packages/darnit/src/darnit/attestation/` (5 files: `__init__.py`, `generator.py`, `predicate.py`, `signing.py`, `git.py`) to `packages/darnit-baseline/src/darnit_baseline/attestation/`
- [ ] Update internal imports in the copied files from `darnit.attestation` to `darnit_baseline.attestation`
- [ ] Delete `packages/darnit/src/darnit/attestation/` directory
- [ ] Move tests from `tests/darnit/attestation/` to `tests/darnit_baseline/attestation/` and update imports
- [ ] Update `darnit_baseline/tools.py` line 652: change `from darnit.attestation import generate_attestation` to `from darnit_baseline.attestation import generate_attestation`

### Group 2: Move threat_model module to darnit-baseline

- [ ] Copy `packages/darnit/src/darnit/threat_model/` (6 files: `__init__.py`, `discovery.py`, `generators.py`, `models.py`, `patterns.py`, `stride.py`) to `packages/darnit-baseline/src/darnit_baseline/threat_model/`
- [ ] Update internal imports in the copied files from `darnit.threat_model` to `darnit_baseline.threat_model`
- [ ] Delete `packages/darnit/src/darnit/threat_model/` directory
- [ ] Move tests from `tests/darnit/threat_model/` to `tests/darnit_baseline/threat_model/` and update imports
- [ ] Update `darnit_baseline/tools.py` lines 567-576: change `from darnit.threat_model import ...` to `from darnit_baseline.threat_model import ...`

### Group 3: Parameterize format_results_markdown()

- [ ] Add `report_title: str = "Compliance Audit Report"` parameter to `format_results_markdown()` in `tools/audit.py`
- [ ] Add `remediation_map: dict | None = None` parameter to `format_results_markdown()`
- [ ] Replace hardcoded `"# OpenSSF Baseline Audit Report"` (line 574) with `f"# {report_title}"`
- [ ] Extract OSPS control-ID sets (lines 672-696) into a `_build_remediation_suggestions()` helper that reads from `remediation_map` parameter instead of hardcoded sets
- [ ] Replace hardcoded `"fix/openssf-baseline"` branch name (line 733) and `"OpenSSF Baseline"` strings in the git workflow section with values from `remediation_map`
- [ ] Update `builtin_audit.py` to pass `report_title` from implementation's `display_name` when calling `format_results_markdown()`
- [ ] Update `darnit_baseline/tools.py` `audit_openssf_baseline()` to define and pass the OSPS remediation map and title when calling `format_results_markdown()`

### Group 4: Clean up framework defaults

- [ ] In `core/discovery.py` `get_default_implementation()`: remove hardcoded `"openssf-baseline"` preference (lines 98-100), just return first discovered implementation
- [ ] In `server/tools/git_operations.py`: change default branch name from `"fix/openssf-baseline-compliance"` to `"fix/compliance"` (line 13)
- [ ] In `server/tools/git_operations.py`: replace OpenSSF-specific URLs and references with generic text in docstrings/messages
- [ ] In `cli.py`: update default framework help text and examples to be generic (keep the functional default as-is since openssf-baseline IS the only implementation currently)

### Group 5: Update darnit framework package metadata

- [ ] Remove `darnit.attestation` and `darnit.threat_model` from any `__init__.py` re-exports in the darnit package
- [ ] Remove attestation reference from `packages/darnit/README.md` (line 58)
- [ ] Verify no remaining imports of `darnit.attestation` or `darnit.threat_model` exist in `packages/darnit/`

### Group 6: Update specs

- [ ] Update `openspec/specs/framework-design/spec.md` Section 10 to require report formatter parameterization and add new section on framework purity (no implementation-specific code)

### Group 7: Verify

- [ ] Run `uv run ruff check .` — zero errors
- [ ] Run `uv run pytest tests/ --ignore=tests/integration/ -q` — all tests pass
- [ ] Grep: zero hits for `OSPS-` in `packages/darnit/src/darnit/` executable code (excluding comments)
- [ ] Grep: zero hits for `darnit.attestation` or `darnit.threat_model` in `packages/darnit/src/`
- [ ] Verify `packages/darnit/src/darnit/attestation/` directory does not exist
- [ ] Verify `packages/darnit/src/darnit/threat_model/` directory does not exist
