# Feature Specification: Honest Verdicts for Reproducibility Controls

**Feature Branch**: `038-repro-false-pass`

**Created**: 2026-09-20

**Status**: Draft

**Input**: Issues #445, #431, #430, #432 -- four reproducibility controls that report a repository as better than the evidence supports.

## Context

Four issues were filed as one family: "controls that pass on artifact presence rather than artifact quality." Reading the code before writing this spec showed that framing is right for two of them and wrong for the other two. The distinction matters because the fixes have different shapes and different blast radii.

### Shape A -- the verdict is stronger than the evidence

- **#445, `repro_bit_for_bit`** (RE-03.01, "Build output is identical across independent builds") returns a dispositive PASS when the string `SOURCE_DATE_EPOCH`, `reprotest`, or `diffoscope` appears anywhere in any workflow file. Observed on `psf/requests`: one occurrence in `publish.yml` produces PASS at confidence 0.8. Nothing is built; nothing is compared.
- **#431, `repro_build_env_declared`** (RE-01.02) returns PASS at confidence 0.85 when any of eight filenames exists. A `Dockerfile` whose only content is `FROM alpine:latest` satisfies it. A floating tag is the opposite of a declared environment: it resolves differently on every build.

### Shape B -- the detection misses violations

`repro_hermetic_build` (RE-02.01) is already careful about its PASS. It requires a *verified* Witness attestation showing no network activity, a Nix flake build, or Bazel with a blocking flag, and its docstring explicitly rejects "merely mentioning `witness run` in CI text." The problem is not the strength of its PASS but the coverage of its violation scan:

- **#430**: `_SUSPICIOUS_PATTERNS` contains seven entries (`curl `, `wget `, `pip install `, `npm install`, `yarn install`, `apt-get install`, `brew install`). `go install`, `go get`, `cargo install`, and `gem install` are absent. A Go or Rust build that fetches dependencies at build time scans clean.
- **#432**: there is no compiler-flag detection at all. `-ffast-math`, `-march=native`, and `-O3` with an unpinned toolchain each make output non-deterministic, and none is looked for.

### The coupling between them

`_detect_strong_hermeticity_signal` gates its Nix path on `dependency_results.get("RE-01.02") == "PASS"`. RE-01.02 is the control #431 is about. So the weak PASS in Shape A feeds a strong signal in Shape B: a repository with a bare `flake.nix`, a `FROM alpine:latest` Dockerfile, and `nix build` in CI currently earns a hermeticity PASS that rests on a build-environment PASS that rests on a filename.

Tightening #431 therefore changes RE-02.01 verdicts for repositories this feature does not otherwise touch. That is a consequence to decide deliberately, not to discover after merging.

### Why now

Principle II forbids false positives specifically: "It is always better to report a false negative than a false positive." All four issues produce over-optimistic verdicts, which is the forbidden direction.

Until recently there was no way to express the honest answer. A handler could return PASS, FAIL, INCONCLUSIVE or ERROR, and "we found a real signal but did not verify the property" is none of those -- INCONCLUSIVE sends the pipeline onward to a generic "Could not automatically verify" WARN that discards what the handler learned. Feature 037 added a conclusive WARN carrying the handler's own message, which makes the honest verdict sayable for the first time.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Bit-for-bit reproducibility is not claimed without being verified (Priority: P1)

A maintainer whose CI sets `SOURCE_DATE_EPOCH` runs an audit. They are told the signal was found and that bit-for-bit reproducibility has not been verified, rather than being told their build is reproducible.

**Why this priority**: this is the framework's strongest claim granted on its thinnest evidence. A maintainer who trusts it may ship believing a property they have never tested.

**Independent Test**: a repo whose only reproducibility evidence is `SOURCE_DATE_EPOCH` in one workflow. The control does not return PASS, and the message names both the signal found and what remains unverified.

**Acceptance Scenarios**:

