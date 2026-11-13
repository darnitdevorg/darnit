# Feature Specification: Amber Run Bundles

**Feature Branch**: `amber-run-bundle` (PR #678, on #532; the Sigstore identity, Rekor publication and S3 store follow in separate PRs)

**Created**: 2026-11-04

**Status**: Draft

**Input**: darnit issue #677 (steps A, C, D: record an experiment under Witness, verify the record, rerun it) and the review of PR #678 on 2026-11-01, whose findings B1-B8 and the should-fix list this specification answers.

## Background

An artifact-evaluation reviewer wants to know three things about a paper's experiment: what was run, what came out, and whether running it again gives the same answer. `darnit-amber run` records one execution as a **run bundle**; `verify` checks that a bundle is what it says it is; `claim` attaches a paper's number to a recorded run; `rerun` repeats a verified run and compares.

Constitution Principle II applies as it does to compliance verdicts: a `REPRODUCED` must come only from a measurement that establishes it, and a false `REPRODUCED` is worse than a false `NOT_REPRODUCED`. The review of the first draft found `verified: true` for content nothing signed, claims measured from files the experiment never wrote, `REPRODUCED` from a string comparison, and stored outputs that could be rewritten in place. Each of those is a false-PASS path; this specification closes them.

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

## User Scenarios & Testing *(mandatory)*

### Primary scenarios

1. A researcher runs `darnit-amber run -- ./run_experiment.sh` in a clean checkout. The bundle records the commit, the command, its exit status, the outputs the command produced, the audit result, the environment allowlist and the signer; the statement is signed; the outputs are stored.
2. A reviewer runs `verify <id> --pubkey researcher.pub`. Every check passes and `verified` is true. The reviewer edits a claim in the JSON and recomputes the id: `statement_signed` is false and `verified` is false.
3. The reviewer runs `claim <id> --file results/report.txt --regex ... --threshold '>= 120'`. The value is read from the stored output after its digest is checked; the derived bundle is signed by the reviewer and records `claim_signer`.
4. The reviewer runs `rerun <id> --pubkey researcher.pub`. `rerun` verifies the bundle, prints the command, asks, clones the recorded commit into a temporary directory and runs there; the new bundle compares outputs and claims with the first.
5. An artifact ships `results/table.txt` with the paper's numbers and an experiment that only writes a log. The claim over `results/table.txt` is `NOT_COMPARABLE` ("not produced by the experiment"), and so is the run.

### Acceptance tests

All in `tests/darnit_amber/test_run_bundle.py`, with Witness and signing replaced by fakes: forgery of the predicate (FR-001), claims from committed files (FR-004), non-numeric ordering (FR-005), rewritten stored outputs (FR-006), credentials in URLs and the environment (FR-010), the exit-status wrapper (FR-012), rerun without verification or consent (FR-014), `--pubkey` against the wrong key and against an envelope carrying a certificate (FR-008), one envelope without a timestamp (FR-009).

## Requirements *(mandatory)*

### Functional

- **FR-001 Signed statement.** A bundle carries `statement_envelope`: a DSSE envelope of type `https://in-toto.io/Statement/v1` whose payload is the canonical statement, signed by the run's key and timestamped like the Witness steps. `verify` passes `statement_signed` only when that payload equals the canonical statement byte for byte, and passes the envelope's signature check only with the signer the verifier named.
- **FR-002 One piece.** The statement names each Witness envelope by digest (`witness_envelopes_sha256`) and its signer (`signing`: the key fingerprint). `verify` fails when an envelope is missing, swapped, or signed by a key other than the one named.
- **FR-003 Bundle id.** The id is the sha256 of the canonical statement. It names the bundle; it proves nothing by itself. `publication` is a slot beside the statement, not inside it (empty here; a transparency-log record goes there in a follow-up), so the id does not change when a bundle is published.
- **FR-004 Claims from products only.** `measure_claim` reads from the bytes of outputs Witness recorded as products, hashed as Witness hashed them. A `measure.file` that is not such an output gives `NOT_COMPARABLE` with the reason "not produced by the experiment". `measure.file` is confined to the checkout (`safe_rel`).
- **FR-005 Comparisons.** `<`, `<=`, `>`, `>=` require two numbers; otherwise the claim is `NOT_COMPARABLE` with the reason. `==` and `!=` fall back to text. `tolerance` applies to every numeric operator, must be a finite number >= 0, and the reason says when a comparison holds only because of it. A value or threshold is a number only in plain decimal notation and finite: `inf`, `nan`, `1_000` and hexadecimal are not numbers here, and because they look like numbers they are not compared as text either; such a claim is NOT_COMPARABLE. Measurement never raises: a bad regex or spec is a `NOT_COMPARABLE` with the error as reason.
- **FR-006 Stored outputs.** Every read of a stored output checks its sha256 against the statement; `claim` refuses a mismatch, and `verify` reports `stored_outputs_match`.
- **FR-007 Overall verdict.** `REPRODUCED` only when every claim is `REPRODUCED`; `NOT_REPRODUCED` when any is; `NOT_COMPARABLE` otherwise, including an entry with no claims.
- **FR-008 Expected signer.** `--pubkey` names the signing key: it must match the fingerprint in the statement and verify every signature. Without it a key-signed bundle is reported, not verified. An envelope that carries a certificate is not the key-signed envelope the statement describes and fails the check; a statement naming an unknown signing method fails it too.
- **FR-009 Timestamps.** Every signature on every envelope (statement and steps) needs a trusted RFC 3161 timestamp that covers it and chains to a timestamp authority in Sigstore's trusted root. A bundle made with `--no-timestamp` cannot be verified.
- **FR-010 What leaves the machine.** Clone URLs are recorded without userinfo, query string or fragment. `VIRTUAL_ENV`, `CONDA_PREFIX` and each entry of `PYTHONPATH` are recorded relative to the checkout or the home directory (`$CHECKOUT/...`, `$HOME/...`); a path under a system prefix (`/usr`, `/opt`, `/lib`, `/etc`, `/nix`, ...) is kept, and any other absolute path keeps only its last name (`$ELSEWHERE/<name>`); a local artifact with no remote is named `local/<directory name>`. The environment is an allowlist (`ENV_ALLOWLIST`) recorded in the statement; the Witness environment attestor is not used. The README says that stdout and stderr are recorded.
- **FR-011 Clean commit.** A checkout with uncommitted changes or untracked files is refused unless `--allow-dirty`; then it runs in place, the subject carries no `gitCommit`, `entry.artifact.dirty` is true, and the bundle cannot be rerun. A clean checkout, a URL, and a local path run at a named `--ref` are executed from a fresh clone of the commit, so files git ignores are not there: the experiment reads only what the commit contains.
- **FR-012 Failed experiments.** The experiment runs in a wrapper that records its exit status in `.amber/exit` inside the checkout and exits 0, so Witness attests the command and hashes the record as a product; the audit step writes its report to `.amber/audit.json` the same way. Both records are stored with the bundle (`experiment.exit_status`, `audit.report`: path and digest), and `.amber/` is removed after each step. `verify` checks that the command Witness ran is the wrapper of the recorded command, that the audit command is the one recorded, and that each stored record matches the digest Witness hashed and yields the recorded `exit_code` and `audit.results`.
- **FR-013 Store first.** The bundle and its outputs are stored as one step, before anything else happens to them; a follow-up that records the envelopes in a transparency log must leave a stored, signed bundle behind when it fails.
- **FR-014 Rerun consent.** `rerun` verifies the bundle with the same flags as `verify` and executes nothing from a bundle that does not verify. It shows the command and requires consent (`--yes`, or a terminal answer). A local-path artifact is cloned at the recorded commit; the working tree is never run in place.
- **FR-015 Errors.** The CLI reports a bad entry, regex, path or store problem as a one-line error with exit 1, never a traceback.
- **FR-016 Audit output.** The audit's JSON is written outside the checkout; `run` leaves nothing in the repository.
- **FR-017 Isolation in tests.** No test writes a signing key under the developer's data directory: the test suite replaces `user_data_root` for every test.
- **FR-018 Two signers.** A bundle `claim` derived has `claim_signer` for its statement and keeps `signing` for the Witness envelopes. `verify` checks the statement against the claimer's key (`--claimer-pubkey`) and the envelopes against the run's; with no claimer key the run's applies to both, and a failing statement check says which flag names the claimer. Every claim carries `signed_by` from the run on (`signing`); `claim` marks the one it adds `claim_signer`. Only the claimer signs a derived statement; the earlier bundle, with the run signer's own statement, stays in the store under `derived_from`.
- **FR-019 Provenance.** The predicate carries `provenance.observed`, exactly the keys `verify` checks against a Witness envelope (`audit.command`, `audit.exit_code`, `audit.report`, `audit.results`, `experiment.command`, `experiment.exit_code`, `experiment.exit_status`, `experiment.outputs`, `experiment.products`, `witness_envelopes_sha256`), and `provenance.self_reported`, the keys darnit-amber wrote down itself (`started_at`, `environment`, `signing`, `entry`, `claims`, `verdict`). `environment.recorded_by` names the tool. A reader can tell which fields a forger could type and which would break an envelope signature or a Witness-hashed record.

### Non-functional

- `sigstore` and `rfc3161-client` are dependencies: `verify` needs Sigstore's trusted root (its timestamp authorities) for any bundle.

## Out of scope

- Running the experiment in a pinned container (darnit #677 step B).
- Signing with a Sigstore identity instead of a key, and recording the envelopes in Rekor: the two PRs that follow this one.
- An S3-compatible attestation store: a third follow-up PR.
- MCP tools for `run`, `verify`, `claim` and `rerun`: a design question for the `#677` thread.
- Choosing between key and keyless signing by default, and between an S3 store and GHCR: decided on #677.
