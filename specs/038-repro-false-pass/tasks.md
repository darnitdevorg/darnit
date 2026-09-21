---

description: "Task list for feature 038: Honest Verdicts for Reproducibility Controls"
---

# Tasks: Honest Verdicts for Reproducibility Controls

**Input**: Design documents from `/specs/038-repro-false-pass/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: included. SC-009 requires a fixture and asserted verdict for every edge case, and both contracts carry numbered test obligations.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 (#445), US2 (#431), US3 (#430), US4 (#432)
- Paths are repository-relative from `/Users/mlieberman/Projects/darnit`

**Two existing tests assert the behavior this feature removes.** They are not collateral damage to discover during implementation; they are T010 and T018. `TestBuildEnvDeclared::test_pass_with_dockerfile` writes `FROM python:3.11` and asserts PASS. `TestBitForBit::test_pass_with_source_date_epoch` asserts PASS. Both must change with the code that changes their subject.

---

## Phase 1: Setup

- [X] T001 Add a `repro_ctx` helper to `tests/darnit_reproducibility/conftest.py` that builds a `HandlerContext` for a tmp_path repo and a handler config with `verify_witness_attestations: false`. This is for T041's corpus test, which lives in its own file: tests added to the existing classes in `tests/darnit_reproducibility/test_handlers.py` already get network isolation from the autouse `_stub_witness_attestation` fixture at line 33, and should keep using it rather than a second mechanism.
- [X] T002 [P] Add a `dependency_results` parameter to that helper in `tests/darnit_reproducibility/conftest.py`, defaulting to empty, so the RE-01.02 gate in `_detect_strong_hermeticity_signal` can be exercised from tests without constructing a context by hand.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the reporting split that US4 needs before compiler-flag findings can be reported separately from network fetches.

**Blocking US4 only.** US1 and US2 touch different handlers. US3 only appends to `_SUSPICIOUS_PATTERNS`, whose matches classify as the existing `violation` kind, so it needs nothing from this phase either. Three of the four stories can start immediately.

- [X] T003 Add a `nondeterminism` member to `_ScanKind` in `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py`, alongside `safe`, `deferred`, and `violation`.
- [X] T004 Split the violation reporting in `repro_hermetic_build_handler` so network fetches and non-deterministic flags collect into separate buckets with separate messages. The existing message at `handlers.py:674` reads "Possible live network fetches in build files"; a compiler flag reported through it would be a false statement about what was found (contract HS C-3).
- [X] T005 [P] Extend `TestScanLine` in `tests/darnit_reproducibility/test_handlers.py` to cover the new kind, asserting that a `nondeterminism` match is not classified as `violation`.
- [X] T006 Add a test to `TestHermeticBuild` in `tests/darnit_reproducibility/test_handlers.py` for contract HS-9: the existing PASS conditions still fire after the T004 split -- a verified Witness attestation with a clean network log, and Bazel with a blocking flag. T004 restructures the violation buckets inside the same handler that holds those early-return PASS paths, which is exactly where a regression would land and where nothing else would catch it.

**Checkpoint**: the scan can distinguish the two finding types. US4 can begin.

---

## Phase 3: User Story 1 - Bit-for-bit reproducibility is not claimed without verification (Priority: P1)

**Goal**: RE-03.01 stops reporting a build as reproducible because a string appears in a workflow.

**Independent test**: a repo whose only evidence is `SOURCE_DATE_EPOCH` in one workflow returns WARN, and the message names both the signal and what stayed unverified.

**Why this is the smallest shippable increment**: one handler, one verdict, no new module, no cross-control effect. It closes the worst of the four issues on its own.

- [X] T007 [US1] Change the signals-found branch of `repro_bit_for_bit_handler` in `handlers.py` from PASS to `HandlerResultStatus.WARN` (FR-001). The handler is registered `default_authority="dispositive"`, so the WARN concludes rather than falling through.
- [X] T008 [US1] In `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py`, rewrite that result's message to name the signal found and state that bit-for-bit reproducibility was not verified, so "no evidence" and "promising evidence, unverified" are distinguishable (FR-002).
- [X] T009 [US1] Confirm the no-signals branch of `repro_bit_for_bit_handler` in `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py` is untouched and still returns INCONCLUSIVE with its existing message (FR-003).
- [X] T010 [US1] Update `TestBitForBit::test_pass_with_source_date_epoch` in `tests/darnit_reproducibility/test_handlers.py` to assert WARN, and rename it to match. This test currently encodes the bug.
- [X] T011 [P] [US1] Add a test to `TestBitForBit` in `tests/darnit_reproducibility/test_handlers.py` asserting the WARN message names `SOURCE_DATE_EPOCH` and says reproducibility was not verified (SC-001, FR-012).
- [X] T012 [P] [US1] Add a test to `TestBitForBit` in `tests/darnit_reproducibility/test_handlers.py` asserting `reprotest` and `diffoscope` each produce the same WARN treatment as `SOURCE_DATE_EPOCH`.
- [X] T013 [US1] In `tests/darnit_reproducibility/test_handlers.py`, confirm `TestBitForBit::test_date_macro_not_flagged` and `test_inconclusive_with_no_workflows` still pass unchanged.

**Checkpoint**: the framework's strongest claim is no longer granted on its thinnest evidence.

---

## Phase 4: User Story 2 - A floating base image is not a declared build environment (Priority: P1)

**Goal**: RE-01.02 reads container build files instead of trusting their filenames.

**Independent test**: two repos, `FROM alpine:latest` and `FROM alpine@sha256:...`. The first does not pass; the second does.

**Depends on**: nothing in Phases 2 or 3. Can run in parallel with US1.

- [X] T014 [US2] Create `packages/darnit-reproducibility/src/darnit_reproducibility/container_pinning.py` with the `PinKind` and `ContainerClassification` enums and a module docstring stating the boundary: text in, classification out, no file discovery and no `HandlerResult` (mirrors `requirements_pins.py` from feature 037).
- [X] T015 [US2] Implement `FROM`-line parsing in `container_pinning.py`. Collect `AS <name>` stage aliases across the whole file BEFORE classifying, so a later `FROM <name>` is recognized as a stage reference rather than an unpinned image. `packaging/container/Dockerfile` in this repo has exactly that shape and is the regression case (contract BE-4).
- [X] T016 [US2] Implement pin classification in `container_pinning.py`: `DIGEST` for `@sha256:<64 hex>`, `SCRATCH` for `FROM scratch`, `STAGE_REF` for a known stage alias, `TAG` for any tag including specific-looking ones, `INDETERMINATE` for a variable reference (FR-005, contract BE C-2).
- [X] T017 [US2] Implement `classify(text) -> ContainerClassification` in `packages/darnit-reproducibility/src/darnit_reproducibility/container_pinning.py` with the weakest-reference-governs rule, returning `NO_IMAGES` when no `FROM` lines are present (contract BE C-4).
- [X] T018 [US2] Split the `env_files` map in `repro_build_env_declared_handler` into inherently-pinned, content-dependent, and deferred classes per data-model.md, keeping the resolution order: inherently pinned first, then container files, then deferred, then INCONCLUSIVE (FR-007).
- [X] T019 [US2] Map `UNPINNED` to WARN at confidence 0.85 in `handlers.py`, with a message naming the offending image reference (FR-004, FR-006, FR-012).
- [X] T020 [US2] Update `TestBuildEnvDeclared::test_pass_with_dockerfile` in `test_handlers.py`. It writes `FROM python:3.11` -- a tag -- and asserts PASS. It must assert WARN (SC-002), and a sibling test must cover the digest-pinned PASS with output unchanged from today (SC-003).
- [X] T021 [P] [US2] Write `tests/darnit_reproducibility/test_container_pinning.py` covering every row of contract BE's obligations BE-1 through BE-7 as a pure-function table. BE-2 (`alpine:latest`), BE-3 (`python:3.12-slim-bookworm`), BE-5 (`scratch`) and BE-6 (`$BASE_IMAGE`) each need their own row rather than being covered by the range.
- [X] T022 [P] [US2] Add handler-level tests to `TestBuildEnvDeclared` in `tests/darnit_reproducibility/test_handlers.py` for BE-8 (inherently-pinned declarations byte-identical, SC-006), BE-9 (flake plus unpinned Dockerfile passes on the flake), BE-10 (`.devcontainer` and `Vagrantfile` unchanged in v0), BE-11 (Dockerfile with no `FROM` treated as absent).
- [X] T023 [US2] Add a test to `TestBuildEnvDeclared` in `tests/darnit_reproducibility/test_handlers.py` asserting `Containerfile` is handled identically to `Dockerfile`.

**Checkpoint**: the most common shape of the bug is fixed, and the RE-01.02 verdict that gates hermeticity is now earned.

---

## Phase 5: User Story 3 - Build-time dependency fetches are caught regardless of ecosystem (Priority: P2)

**Goal**: Go, Rust and Ruby installers are treated like the Python and Node ones already are.

**Independent test**: a workflow running `go install example.com/tool@latest` is reported as a live fetch.

**Depends on**: nothing. US3 appends to `_SUSPICIOUS_PATTERNS` and its matches use the existing violation message, so Phase 2 is not a prerequisite. It shares `handlers.py` with US4, so the two should not be edited concurrently.

- [X] T024 [US3] Add `go install `, `go get `, `cargo install `, and `gem install ` to `_SUSPICIOUS_PATTERNS` in `handlers.py` (FR-008).
- [X] T025 [US3] In `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py`, include the pinned version in the violation message when an installer reference carries one, so `go install pkg@v1.2.3` is distinguishable from `@latest` while both remain violations -- the control's subject is hermeticity, not determinism (FR-011, contract HS C-2).
- [X] T026 [P] [US3] Add tests to `TestHermeticBuild` in `test_handlers.py` for HS-1: each of the four installers produces a violation naming the command and file (SC-004, FR-012).
- [X] T027 [P] [US3] Add a test to `TestHermeticBuild` in `tests/darnit_reproducibility/test_handlers.py` for HS-2: `go install pkg@v1.2.3` is a violation whose message names the pinned version.
- [X] T028 [P] [US3] Add a test to `TestHermeticBuild` in `tests/darnit_reproducibility/test_handlers.py` asserting an installer inside a comment produces no finding, exercising the `_scan_line` comment strip rather than a parallel path (FR-015, HS-6).

**Checkpoint**: the hermeticity scan no longer has an ecosystem blind spot.

---

## Phase 6: User Story 4 - Non-deterministic compiler flags are surfaced (Priority: P2)

**Goal**: flags that make output depend on the build host are reported.

**Independent test**: a Makefile containing `-march=native` produces a finding naming the flag.

**Depends on**: Phase 2 for the `nondeterminism` kind and the message split.

- [X] T029 [US4] Add a `_NONDETERMINISTIC_FLAGS` tuple to `handlers.py` containing `-ffast-math`, `-march=native`, and `-mtune=native` (FR-009).
- [X] T030 [US4] Match those flags in `_scan_line` in `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py` and return the `nondeterminism` kind, keeping the comment strip and the `_SAFE_PATTERNS` precedence intact (contract HS C-4).
- [X] T031 [US4] Report the flag findings under their own message in `repro_hermetic_build_handler` in `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py`, naming the flag and the file it came from.
- [X] T032 [P] [US4] Add tests to `TestHermeticBuild` in `tests/darnit_reproducibility/test_handlers.py` for HS-3: each of the three flags produces a finding naming the flag and file, in both a Makefile and a workflow (SC-005, FR-012).
- [X] T033 [P] [US4] Add a test to `TestHermeticBuild` in `tests/darnit_reproducibility/test_handlers.py` for HS-4: the compiler-flag finding does not use the network-fetch message.
- [X] T034 [P] [US4] Add a test to `TestHermeticBuild` in `tests/darnit_reproducibility/test_handlers.py` for HS-5: `-O3` alone produces no finding. Record why in the test docstring -- at a fixed toolchain it is deterministic, and the non-determinism #432 describes comes from the unpinned toolchain (research.md R5).
- [X] T035 [P] [US4] Add a test to `TestHermeticBuild` in `tests/darnit_reproducibility/test_handlers.py` for HS-6: a flag inside a comment produces no finding.

**Checkpoint**: all four issues closed.

---

## Phase 7: The FR-010 Propagation

**Purpose**: the consequence that reaches repositories this feature does not otherwise touch. Separated from the stories because it is a cross-control effect rather than any one story's behavior.

- [X] T036 In `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py`, verify `_detect_strong_hermeticity_signal` still reads `dependency_results.get("RE-01.02") == "PASS"` unchanged. Nothing in the expression changes; only its input does (contract HS C-5).
- [X] T037 Make the withheld-signal case legible in `repro_hermetic_build_handler` in `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py`: when a `flake.nix` and a Nix CI invocation are present but RE-01.02 did not pass, the result must say the Nix signal was withheld because of RE-01.02, not leave the operator to infer the flake was missing (SC-010).
- [X] T038 Add a test to `TestDetectStrongSignal` in `tests/darnit_reproducibility/test_handlers.py` for HS-7: flake plus `nix build` plus `dependency_results={"RE-01.02": "PASS"}` still yields the Nix signal, unchanged.
- [X] T039 Add a test to `TestDetectStrongSignal` in `tests/darnit_reproducibility/test_handlers.py` for HS-8: flake plus `nix build` plus a WARNing RE-01.02 yields no Nix signal, and the message attributes the withholding to RE-01.02.
- [X] T040 Add an end-to-end test to `TestHermeticBuild` in `tests/darnit_reproducibility/test_handlers.py` building a repo with `flake.nix`, `nix build` in CI, and an unpinned `Dockerfile`, asserting RE-01.02 does not pass and RE-02.01 loses the signal (SC-010).

---

## Phase 8: Polish and Cross-Cutting Concerns

- [X] T041 Write `tests/darnit_reproducibility/test_repro_corpus.py` with a hand-written expected-verdict table over the feature's fixtures, run with `verify_witness_attestations: false`. Write the table by hand rather than capturing it -- this feature's claim is "these specific things changed", which a reviewer should be able to read and disagree with (research.md R8, SC-007).
- [X] T042 Assert in `tests/darnit_reproducibility/test_repro_corpus.py` that no control other than RE-01.02, RE-02.01 and RE-03.01 appears with a changed verdict (FR-013).
- [X] T043 Confirm SC-009: every edge case in spec.md has a fixture and an asserted verdict, including `FROM scratch`, `FROM $BASE_IMAGE`, the multi-stage case, and the pinned-version installer.
- [X] T044 [P] Update the `repro_build_env_declared_handler` docstring in `handlers.py` -- it currently says "Looks for Dockerfile, Nix flake, devcontainer, or similar. PASS if found", which this feature makes wrong.
- [X] T045 [P] Update the `repro_bit_for_bit_handler` docstring in `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py`, which currently describes the signals as "the most reliable signals without actually running the build twice" and returns PASS on them.
- [X] T046 Run `uv run darnit audit --framework reproducibility .` against this repository and confirm RE-01.02 returns WARN naming `python:3.12-slim-bookworm`, and that the multi-stage `FROM builder` is not reported (quickstart.md).
- [X] T047 Re-run the nine dogfood repositories (`uv run darnit audit --framework reproducibility <repo>`) from the #445/#446 investigation and confirm every verdict change is explained by one of FR-001 through FR-009 (SC-008).
- [X] T048 File a follow-up issue for `repro_provenance_exists` (`packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py`), which has the same presence-based shape as #445 and is covered by none of the four issues.
- [X] T049 Verify FR-014 by checking the imports of `packages/darnit-reproducibility/src/darnit_reproducibility/` against its declared dependencies. The new work is stdlib string and path handling, so this should be a confirmation rather than a fix.
- [X] T050 Run the full gate: `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ --ignore=tests/darnit/parity/tier2 -q`, `uv run python scripts/validate_sync.py --verbose`.
- [X] T051 Run `uv run ruff format` on touched files only. A repository-wide format run reformats hundreds of unrelated files.

---

## Dependencies

```text
Phase 1 (T001-T002)
    |
    +-- Phase 3 / US1 (T007-T013)   ---> shippable on its own
    |
    +-- Phase 4 / US2 (T014-T023)   <- independent of US1, may run alongside
    +-- Phase 5 / US3 (T024-T028)   <- independent of Phase 2
    |
    +-- Phase 2 (T003-T006)
             |
             `-- Phase 6 / US4 (T029-T035)
                      |
                 Phase 7 (T036-T040)   <- needs US2's verdict change
                      |
                 Phase 8 (T041-T051)
```