1. **Given** a repo with `SOURCE_DATE_EPOCH` in a workflow and no verification tooling, **When** the audit runs, **Then** RE-03.01 returns WARN, not PASS.
2. **Given** the same repo, **When** the audit runs, **Then** the message states the signal that was found and that reproducibility was not verified, so the operator can tell the difference between "no evidence" and "promising evidence, unverified."
3. **Given** a repo with no reproducibility signals at all, **When** the audit runs, **Then** the result is unchanged from today.

---

### User Story 2 - A floating base image is not a declared build environment (Priority: P1)

A maintainer whose `Dockerfile` reads `FROM alpine:latest` is told their build environment is declared but not pinned, instead of being told it is declared.

**Why this priority**: it is the most common shape of the bug -- unpinned base images are everywhere -- and it is the one that propagates, because RE-01.02's verdict gates the hermeticity signal.

**Independent Test**: two repos, one `FROM alpine:latest` and one `FROM alpine@sha256:...`. The pinned one passes; the floating one does not.

**Acceptance Scenarios**:

1. **Given** a repo whose `Dockerfile` uses a floating tag (`latest`, or any bare tag), **When** the audit runs, **Then** RE-01.02 does not return PASS, and the message names the offending image reference.
2. **Given** a repo whose `Dockerfile` pins by digest, **When** the audit runs, **Then** RE-01.02 returns PASS as it does today.
3. **Given** a repo with a `flake.nix`, `.tool-versions`, or another declaration that is inherently pinned, **When** the audit runs, **Then** RE-01.02 returns PASS unchanged.

---

### User Story 3 - Build-time dependency fetches are caught regardless of ecosystem (Priority: P2)

A maintainer of a Go or Rust project whose CI runs `go install` or `cargo install` during the build is told their build fetches dependencies at build time, the same as a Python project running `pip install`.

**Why this priority**: a correctness gap rather than a wrong claim, and it under-reports rather than over-claiming. Still a defect, and cheap to close.

**Independent Test**: a repo whose workflow runs `go install example.com/tool@latest`. RE-02.01 reports it as a live fetch.

**Acceptance Scenarios**:

1. **Given** a workflow containing `go install`, `go get`, `cargo install`, or `gem install`, **When** the audit runs, **Then** RE-02.01 reports a live-fetch violation naming the command and file.
2. **Given** a workflow containing a lock-file-pinned equivalent, **When** the audit runs, **Then** it is not reported as a violation.

---

### User Story 4 - Non-deterministic compiler flags are surfaced (Priority: P2)

A maintainer whose build passes `-ffast-math` or `-march=native` is told those flags make output non-deterministic.

**Why this priority**: real and well-defined, but narrower in reach than the other three, and it is new detection rather than a correction to an existing claim.

**Independent Test**: a Makefile or workflow with `-march=native`. RE-02.01 names the flag.

**Acceptance Scenarios**:

1. **Given** a build file containing `-ffast-math`, `-march=native`, or `-mtune=native`, **When** the audit runs, **Then** the result names the flag and the file.
2. **Given** a build file with none of these, **When** the audit runs, **Then** the result is unchanged from today.

---

### Edge Cases

