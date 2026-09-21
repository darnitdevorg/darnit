# Phase 0 Research: Honest Verdicts for Reproducibility Controls

**Feature**: 038 | **Date**: 2026-09-20

Every decision below was checked against the code rather than assumed. References are to `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py` unless stated.

---

## R1: How RE-03.01 says "signal found, not verified" (#445)

**Decision**: return the conclusive WARN added by feature 037, with a message naming both the signal and the gap.

**Rationale**: the handler's existing structure is already right -- it scans workflows for `SOURCE_DATE_EPOCH`, `reprotest`, `diffoscope` and records them in evidence. Only the verdict is wrong. Returning WARN keeps the finding and drops the unearned claim.

`repro_bit_for_bit` is registered `default_authority="dispositive"`, so the WARN concludes rather than falling through to the generic "Could not automatically verify" string. Before feature 037 that was not possible, which is why the handler had only PASS and INCONCLUSIVE to choose between.

**Alternatives considered**:
- *INCONCLUSIVE instead of WARN*: sends the pipeline to `manual`, whose message discards the signal the handler found. The operator then cannot distinguish "no evidence" from "promising evidence, unverified" -- exactly the distinction FR-002 requires.
- *Keep PASS at lower confidence*: confidence is not a hedge on the claim. A PASS at 0.5 still counts as compliant in the arithmetic.

---

## R2: How RE-01.02 distinguishes pinned from unpinned declarations (#431)

**Decision**: split the existing `env_files` map into two classes.

| Class | Files | Treatment |
|---|---|---|
| Inherently pinned | `flake.nix`, `shell.nix`, `.tool-versions`, `.nvmrc`, `.python-version` | PASS on presence, unchanged (FR-007, SC-006) |
| Content-dependent | `Dockerfile`, `Containerfile`, `.devcontainer`, `Vagrantfile` | inspect contents |

**Rationale**: the two classes differ in kind. A `flake.nix` pins by construction -- that is what a flake lock is for. A `Dockerfile` pins only if its `FROM` lines do. Treating them alike is the actual bug in #431, not the absence of parsing.

`.devcontainer` and `Vagrantfile` are content-dependent in principle. In practice `.devcontainer` usually delegates to a Dockerfile or an image reference, and `Vagrantfile` names a box with an optional version. **Decision: v0 inspects `Dockerfile` and `Containerfile` only.** A repository whose only declaration is `.devcontainer` or `Vagrantfile` keeps today's PASS. Widening is detection work of the same shape as #433/#446 and is recorded in Out of Scope rather than smuggled in.

**Alternatives considered**: inspecting every content-dependent file in one pass. Rejected on review size -- three more formats, three more edge-case tables, one PR.

---

## R3: What counts as a pinned image reference (FR-005)

**Decision**: pinned if and only if the reference carries an image digest (`@sha256:<64 hex>`). Every tag is unpinned, including specific-looking ones.

**Verified forms that must not be misread**:

| `FROM` line | Classification | Why |
|---|---|---|
| `FROM alpine@sha256:<64 hex>` | pinned | immutable content address |
| `FROM alpine:latest` | unpinned | mutable |
| `FROM python:3.12-slim-bookworm` | unpinned | a tag, rebuilt regularly |
| `FROM builder` | **not an image** | stage reference in a multi-stage build |
| `FROM scratch` | pinned | the empty image; nothing to resolve |
| `FROM $BASE_IMAGE` | indeterminate | an ARG; cannot be resolved statically |

The stage-reference case is the one a naive scan gets wrong. `packaging/container/Dockerfile` in this repository has exactly that shape -- `FROM python:3.12-slim-bookworm AS builder` followed by a second `FROM`. Any stage name introduced by a prior `AS` clause must be collected first and excluded from classification, or every multi-stage build reports a spurious unpinned reference.

`FROM $BASE_IMAGE` is treated as unpinned: the tool cannot see what it resolves to, and Principle II resolves doubt against the claim.

**Weakest stage governs**, consistent with how feature 037 treats requirement lines.

---

## R4: Where installer patterns go (#430)

**Decision**: add `go install `, `go get `, `cargo install `, `gem install ` to `_SUSPICIOUS_PATTERNS`.