US1, US2 and US3 are independent of each other and of Phase 2. Only US4 needs Phase 2's reporting split. Phase 7 needs US2, because the propagation it tests is caused by US2's verdict change.

## Parallel Opportunities

- **US1 and US2 together.** US1 touches `repro_bit_for_bit_handler`; US2 touches `repro_build_env_declared_handler` and a new module. Different functions, no contention beyond the shared file.
- **US3 and US4 after Phase 2.** Both extend the scan, but T024-T025 touch the pattern tuple and message while T029-T031 touch a different tuple and a different message bucket.
- **Test authoring.** T021, T026, T027, T032 through T035 are independent.
- **Not parallel**: T014 through T017 all edit `container_pinning.py`; T018, T019, T024, T025, T029, T030, T031, T037 all edit `handlers.py`; T010, T020, T022, T026 and most test tasks edit `test_handlers.py`.

## Implementation Strategy

**MVP = Phases 1 and 3.** US1 alone closes #445, the worst of the four, with one verdict change in one handler, no new module, and no cross-control effect. If the digest-pinning rule in US2 needs more argument than the fix deserves, this is a clean place to stop.

**US2 is the one to review carefully.** It changes a verdict that gates another control, and its rule -- that only a digest pins -- will fail this repository's own Dockerfile. That is intended, and T046 makes it the thing you see rather than something a user reports.