- **A multi-stage Dockerfile with a mix of pinned and floating `FROM` lines**: the weakest stage governs, consistent with how feature 037 treats requirement lines.
- **A Dockerfile pinned to a tag but not a digest** (`FROM alpine:3.19`): more pinned than `latest`, less pinned than a digest. A tag is mutable, so it does not pin.
- **`SOURCE_DATE_EPOCH` plus a verified reproducibility check** (a workflow that builds twice and diffs): the signal is corroborated by actual verification. This is the case that should still PASS, and the one that distinguishes a signal scan from a verification.
- **`go install` of a tool pinned to a version** (`go install example.com/tool@v1.2.3`): fetches at build time but deterministically. Distinct from `@latest`.
- **A repository with no CI at all**: unchanged -- no files to scan, no verdict to change.
- **Compiler flags inside a comment or documentation**: a flag mentioned in a README is not a flag used in a build.
- **The RE-01.02 gate on the Nix path**: repositories that currently earn a hermeticity PASS through the Nix signal lose it when their RE-01.02 verdict changes. Resolved: the gate stands (FR-010), and the propagation is an accepted, documented consequence.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: RE-03.01 MUST NOT return PASS on the basis of a reproducibility signal appearing in a file. Signals found without verification MUST produce WARN carrying the handler's own message.
- **FR-002**: The RE-03.01 message MUST name both the signal found and the fact that reproducibility was not verified, so "promising but unverified" is distinguishable from "no evidence."
- **FR-003**: RE-03.01 MUST continue to return its existing verdict when no signals are found.
- **FR-004**: RE-01.02 MUST inspect the contents of a container build file rather than only its filename, and MUST NOT return PASS when the environment it declares is itself unpinned.
- **FR-005**: An image reference pinned by digest MUST count as pinned. A reference by mutable tag, including `latest` and any bare version tag, MUST NOT.
- **FR-006**: The RE-01.02 message MUST name the offending image reference when the declaration is unpinned.
- **FR-007**: Declarations that are inherently pinned (`flake.nix`, `.tool-versions`, `.python-version`, `.nvmrc`) MUST keep their current verdict. This feature inspects container build files only.
- **FR-008**: RE-02.01's violation scan MUST recognize language-level package installers that fetch at build time: `go install`, `go get`, `cargo install`, and `gem install`.
- **FR-009**: RE-02.01's violation scan MUST recognize compiler flags that make output non-deterministic, at minimum `-ffast-math`, `-march=native`, and `-mtune=native`, and MUST name the flag and the file.
- **FR-010**: The Nix strong-hermeticity signal MUST continue to require RE-01.02 to have PASSED. The tightening in FR-004 therefore propagates: a repository with a `flake.nix`, `nix build` in CI, and an unpinned container declaration loses its RE-02.01 PASS without its flake having changed.

  This is deliberate rather than incidental. The gate exists because "a bare flake.nix that isn't the project's confirmed, declared build environment isn't a strong signal on its own." Once RE-01.02 stops confirming that the environment is declared, the gate's premise is gone, and preserving the PASS would keep a verdict whose justification no longer holds.

  The cost MUST be stated wherever this change is described to users: some repositories will see RE-02.01 move from PASS to INCONCLUSIVE having changed nothing themselves. The propagation MUST be visible in the result -- a reader of the RE-02.01 output must be able to tell that the Nix signal was withheld because of RE-01.02, rather than because the flake was not found.
- **FR-011**: A version-pinned `go install example.com/tool@v1.2.3` MUST be distinguishable from `@latest` in the result message, whether or not both are treated as violations.
- **FR-012**: Every verdict changed by this feature MUST state what was examined and what was concluded, not merely a status. This applies to all four changed messages: the RE-03.01 signal WARN, the RE-01.02 unpinned WARN, the RE-02.01 installer violation, and the RE-02.01 compiler-flag finding.
- **FR-013**: No control outside RE-01.02, RE-02.01, and RE-03.01 may change its verdict as a result of this feature.
- **FR-014**: The feature MUST NOT introduce a new runtime dependency.
- **FR-015**: Detection MUST NOT treat a flag or command appearing in prose or a comment as a build-time occurrence.

### Key Entities

- **Reproducibility signal**: an indicator that reproducibility was considered (`SOURCE_DATE_EPOCH`, `reprotest`, `diffoscope`). Evidence of intent, not of achievement.
- **Environment declaration**: a file that states what the build runs on. Either inherently pinned (a flake, a version file) or pinned only if its contents pin it (a container build file).
- **Image reference**: a base image in a container build file, pinned by digest or floating by tag.
- **Build-time fetch**: a command in a CI or build file that retrieves code or artifacts while the build runs.

## Success Criteria *(mandatory)*