**Rationale**: `_scan_line` already does the work -- strips comments, checks `_SAFE_PATTERNS` first, defers Dockerfile system-package installs, then matches suspicious patterns. These four are the same kind of thing as the seven already there. No new mechanism.

**On version-pinned installs (FR-011)**: `go install example.com/tool@v1.2.3` fetches at build time just as `@latest` does. The control is `HermeticBuild` -- "Build does not fetch dependencies at build time" -- so both are violations. What differs is diagnosis, so the **message** names the pinned version when one is present, and the result does not pretend they are equally bad. A pinned fetch is a smaller problem than a floating one, and the operator should be able to see which they have.

**Alternatives considered**: treating `@v1.2.3` as `_SAFE_PATTERNS`. Rejected -- it would mean the control silently redefines hermetic as "deterministic", which is a different property and not the one RE-02.01 claims.

---

## R5: Compiler flags need their own category, not `_SUSPICIOUS_PATTERNS` (#432)

**Decision**: add a separate `_NONDETERMINISTIC_FLAGS` tuple and a distinct violation kind, so the two findings carry different messages.

**Rationale**: the existing violation message is `"Possible live network fetches in build files: ..."` (line 674). Putting `-march=native` into `_SUSPICIOUS_PATTERNS` would report a compiler flag as a network fetch. That is a wrong statement to an operator, and the kind of thing that makes people stop trusting the output.

`_ScanKind` is already `Literal["safe", "deferred", "violation"]`, so the change is a fourth member plus a second violation bucket in the handler. The scan structure is reused; only the reporting splits.

**Initial flag set**: `-ffast-math`, `-march=native`, `-mtune=native`. Each makes output depend on the build host's CPU or on reassociated floating-point arithmetic.

**Deliberately excluded**: `-O3`. It is not itself non-deterministic -- the same compiler at `-O3` produces the same output. #432 mentions it alongside an unpinned toolchain, but the non-determinism there comes from the toolchain, not the flag, and flagging `-O3` would fire on a large share of legitimate builds for no defensible reason.

---

## R6: Keeping comments and prose out of the results (FR-015)

**Decision**: route all new detection through `_scan_line`, which calls `_strip_comment` before matching.

**Rationale**: the guard exists and works. The failure mode to avoid is adding a second scanning path that skips it -- which is how the `-march=native` in a Makefile comment would end up in a result.

The scanned file set is already bounded and relevant: workflows, composite actions, Makefiles and build scripts, Dockerfiles, other CI files. Documentation is not scanned, so prose is out of reach by construction rather than by filtering.

---

## R7: Verifying SC-007 without pinning the environment

**Decision**: capture a reproducibility-only corpus with witness verification disabled, and assert the expectation table.

`_maybe_check_witness_attestation` honors `config.get("verify_witness_attestations", True)` (line 468), so passing `verify_witness_attestations: false` removes the only network call in the plugin. With that off, reproducibility verdicts over fixed fixtures are pure filesystem functions and are identical on a laptop and on a runner.

**Rationale**: feature 037 tried a committed golden of control statuses and it failed in CI while passing locally -- seven OSPS controls resolve differently depending on whether `gh` is authenticated. That lesson applies to any corpus containing network-dependent controls. Restricting this corpus to `reproducibility` with witness checking disabled removes the cause rather than working around it.

Controls outside this plugin cannot be affected: no shared code changes, and `openssf-baseline` does not import `darnit_reproducibility`. SC-007 is therefore satisfied by the reproducibility corpus plus that structural fact, and does not need the cross-framework capture from feature 037.

---

## R8: Establishing the before/after comparison

**Decision**: assert an explicit expected-verdict table checked into the test, not a captured golden.

**Rationale**: the corpus is small -- five controls across a handful of fixtures -- and every verdict in it is a deliberate claim of this feature. Writing the table by hand means a reviewer can read it and disagree; generating it means the test asserts whatever the code happened to do. Feature 037 needed a captured baseline because its claim was "nothing changed" across 213 controls. This feature's claim is "these specific things changed", which is better expressed as an expectation than as a diff.

The FR-010 propagation case (SC-010) is one row in that table, and it is the row most worth reading.
