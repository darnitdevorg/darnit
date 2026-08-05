# Data Model: E2E Regression Baseline for `darnit run`

**Feature**: 024-cmd-run-e2e-tests
**Date**: 2026-08-05

This is a test-only feature; there is no new production data model. This document enumerates the *test-fixture* entities so a future maintainer can extend or move them without archaeology.

---

## Fixture entities

### 1. `MinimalRepo` fixture tree

**Location**: `tests/darnit/cli/fixtures/minimal_repo/`

**Purpose**: The single-repo tree used by the golden-path and deterministic-only tests. Sized to produce zero FAIL results against every `testchecks` control at levels 1-3 (which is what `cmd_run` exercises by default, since it inherits `state.level = 3`).

**Structure**:

```text
tests/darnit/cli/fixtures/minimal_repo/
├── .baseline.toml                    # Selects framework = "testchecks"
├── .project/
│   └── project.yaml                  # Minimal project context (name only)
├── .editorconfig                     # Satisfies TEST-CFG-01
├── .gitignore                        # Satisfies TEST-SEC-02 + TEST-IGN-01
├── .pre-commit-config.yaml           # Satisfies TEST-CFG-02
├── .github/
│   └── workflows/
│       └── ci.yml                    # Satisfies TEST-CI-01 + TEST-CI-02
├── CHANGELOG.md                      # Satisfies TEST-DOC-02
├── LICENSE                           # Satisfies TEST-LIC-01
├── README.md                         # Satisfies TEST-DOC-01
└── hello.py                          # Satisfies TEST-QA-01, TEST-QA-02, TEST-SEC-01
```

**Per-file content requirements** (all ASCII, all minimal):

- `.baseline.toml`: `framework = "testchecks"`. Nothing else.
- `.project/project.yaml`: `name: minimal-repo`. Nothing else.
- `README.md`: two lines. Any ASCII content.
- `CHANGELOG.md`: one line, e.g. `# Changelog`.
- `LICENSE`: any short ASCII license notice (Apache-2.0 header is fine).
- `.editorconfig`: one line, e.g. `root = true`.
- `.pre-commit-config.yaml`: `repos: []` is sufficient (file existence is the check).
- `.gitignore`: MUST contain the literal substrings `.env`, `*.key` (or `*.pem`), and `credentials` (or `secrets`) to satisfy TEST-SEC-02's three sub-patterns. TEST-IGN-01 only checks the file exists.
- `.github/workflows/ci.yml`: MUST contain one of `npm test`, `pytest`, `go test`, `cargo test`, `mvn test`, or `make test` (TEST-CI-02 regex). Simplest working content: `jobs:\n  test:\n    steps:\n      - run: pytest`.
- `hello.py`: MUST NOT contain any of the substrings `TODO` (case-sensitive, in a comment) (TEST-QA-01), `print(` at line start (TEST-QA-02), or `password="..."` / `secret="..."` / `api_key="..."` string assignments (TEST-SEC-01). A trivial `def hi() -> str:\n    return "hi"\n` file satisfies all three. Kept as a real `.py` file (not empty) so the pattern handlers see something to scan; empty-glob paths return INCONCLUSIVE not PASS.

**Invariants**:
- The tree, once copied into `tmp_path` and `git init`'d, produces zero `FAIL` results from `testchecks` at level 3. This lets `test_golden_exit_code_matches_failed_count` pin BOTH `exit_code == 0` AND the rule that derives it.
- Total number of results is deterministic (fixed at fixture-write time). Tests pin the RULE `exit_code == (1 if failed > 0 else 0)` rather than the specific counts, so a future testchecks control addition that produces a FAIL will surface as a genuine golden-path failure worth investigating.
- No `.git/` directory is checked in. `conftest.py` runs `git init` after copy so `detect_repo_from_git` finds a real repo (even without a remote).
- All content is ASCII (contract C9, FR-012).

**Handler-behavior note**: The three "no forbidden pattern" testchecks controls (TEST-QA-01, TEST-QA-02, TEST-SEC-01) use `pass_if_any = false` on globs like `**/*.py`. If the fixture had no matching files, the regex handler returns INCONCLUSIVE (which counts as WARN, not PASS). The presence of `hello.py` (with no forbidden patterns) is therefore required to convert those results to PASS. Removing `hello.py` would cause three WARN entries and would not affect the zero-FAIL invariant, but would change golden-path counts.

---

### 2. `MalformedProjectYaml` fixture tree

**Location**: `tests/darnit/cli/fixtures/malformed_project/`

**Purpose**: Failure-path test for User Story 3, acceptance #3.

**Structure**:

```text
tests/darnit/cli/fixtures/malformed_project/
├── .baseline.toml          # Same as MinimalRepo -- framework = "testchecks"
└── .project/
    └── project.yaml        # Intentionally invalid YAML
```

**Invariants**:
- `.project/project.yaml` fails `yaml.safe_load` with a `YAMLError` subclass.
- The specific malformation (unclosed bracket) is chosen for clarity of the error message, not for its parser-implementation specificity.

---

### 3. `PendingFeedbackRepo` fixture tree

**Location**: `tests/darnit/cli/fixtures/pending_feedback_repo/`