- **SC-001**: A repository whose only reproducibility evidence is `SOURCE_DATE_EPOCH` in a workflow no longer receives PASS on RE-03.01. Verified against a fixture reproducing the `psf/requests` case from #445.
- **SC-002**: A repository whose `Dockerfile` reads `FROM alpine:latest` no longer receives PASS on RE-01.02, and the message names the image. Verified by fixture.
- **SC-003**: A repository whose `Dockerfile` pins by digest still receives PASS on RE-01.02, with output identical to today. Verified by fixture.
- **SC-004**: A workflow running `go install` or `cargo install` produces a violation on RE-02.01 naming the command. Verified by fixture.
- **SC-005**: A build file containing `-ffast-math` or `-march=native` produces a result naming the flag. Verified by fixture.
- **SC-006**: Repositories declaring their environment through `flake.nix`, `.tool-versions`, `.python-version`, or `.nvmrc` produce byte-identical RE-01.02 output before and after this change.
- **SC-007**: No control other than RE-01.02, RE-02.01, and RE-03.01 changes status across the change, verified by the same differential capture feature 037 introduced.
- **SC-008**: Each of the nine repositories used to find these issues is audited before and after, and every verdict change is explained by one of FR-001 through FR-009.
- **SC-009**: Every edge case enumerated above has a fixture and an asserted verdict.
- **SC-010**: A fixture combining a `flake.nix`, `nix build` in CI, and an unpinned `Dockerfile` demonstrates the FR-010 propagation: RE-01.02 does not PASS, RE-02.01 loses the Nix signal, and the RE-02.01 message attributes the withheld signal to RE-01.02 rather than to a missing flake.

## Assumptions

- Digest pinning is the only form of container image pinning that counts. A tag, however specific, is mutable.
- RE-03.01's signal scan is worth keeping. The signals are real evidence about intent; the defect is the verdict drawn from them, not the detection.
- Actually verifying bit-for-bit reproducibility means building twice and comparing, which belongs to #416 rather than here.
- `repro_hermetic_build`'s existing PASS conditions (verified Witness attestation, Bazel with a blocking flag) are sound and are not revisited.
- The Nix gate's dependency on RE-01.02 is treated as correct and is preserved (FR-010). The alternative -- judging a flake on its own merits regardless of the container declaration -- was considered and rejected: it would keep a PASS resting on a premise the same change removes.
- The four issues were filed as one family. Two are verdict-strength corrections and two are detection-coverage additions; they are specified together because they share a file, a principle, and a test corpus, not because they share a fix.

## Dependencies

- **PR #443 (feature 037)** -- FR-001 and FR-004 depend on the conclusive handler-level WARN it introduces. Without it the honest verdict cannot carry its own message, and the alternatives are a misleading PASS or a generic fallthrough.
- **#416** (heuristic checks for execution and build reproducibility) would supply real verification for RE-03.01. This feature makes the claim honest in its absence; it does not substitute for it.
- **#442** (cross-framework control leakage) affects the differential capture used by SC-007, which already works around it with subprocess isolation.

## Out of Scope

- **Actually verifying reproducibility** by building twice and comparing. That is #416.
- **#433** (native C/C++ toolchain support) and **#446** (pyproject.toml and conda manifests). Both are detection-coverage work in the same file, deferred to keep this change reviewable.
- **Remediation** for any of the new findings. Telling a maintainer to pin their base image is a separate action from detecting that it floats.
- **Revisiting confidence values.** Each control keeps the confidence it already uses: 0.85 for RE-01.02, 0.8 for RE-03.01. Feature 037 established that moving to content inspection does not by itself justify changing a confidence, and this feature follows that reasoning rather than 037's specific number -- which belonged to a different control. Using 0.8 for RE-01.02 would break SC-003 and SC-006, both of which require byte-identical output for declarations that still pass.
- **The `repro_provenance_exists` handler.** It has the same presence-based shape and is not covered by any of the four issues. Worth its own look; not smuggled in here.
