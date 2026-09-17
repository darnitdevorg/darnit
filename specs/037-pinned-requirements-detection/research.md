# Phase 0 Research: Pinned-Requirements Detection

**Feature**: 037 | **Date**: 2026-09-17

Each decision below was verified against the code in this repository rather than inferred. File and line references are to the state of `main` at `b83c006`.

---

## R1: How a handler expresses a conclusive WARN

**Decision**: add `WARN` to `HandlerResultStatus`, add `StepDisposition.CONCLUDE_WARN`, and gate it through the existing feature 025 authority rule exactly as PASS and FAIL are gated.

Concretely, `resolve_step_result` (`orchestrator.py:56`) currently reads:

```python
if handler_status in (HandlerResultStatus.PASS, HandlerResultStatus.FAIL):
    if is_terminal_authority(effective_authority):
        return CONCLUDE_PASS if PASS else CONCLUDE_FAIL
    if is_last_step:
        return TERMINATE_INCONCLUSIVE
    return ATTACH_EVIDENCE_AND_CONTINUE
```

WARN joins that first tuple and maps to `CONCLUDE_WARN` under terminal authority. A suggestive or authority-less WARN attaches evidence and continues, identical to a suggestive PASS.

**Rationale**: the authority gate is the mechanism feature 025 introduced so that a non-authoritative step cannot conclude a control. A WARN that bypassed it would let an LLM step (suggestive) halt verification before a dispositive step ever ran. That is the safe direction for compliance arithmetic, but it would silently reduce how much verification actually happens, and it would make WARN the one outcome exempt from the rule the rest of the pipeline obeys. Symmetry is both safer and easier to reason about.

`repro_deps_pinned` is registered `default_authority="dispositive"` (`darnit-reproducibility/implementation.py:125`), so its WARN concludes.

**Alternatives considered**:
- *Handler returns INCONCLUSIVE; rely on the all-inconclusive fallthrough* (`orchestrator.py:585`). Rejected during `/speckit-clarify`: the fallthrough emits a fixed string and drops the handler's message, so the operator reads "Could not automatically verify" about a file the tool read successfully.
- *Make the fallthrough carry the last handler message.* Rejected: `RE-01.01`'s last pass is `manual`, which always returns INCONCLUSIVE, so the last message is the manual placeholder's. Selecting "last non-manual message" is the fragility feature 036 already had to work around for `error_class`.
- *WARN concludes regardless of authority.* Rejected as above.

---

## R2: Whether `PassOutcome` also gains WARN

**Decision**: yes. `PassOutcome` (`sieve/models.py:22`) gains `WARN = "warn"`, and `_handler_status_to_outcome` (`orchestrator.py:904`) maps `HandlerResultStatus.WARN -> PassOutcome.WARN`.

**Rationale**: `PassOutcome` records what an individual pass decided, and it feeds `pass_history`, which is the audit trail FR-012 expects a reviewer to be able to read. Mapping a pass that concluded WARN to INCONCLUSIVE would put the control's status (WARN) and its own history ("this pass reached no conclusion") in contradiction.

**Blast radius, measured**: `PassOutcome.<member>` appears in exactly two product files -- `sieve/orchestrator.py` and `harness/driver.py`. The harness only ever constructs values (`driver.py:303, 317, 324-328`); it never matches exhaustively, so a new member cannot fall through a branch there. `_handler_status_to_outcome` already ends in `mapping.get(status, PassOutcome.INCONCLUSIVE)`, which means an unmapped member degrades to INCONCLUSIVE rather than raising -- the safe direction, and the reason the explicit mapping entry must be added deliberately rather than relied upon.

**Alternative considered**: map WARN to `PassOutcome.INCONCLUSIVE` and change nothing else. One line, and it would work, but it deliberately falsifies the audit trail. Recorded in plan.md Complexity Tracking.

---

## R3: Interaction with the CEL post-step

**Decision**: `_apply_cel_expr` (`orchestrator.py:88`) leaves a WARN result untouched. Its existing guard already does this -- it returns early unless the status is PASS or FAIL (`orchestrator.py:120-125`) -- so the correct implementation is to add no code and add a test that pins the behavior.

