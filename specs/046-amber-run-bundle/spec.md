# Feature Specification: Amber Runs

**Feature Branch**: `amber-run-bundle` (PR #678) · **Created**: 2026-11-04 · **Revised**: 2026-11-25 · **Status**: Draft

**Input**: darnit issue #677.

## Background

A reviewer of a paper's experiment wants to know what was run, what came out, and whether running it again gives the same result.

- `darnit-amber run -- <command>` runs the command under Witness, in a fresh clone of the commit, and stores a signed record of it in `.amber/`.
- `darnit-amber verify` checks that a record was not changed and who signed it.
- `darnit-amber rerun` verifies a record, rebuilds the environment it ran in, runs the command again, and compares the results.
- `darnit audit -f amber` reports whether the audited commit has a verified run by a trusted signer (RE-02.03).

## Clarifications

### Session 2026-11-04

- Q: What does the researcher sign? -> A: The statement itself. The Witness envelopes attest the steps; the predicate (claims, verdict, audit results, environment, signer) is derived by darnit and was unsigned. The statement is now signed as a DSSE envelope by the same signer, with the same timestamp authority, and `verify` requires the signed payload to be byte-identical to the statement the id hashes (FR-001).
- Q: Where is a claim measured from? -> A: Only from bytes the experiment produced, as Witness hashed them. A file in the checkout that Witness did not record as a product is not an output, whatever it contains (FR-004).
- Q: What does `verify` establish about the signer? -> A: That the key the verifier named (`--pubkey`) is the key the statement names and the one every signature verifies with. A signature nobody checked never counts as verified, as `cosign verify` behaves (FR-008). Who holds the key (a Sigstore identity) and whether the bundle is in a public log are follow-up PRs on this one.
- Q: Does a failed experiment get a bundle? -> A: Yes. Witness writes no attestation for a command that exits non-zero, so the command runs in a wrapper that records its exit status and exits 0; the recorded status is in the signed statement, and `verify` recomputes the wrapper from the recorded command (FR-012).
- Q: What of the host does the bundle record? -> A: An allowlist of variables that decide how code runs. Witness's environment attestor is not used: it records the host name, the user name and every variable a blocklist does not know (FR-010).
- Q: Does `rerun` run anything from an unverified bundle? -> A: No. It verifies first, shows the command, and runs it only with consent, because until the container step lands the command runs on the host as the user (FR-014).

### Session 2026-11-11

- Q: Who signs a derived bundle, and how does a verifier name two signers? -> A: The run's signer stands behind the Witness envelopes and the statement of an original bundle; the claimer stands behind the statement of a bundle `claim` derived. `verify` takes a key for each: `--pubkey` for the run's signer, `--claimer-pubkey` for the claimer, falling back to the run's expectation when none is given (the researcher claiming their own run). Each claim records `signed_by` (FR-018).
- Q: What does a bundle record of where the researcher works? -> A: Nothing. Path variables in the allowlist are rewritten relative to the checkout (`$CHECKOUT/...`) or the home directory (`$HOME/...`); a local artifact without a remote is named `local/<directory name>`, so `rerun` of such a bundle needs `--artifact` (FR-010).
- Q: Which files can the experiment read? -> A: Only what the commit contains. Untracked files make a checkout dirty; a clean checkout, and any run at a named commit, is executed from a fresh clone, where files git ignores do not exist (FR-011).
- Q: Which parts of the predicate did Witness see? -> A: The predicate says so itself, under `provenance`: `observed` lists exactly what `verify` checks against a Witness envelope (the audit's command, exit code, report and results; the experiment's command, exit status, outputs and products; the envelope digests); `self_reported` lists what darnit-amber wrote down on its own (`started_at`, `environment`, which also carries `recorded_by`, `signing`, `entry`, `claims`, `verdict`) (FR-019).
- Q: How can the exit status and the audit report be Witness-observed when Witness refuses a failing command? -> A: Both are written inside the checkout, under `.amber/`, where Witness's product attestor hashes them; darnit stores both as blobs and `verify` reads them back against those digests and recomputes `exit_code` and `audit.results` from them. `.amber/` is removed after each step, so nothing is left in the checkout, in-place `--allow-dirty` runs included (FR-012).

### Session 2026-11-25

This session revises the design; "Requirements" below is the current design. Still hold: on 2026-11-04, only a verified run is rerun; on 2026-11-11, the command reads only what the commit contains. Everything else above is superseded: claims are removed, the audit no longer runs inside `run`, and signing and the environment work as below.

- Q: Who signs? -> A: The researcher's Sigstore identity, after the experiment (keyless). Most researchers will not manage a key pair. `--key` signs with a key instead.
- Q: How is the environment recorded? -> A: On Linux, Witness traces every file the command opens. Those become a lock: package versions (dpkg, Python, pip), and files no package accounts for, by digest.
- Q: Where does a rerun run? -> A: In an image built from the lock, or with `--host-environment` on this machine. It runs under Witness too; `--sign` records it as a signed run of its own.
- Q: Is a failing run recorded? -> A: Only with `--record-failure`. A failure is usually a mistake (a wrong path), not a result worth signing.
- Q: Does a rerun ask before running? -> A: Only with `--host-environment`, where it runs on this machine as the user.
- Q: Can a model fill in files no package accounts for? -> A: Planned, not built (`resolve.py` is a stub).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record and verify a run (Priority: P1)

A researcher runs `darnit-amber run --results results/ -- python train.py` and signs in to Sigstore. A reviewer runs `darnit-amber verify --identity <researcher> --issuer <issuer>`.

**Acceptance**: verify passes; after any change to the record, or with another signer named, it fails.

### User Story 2 - Rerun a run (Priority: P2)

The reviewer runs `darnit-amber rerun`.

**Acceptance**: the rerun runs only after the run verifies and the reviewer agrees, and reports whether the results changed and whether the environment differed.

### User Story 3 - Audit a commit (Priority: P3)

An operator who trusts the researcher's identity runs `darnit audit -f amber`.

**Acceptance**: RE-02.03 passes for a verified run of the audited commit that exited 0.

### Edge Cases

- A failing experiment is not recorded unless `--record-failure`; then it is, with its exit code.
- A checkout with uncommitted changes or untracked files is refused.
- A run with no lock (not Linux, or `--no-trace`) can only be rerun with `--host-environment`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `run` MUST record the repository and commit, the command, its exit code, the digests and copies of the `--results` files, and the environment lock, and MUST NOT record credentials in URLs.
- **FR-002**: `verify` MUST pass only when the record agrees with Witness's attestation, the stored copies match their digests, and the signature verifies for the signer the verifier names (without one, the signer the run names, with a warning).
- **FR-003**: `rerun` MUST NOT run anything from a run that does not verify, nor run on this machine without consent.
- **FR-004**: RE-02.03 MUST fail if a run of the audited commit does not verify, MUST pass only for a verified run that exited 0 by a trusted key or identity, and is inconclusive otherwise.

### Key Entities

- **Run**: the signed statement, Witness's attestation, and copies of the results, in `.amber/runs/<id>/`; the id is the statement's sha256.
- **Environment lock**: package versions (dpkg, Python, pip) and, for files no package accounts for, their digests.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A changed record never verifies (`tests/darnit_amber/test_amber_runs.py`).
- **SC-002**: A rerun of an unchanged experiment reports identical results (`test_amber_runs.py`).
- **SC-003**: A lock renders to a Dockerfile that installs the locked versions (`test_envlock.py`).

## Assumptions

- Witness is on `PATH`; tracing works only on Linux; rerunning in an image needs Docker or Podman.
- Out of scope: paper claims; filling in unresolved files with a model; other package managers; publishing runs to a store; MCP tools.
