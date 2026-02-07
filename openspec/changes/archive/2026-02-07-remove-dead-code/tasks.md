## 1. Remove dead modules (dependency order)

- [x] 1.1 Delete `scripts/create-test-repo.sh`
- [x] 1.2 Delete `packages/darnit/src/darnit/config/validation.py`

## 2. Migrate models.py consumers

- [x] 2.1 In `packages/darnit/src/darnit/remediation/executor.py` line 669, change `from darnit.config.models import ProjectConfig` → `from darnit.config.schema import ProjectConfig`
- [x] 2.2 In `packages/darnit/src/darnit/attestation/predicate.py` line 11, change `from darnit.config.models import ProjectConfig` → `from darnit.config.schema import ProjectConfig`
- [x] 2.3 In `packages/darnit/src/darnit/config/__init__.py` lines 121-126, remove the legacy re-exports block (`ControlStatus`, `ReferenceStatus`, `ResourceReference` from `.models`)
- [x] 2.4 Delete `packages/darnit/src/darnit/config/models.py`

## 3. Update documentation

- [x] 3.1 In `docs/FRAMEWORK_DESIGN.md` line 821, change `from ..config.models import ProjectConfig` → `from ..config.schema import ProjectConfig`

## 4. Verify

- [x] 4.1 Run `uv run ruff check .` — no lint errors
- [x] 4.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — all tests pass (793 passed, 1 skipped)
- [x] 4.3 Grep for stale references: `config.models`, `config.validation`, `create-test-repo.sh` — no hits in packages/