**Rationale**: the CEL transition table (documented in the function's docstring and in `specs/020-definitive-fail-verdict/contracts/cel-post-step.md`) exists to reconcile a handler's verdict with an expression over its evidence, and it has a defined answer only for PASS and FAIL. There is no meaningful "CEL disagrees with WARN" cell: WARN already means the evidence is incomplete.

**Why this gets a test rather than a shrug**: feature 026 and feature 036 both shipped bugs of exactly this shape -- a new `HandlerResult` field that was silently dropped at one of the three `HandlerResult(...)` construction sites inside `_apply_cel_expr`. A status is not a field, so the mechanism differs, but the lesson is that this function is where new result vocabulary goes to get lost. Pin it.

---

## R4: Parsing PEP 440 requirements

**Decision**: use `packaging` (`packaging.requirements.Requirement`, `packaging.specifiers.SpecifierSet`), and declare it explicitly in `packages/darnit-reproducibility/pyproject.toml`.

**Verified facts**:
- `packaging` 26.0 resolves in the workspace venv today, but `uv pip show packaging` reports `Required-by: pytest` -- that is, it is present as a *test* dependency.
- `darnit` core already imports it at runtime in two places: `core/composition.py:363-364` and `config/framework_schema.py:1445`. Neither declares it. The comment at `framework_schema.py:1443` asserts that "`packaging` is a transitive dep via setuptools and is already part of every Python install with pip available," which is not reliable -- pip and setuptools vendor their own copies, and neither guarantees an importable top-level `packaging` in an arbitrary environment.

**Rationale**: FR-015 forbids a new runtime dependency *outside the existing darnit dependency set*. `packaging` is already inside the runtime import set of `darnit` core, so using it here adds nothing new to what a darnit install must be able to import. Declaring it is a correctness fix for a latent packaging bug, not the introduction of a dependency. Shipping this feature with a third undeclared runtime import would be the choice that actually violates FR-015's intent.

The alternative is a hand-rolled parser, and FR-008 through FR-010 enumerate precisely the cases hand-rolled parsers get wrong: `pkg==1.*` looks pinned to a substring check, `pkg>=1.0,<2.0` contains no `==` but must still parse, extras and environment markers decorate the name and the tail. Reimplementing PEP 440 to avoid declaring a dependency that is already imported twice is a bad trade.

**Carried out of scope**: core's two undeclared imports are a pre-existing defect that this feature does not fix. File a follow-up issue; do not expand this branch into a packaging-metadata audit.

---

## R5: Preprocessing before `Requirement()` sees a line

**Decision**: a line goes through a preprocessing pass before parsing. Verified behavior of `packaging.requirements.Requirement` in the workspace venv:

| Input | Result |
|---|---|
| `numpy==1.26.4 --hash=sha256:abc` | `InvalidRequirement` -- it does not know about hashes |
| `-e .` | `InvalidRequirement` -- "Expected package name at the start" |
| `numpy` | parses, `specifier` empty |
| `pkg[extra]==1.* ; python_version < "3.11"` | parses, specifier `==1.*` |
| `pkg @ git+https://x/y@<40 hex>` | parses, `url` set, `specifier` empty |

So preprocessing must, in order: join backslash continuations; strip comments; drop blank lines; split off and collect `--hash=` values; skip pip option lines and `-e .`-style self-references (FR-018); and only then hand the remainder to `Requirement`.

**Rationale**: this is not a design choice so much as a consequence of what the library accepts. Recording it here so the implementation does not discover it as a test failure.

**Note on `--hash` placement**: hashes may appear on continuation lines, which is the shape `pip-compile --generate-hashes` actually emits. Continuation joining must therefore happen before hash extraction, not after.

---

## R6: Recognizing a commit-SHA-pinned VCS reference

**Decision**: a direct reference is pinned when its URL fragment after the final `@` is a full hexadecimal object id -- 40 characters (SHA-1) or 64 (SHA-256). Anything shorter, or anything non-hexadecimal, is a branch or tag and is not pinned.

**Rationale**: an abbreviated SHA is ambiguous by construction and git's own disambiguation depends on repository state at resolve time, so it does not pin. Accepting 64 as well as 40 avoids a needless failure when a repository has migrated to SHA-256 object ids.

**Tier**: per FR-010, a SHA-pinned reference is exactly identified but is *not* hash evidence, so a file containing one classifies at best version-pinned. `Requirement` exposes this cleanly: `url` is set and `specifier` is empty, which distinguishes it from a version-specified requirement without string surgery.

---

## R7: Establishing the SC-004 / SC-005 baseline

**Decision**: capture the before-change control output for the lock-file and no-dependency-files fixtures as committed golden files, generated from unmodified code *before* any implementation task begins, and assert against them afterwards.

**Rationale**: SC-004 and SC-005 claim byte-identical output across the change. A golden generated after the change is circular -- it proves the code agrees with itself. This repository has already made that decision once: feature 028's parity work rejected `syrupy` because `--snapshot-update` absorbs regressions silently rather than surfacing them. Same reasoning, same conclusion.

**Ordering consequence for `/speckit-tasks`**: baseline capture is a Foundational-phase task that must precede every implementation task, and it must run on a clean tree. If it lands after the first source edit, SC-004 and SC-005 are unverifiable and the only honest options are to re-derive the baseline from `git stash` or to weaken the criteria.

---

## R8: Verifying SC-008 (no existing control's status moves)

**Decision**: assert it mechanically rather than by inspection. Run the full control set against the existing fixture corpus before and after, and diff per-control status.

**Rationale**: SC-008 is the claim that makes the framework change acceptable, and it is exactly the kind of claim that is easy to assert and hard to notice breaking. The structural argument is strong -- no existing handler returns the new member, so no existing dispatch path changes -- but the argument is about the code as currently written, and the diff is about the code as it actually runs.

**Note**: this shares its baseline-capture mechanics with R7 and should reuse them rather than build a second harness.