**Purpose**: Pending-feedback assertion (User Story 3, acceptance #4).

**Structure**: Same layout as `MinimalRepo`, but its `.baseline.toml` (or a companion configuration under `testchecks.toml`) enables at least one control that requires a user-judgment context key (e.g. `maintainers`). The `testchecks` framework MUST provide such a control for this fixture to work; if it does not, this fixture is dropped and User Story 3 acceptance #4 is scoped down to "not tested here" with an inline `pytest.skip` explaining why.

**Deferred**: Concrete testchecks control choice is a Phase 2 (tasks) decision. If `testchecks` does not currently emit any feedback question, the tasks phase MAY:
- (a) Add a trivial `testchecks` control that does emit one (implementation-side change, would exit test-only scope; requires escalation), OR
- (b) Reuse the same `MinimalRepo` fixture and skip acceptance #4 with a documented `TODO(#359)` marker.

---

### 4. Stub registry (in-test state)

**Location**: `tests/darnit/cli/conftest.py`, two module-level constants.

**Purpose**: Two separate stub tiers, applied together by the `deterministic_run` fixture, that cover distinct guarantees.

**Rationale for two tiers (not one)**: The golden path REQUIRES `subprocess.run` to work: `cmd_run` -> `prepare_audit` (`packages/darnit/src/darnit/tools/audit.py:215`) -> `detect_repo_from_git` -> `_get_remote_url` (`packages/darnit/src/darnit/core/utils.py:158`) shells out to `git remote get-url`. If `subprocess.run` raises, `prepare_audit` sets `state.error` and the golden-path assertions collapse. So subprocess needs a canned-success stub, not a raising stub. Meanwhile, LLM and MCP entry points must NEVER be called from `cmd_run`; those get raising stubs to catch any future accidental introduction.

**Tier 1: `_MUST_NOT_BE_CALLED`** -- LLM and MCP entry points; stubbed to raise.

```python
# In tests/darnit/cli/conftest.py:
_MUST_NOT_BE_CALLED: tuple[tuple[str, str], ...] = (
    # (module_path, attr_name). Each patched with side_effect=RuntimeError so
    # any invocation surfaces as a named failure identifying the call site.
    # LLM SDK entry points reachable at test time (grep confirms none are
    # imported today; listing them defensively so future imports trip the guard):
    # ("openai", "ChatCompletion"),        # add if openai gets imported
    # ("anthropic", "Anthropic"),          # add if anthropic gets imported
    # MCP client entry points reachable at test time:
    # ("fastmcp.client", "Client"),        # add if fastmcp client gets used from cmd_run codepath
    # Placeholder: empty tuple is acceptable until an LLM/MCP entry point
    # actually becomes importable from cmd_run's transitive closure.
)
```

**Tier 2: `_SUBPROCESS_STUBS`** -- subprocess call sites; stubbed to return `CompletedProcess`-like canned success (or graceful "not found" for git remote).

```python
# In tests/darnit/cli/conftest.py:
from subprocess import CompletedProcess

def _fake_git_remote_get_url(cmd, *args, **kwargs):
    """`git remote get-url ...` -> return exit 2, empty stdout (matches
    real-git behavior for a repo with no remotes). detect_repo_from_git
    handles this gracefully by returning None and letting prepare_audit
    return its "Could not auto-detect" error path.

    For the golden path where auto-detect is not required, set the fixture
    to include a remote OR override this stub locally in the test.
    """
    return CompletedProcess(args=cmd, returncode=2, stdout="", stderr="fatal: No such remote\n")

def _fake_generic_subprocess_run(cmd, *args, **kwargs):
    """Default: return exit 0 with empty stdout. Individual tests may
    monkeypatch this with a more specific canned response."""
    return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

_SUBPROCESS_STUBS: tuple[tuple[str, str], ...] = (
    ("darnit.core.utils", "subprocess"),          # _get_remote_url, _gh_enrich
    ("darnit.sieve.builtin_handlers", "subprocess"),  # exec handler (belt-and-suspenders)
)
```

The `deterministic_run(monkeypatch)` fixture applies:
- `_MUST_NOT_BE_CALLED`: `monkeypatch.setattr(<module>, <attr>, Mock(side_effect=RuntimeError("must not be called: <dotted-name>")))`
- `_SUBPROCESS_STUBS`: `monkeypatch.setattr(<module>, "subprocess", <a namespace object exposing .run=_fake_generic_subprocess_run and .PIPE/.STDOUT constants and .CalledProcessError class>)`. Since `_get_remote_url` uses `subprocess.run(["git", "remote", "get-url", ...])`, tests that need auto-detect to succeed override the fake to return a canned remote URL.

**Invariants**:
- Every entry in `_MUST_NOT_BE_CALLED` and `_SUBPROCESS_STUBS` corresponds to an actual attribute that exists at test-collection time. A collection-time guard asserts this so a production-code rename produces a helpful test-collection error instead of a silent bypass.
- The two tuples live in `conftest.py` (not in the test file) so the same lists are reusable if a second test file ever exercises the same guarantees.
- The `_MUST_NOT_BE_CALLED` tuple is allowed to be empty until an LLM/MCP entry point actually becomes importable from the `cmd_run` transitive closure. The tuple existing (even if empty) is the mechanism that future maintainers extend when they wire an LLM SDK; the collection-time guard skips gracefully on an empty tuple.

---

### 5. Observable-output snapshot

**Location**: not a file. In-test string assertions.

**Purpose**: The set of substring / structural assertions that constitute the pinned output contract. Documented in full at `contracts/cmd_run-output.md`.

**Shape**: See contracts/cmd_run-output.md.

---

## Non-entities (things this feature explicitly does NOT introduce)

- No new production dataclasses, TypedDicts, or Pydantic models.
- No new fields on `AuditState`, `CheckResult`, or `FeedbackQuestion`.
- No new framework configuration schema.
- No new `.baseline.toml` fields.
- No new CLI flags.
- No shared test fixture at the root `tests/conftest.py` level. All fixtures for this feature live under `tests/darnit/cli/`.
