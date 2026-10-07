# Addendum: `repro_witness_attestation`, a FAIL-only runtime-trace step

**Amends**: [step-contract.md](step-contract.md) section 5 and FR-010 (reproducibility step ceilings)
**Issue**: #553
**Authoritative text**: `docs/architecture/framework-design.md` section 3.0.1 (scenario "A runtime trace proves only network access") and section 12

## Why

`repro_hermetic_build` fetched and Sigstore-verified Witness / in-toto attestations from the repository's latest successful CI run on the default branch and treated a verified, empty network log as a PASS strong signal. Three things were wrong with that:

1. **An empty log is not proof of no network access.** The in-toto runtime-trace v0.1 parsing rules make an absent or null optional list equivalent to an empty one, and what `monitorLog.network` records depends on `monitor.type` and its `tracePolicy`. A monitor that does not trace sockets produces the same empty log as a build that made no connection; the spec's own Tetragon example, with a `connect` policy, has no `network` field at all.
2. **The attestation was not bound to what was audited.** The latest successful run on the default branch need not have built the checked-out commit.
3. **The predicate was matched loosely.** Any statement with a top-level `network` key, or any payload containing `"network"`, was read as a runtime trace.

Splitting the check into its own step gives it its own ceiling and its own setting, and leaves `repro_hermetic_build` a filesystem-only scan.

## 1. Registration

| Field | Value |
|---|---|
| Step type | `repro_witness_attestation` |
| Registered by | `darnit-reproducibility`, in `register_sieve_handlers` |
| Phase | `deterministic` |
| Ceiling | `{fail}` |
| Settings | `verify_witness_attestations` (bool, default `true`) |
| Expression names | none |

`repro_hermetic_build` keeps ceiling `{fail}` and now declares no settings. Under strict loading (section 3.0.3) a step that sets `verify_witness_attestations` on `repro_hermetic_build`, in shipped TOML or an operator pass override, fails loading.

## 2. Inputs and binding

| Input | Source |
|---|---|
| Repository identity | `ctx.owner`, `ctx.repo` |
| Audited commit | `git rev-parse HEAD` in `ctx.local_path` |
| Runs | `gh run list --repo <owner>/<repo> --commit <sha> --status success --limit 5 --json databaseId` |
| Artifacts | `gh run download <run> --repo <owner>/<repo> --pattern '*witness*'` for each run; `*.json` files, those ending `.att.json`, `.bundle.json`, `.sigstore.json` first, at most 20 |
| Verification | Sigstore bundle, DSSE payload type containing `in-toto`, policy `AllOf([OIDCIssuer("https://token.actions.githubusercontent.com"), GitHubWorkflowRepository("<owner>/<repo>"), GitHubWorkflowSHA("<sha>")])` |

A file that does not verify under that policy is not read. Unsigned DSSE envelopes, bundles signed by another repository's workflow, and bundles signed by a workflow run for another commit are all ignored.

## 3. What is read from a verified statement

| Source | Read | Used as |
|---|---|---|
| Statement with `predicateType` exactly `https://in-toto.io/attestation/runtime-trace/v0.1` | `predicate.monitorLog.network`, `predicate.monitor.type` | Network events; monitor type for evidence |
| Entry of a Witness `https://witness.dev/attestation-collection/v0.1` whose `type` is exactly the runtime-trace URI | `attestation.monitorLog.network`, `attestation.monitor.type` | Same |
| Entry of a Witness collection whose `type` names `command-run` | `processes[].program`, `processes[].cmdline` | Matched against the installer patterns (`curl `, `wget `, `pip install `, ...) |

Nothing else is read. A top-level `network` key on any other predicate type is ignored. A `network` value that is not a list is treated as unrecognized and decides nothing.

## 4. Outcomes

Every verified file is examined; one that records network access decides the step even if an earlier one was clean.

| Situation | Outcome | Message / evidence |
|---|---|---|
| `verify_witness_attestations = false` | INCONCLUSIVE | Verification is disabled. No `git` or `gh` call is made. |
| `sigstore` not installed | INCONCLUSIVE | Names the `attestation` extra. |
| No `owner`/`repo` | INCONCLUSIVE | Repository identity unavailable. |
| `ctx.local_path` has no commit | INCONCLUSIVE | No commit to bind to. |
| `gh` missing, unauthenticated, timed out, or failed | INCONCLUSIVE | The specific `gh` reason. |
| No successful run for the commit | INCONCLUSIVE | Names the commit. |
| No `*witness*` artifacts | INCONCLUSIVE | Names the runs. |
| Artifacts found, none verified | INCONCLUSIVE | Lists the files checked. |
| Verified runtime trace with a non-empty `monitorLog.network` | **FAIL** | Names the artifact and the event count. |
| Verified command-run process matching an installer pattern | **FAIL** | Names the artifact, the pattern, and the command line. |
| Verified, network log empty or absent, nothing suspicious | INCONCLUSIVE | A clean runtime trace is recorded as evidence but cannot by itself establish that the build had no network access. Evidence names the artifact(s) and monitor type(s). |

Evidence is under the single key `witness_attestation` (commit, runs, checked files, verified artifacts, monitor types, the deciding artifact) so it cannot collide with `repro_hermetic_build`'s keys in the control's gathered evidence.

The step never raises.

## 5. Why missing evidence is INCONCLUSIVE, not ERROR

An ERROR records a broken measurement and, when no later step concludes, makes the control ERROR (section 3.0.2). This step can only add FAIL evidence. Turning "no `gh` login" or "no attestation published" into ERROR would change an RE-02.01 that would otherwise end WARN (no step concluded) into ERROR, on a repository that never claimed to publish runtime traces, for an optional evidence source. So every missing prerequisite is INCONCLUSIVE with the specific reason, as the check did inside `repro_hermetic_build`.

## 6. RE-02.01 order

```toml
[[controls."RE-02.01".passes]]
handler = "repro_witness_attestation"

[[controls."RE-02.01".passes]]
handler = "repro_hermetic_build"

[[controls."RE-02.01".passes]]
handler = "manual"
```

The attestation step runs first: a verified record of network access concludes FAIL even when the repository also carries a Nix or Bazel strong signal, which `repro_hermetic_build` reports only as evidence.

## Follow-up (not in this change)

PASS from a runtime trace needs a built-in allowlist of monitor types (and trace policies) known to record socket activity, each backed by real attestations in the corpus, and a corpus-backed `promotion` on the step (section 5.5). Until then no verified trace concludes PASS.

## Unchanged

- The ceilings of the other five reproducibility step types and their promotion rule (step-contract.md section 5).
- `repro_hermetic_build`'s CI-text scan, its Nix (gated on RE-01.02) and Bazel strong signals, and their evidence-only PASS.