**Phase 7 is not optional.** The propagation happens whether or not it is tested, and SC-010 exists so it is visible in the output rather than discovered by someone whose PASS vanished.

**Blocked end to end until PR #443 merges.** FR-001 and FR-004 need feature 037's conclusive WARN. Unit work is unaffected; this branch already contains 037's commits.

---

## Implementation Notes

Recorded during `/speckit-implement`.

- **Both predicted test breakages happened, and nothing else broke.** `TestBuildEnvDeclared::test_pass_with_dockerfile` and `TestBitForBit::test_pass_with_source_date_epoch` failed exactly as T009 and T019 said they would; the other 101 tests in the file passed untouched. Naming them as tasks rather than discovering them was the right call.
- **T006 (HS-9) earned its place immediately.** Writing it, I used `--spawn_strategy=sandboxed` as the Bazel blocking flag from memory; the real one is `--sandbox_default_allow_network=false`. The test failed, the code was right. A second attempt also failed because a `.bazelrc` alone is not in the discoverable file set, so the handler returns "No CI or build files found" before reaching the signal check -- a pre-existing quirk, not something this feature introduced, and not fixed here.
- **BE-11 was a real defect in the first implementation.** A `Dockerfile` with no `FROM` lines returned PASS because it was counted as inspected. Corrected to fall through as if absent.
- **T045 disproved a claim I made in quickstart.md.** darnit does NOT fail its own RE-01.02 check: it has a root `.python-version`, which is inherently pinned and checked before any container file, so its `Dockerfile` is never inspected. The quickstart has been corrected to show what actually happens and why. The Dockerfile in isolation does WARN, naming `python:3.12-slim-bookworm` twice and correctly never mentioning the `builder` stage.
- **That exposes a consequence of contract BE C-6 worth revisiting.** "A stronger declaration wins" means any Python project with a `.python-version` never has its container file inspected, however floating its base image. Implemented as specified, since C-6 and BE-9 both require it, but it narrows #431's reach for exactly the ecosystem darnit is written in. Worth its own issue or a spec amendment rather than a silent change here.
- **T046 found three verdict changes across the nine dogfood repositories, each explained by a requirement.** cosign RE-01.02 PASS -> WARN (`golang:1.27.1`, FR-004/FR-005); scorecard RE-02.01 WARN -> FAIL (`go install`, FR-008, with FR-011's pin naming working on a real commit SHA); requests RE-03.01 PASS -> WARN (FR-001, the case #445 was filed about). SC-008 satisfied.
- **The follow-up issue task filed #453** for `repro_provenance_exists`. Same shape as #445: a dispositive PASS at confidence 0.9 when any of six provenance-related strings appears in CI text, with no attestation fetched or verified.
