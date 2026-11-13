# darnit-amber

Scientific reproducibility checks plugin for darnit.

Provides five controls across three maturity levels:
- RE-01.01 (L1) DependenciesPinned — checks for lock files
- RE-01.02 (L1) BuildEnvDeclared — checks for Dockerfile, Nix flake, etc.
- RE-02.01 (L2) HermeticBuild — scans CI workflows for live network fetches
- RE-02.02 (L2) ProvenanceExists — checks for sigstore/cosign or SLSA provenance
- RE-03.01 (L3) BitForBitReproducible — checks for SOURCE_DATE_EPOCH and reprotest
## What the checks can conclude

Each check reads text and file-presence signals: lock files, environment
files, CI workflow contents. A signal can show that a requirement is unmet,
but a mention cannot show that it is met. A workflow that names
`cosign sign` in a comment produces no provenance.

So every check here registers the ceiling `{fail}` (feature 044, FR-010):

- A FAIL concludes the control, and only where the signal proves the
  requirement is unmet (for example, a dependency manifest with no lock file,
  or an unpinned requirement).
- A PASS the check reports is evidence only. The control continues to its
  later steps (model judgment, human review), which receive the signals. With
  no later step concluding, the control ends WARN: not compliant.
- A control concludes PASS automatically only when its step declares a
  `promotion` backed by a corpus measurement (framework-design 3.0.1, 5.5).
  None ships today.


## Amber runs: record an experiment, verify it, rerun it

A researcher runs their experiment once through darnit, inside the
artifact's checkout:

```
darnit-amber run -- ./run_experiment.sh
```

darnit runs the Amber audit and the command under CNCF Witness and stores
a signed **run bundle**: which repository and commit (from git; a checkout
with uncommitted changes or untracked files is refused unless
`--allow-dirty`, and then no commit is recorded), the exact command and its
exit status (a failing experiment is a result, so it still gets a bundle),
the environment (Python, OS, CPU and memory, and an allowlist of variables
such as `LANG`, `OMP_NUM_THREADS` and `CUDA_VISIBLE_DEVICES`; never the
host name, the user name, a path of the researcher's machine or anything
that could hold a credential: a path under the checkout or the home
directory is recorded as `$CHECKOUT/...` or `$HOME/...`, a system path
as is, any other only by its last name), every file the command created or changed (with
its contents, up to 10 MB each), and the Witness attestations. A clean
checkout is run from a fresh clone of its commit, so the experiment reads
only what the commit contains: files git ignores (caches, data, precomputed
results) are not there. Nothing is written by hand, and the whole statement
is signed by the researcher.

The bundle says which of its fields `verify` checks against a Witness
envelope and which the tool wrote down itself: `provenance.observed` names
the experiment's command, exit status, outputs and products, the audit's
command, exit code, report and results, and the envelope digests (the exit
status and the audit report are written under `.amber/` inside the checkout
so Witness hashes them, stored with the bundle, and read back by digest;
`.amber/` is removed afterwards); `provenance.self_reported` names the rest:
the host snapshot under `environment` (marked `recorded_by: darnit-amber`),
the entry, the claims and the verdict. Anyone can type the second kind; the
first kind cannot change without breaking an envelope signature or a
Witness-hashed record.

Two things the bundle records that are worth knowing before sharing it:
Witness keeps the command's **stdout and stderr** in the `command-run`
attestation, so an experiment that prints a secret stores it; and a clone
URL is recorded without its credentials, but the command line is recorded
as given.

Then, pointing at a number in one of those outputs, the researcher states
the paper's claim:

```
darnit-amber claim <bundle id> --id figure6a --file results/report.txt \
    --regex 'Queries/sec: ([0-9.]+)' --threshold '>= 120' --source 'Figure 6a'
```

darnit measures it from the stored output (checked against the digest in
the statement: a store is not trusted) and writes a new bundle
(`derived_from` the first, signed by whoever makes the claim, recorded as
`claim_signer`) with the verdict: `REPRODUCED`, `NOT_REPRODUCED`, or
`NOT_COMPARABLE` with `--not-comparable "reason"` for numbers that depend
on hardware the reviewer does not have.

Anyone with the bundle id can later check and repeat it:

```
darnit-amber verify <bundle id> --pubkey key.pub      # statement signature, outputs vs Witness, timestamps
darnit-amber rerun  <bundle id> --pubkey key.pub      # verify, then: same commit, same command, fresh clone
```

`rerun` verifies the bundle first and executes nothing from one that does
not verify. It then prints the command and asks, because the command runs
**on this machine, as this user, with this environment, in no container**
(darnit #677 step B adds the container); `--yes` answers for a script. The
artifact is cloned at the recorded commit, never run in place; a bundle
made from a local path without a remote names it `local/<directory name>`
and records no path, so `rerun` then needs `--artifact` with a clone. It
reports the exit status of both runs, per claim the first value and the
new one with both verdicts, and per output path of either run whether the
file is identical, changed, added or missing. `drift` is true when the
exit status changed, when a verdict changed, or when nothing was measured
and any output differs: a timing report that differs byte for byte but
gives the same verdict is not drift.

## Signing, time, and what is public

Nothing leaves the researcher's machine by default except a hash.

| | what it proves | who learns what |
|---|---|---|
| default | the bundle was signed with the researcher's key and existed at the time in the RFC 3161 countersignature (Sigstore's timestamp authority) | the timestamp authority sees a hash of the signature, nothing else |

The default key is generated once, ed25519, under darnit's data directory
(`~/.local/share/darnit/amber/signing.key` on Linux, mode 0600, with the
public half next to it); `--key` uses another PEM key instead, and
`--no-timestamp` skips the countersignature for offline runs; such a bundle
is signed but cannot be `verified`, because nothing places its signature in
time. The bundle records the key's fingerprint and the timestamp authority
under `signing`, never a path.

`verify` first checks that the bundle is one piece: the statement itself
is a signed DSSE envelope (`statement_envelope`) whose payload is, byte for
byte, the statement the id hashes, so nothing under `predicate` (claims,
verdict, audit results) can be edited after the fact; and the
statement names each Witness envelope by digest and its signer by key
fingerprint, so an envelope cannot be dropped or swapped. Stored outputs are hashed against the statement. It then reports,
per envelope (the statement and each Witness step), the signature check
and each timestamp's time, whether it covers that signature, and whether
its signer chains to a timestamp authority in Sigstore's trusted root
(fetched through TUF; the copy sigstore-python ships is used offline).
Every signature needs a trusted timestamp. The verifier must say who the
signer is: `--pubkey` (a signature nobody checked never counts as
verified), as `cosign verify` requires. A bundle that `claim` derived has
two signers: the run's, behind the Witness envelopes, and the claimer's,
behind the statement, so name both: `--pubkey researcher.pub
--claimer-pubkey reviewer.pub`; with no claimer key the run's is used,
which is right when the researcher claimed their own run. Each claim says
who stands behind it (`signed_by`: `signing`, `claim_signer`, or
`prior_claimer` with the earlier signer and bundle when a claim is carried
through a second `claim`). A bundle is `verified` only when every
check passes.

`verified` establishes that this exact bundle, signed with a key the
researcher holds, existed at the timestamp's time. Who holds the key, and
whether anyone else can confirm the bundle without the researcher's
cooperation, are the next steps (a Sigstore identity instead of a key, and
publication in a transparency log).

## Entry files

The same information can be given up front as a YAML (or JSON) entry with
`--claims entry.yaml`, which is how the test entries in `examples/` work
(SPF, AEADProtocols, GigaDORAM). `run -- <cmd>` overrides the entry's
`run.command`. An entry adds what cannot be inferred: the claims, and
`environment` when the experiment needs a specific image.

## Fields

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Short name, recorded in the bundle as `corpus_entry` |
| `artifact.clone`, `artifact.ref` | yes | Git URL and commit; `run` checks out exactly that commit |
| `environment` | when the experiment needs an image | See below |
| `run.command` | for an experiment step | Shell (`sh -c`) run inside the checkout under Witness |
| `run.outputs` | with `run.command` | Files the command writes; their digests go into the bundle |
| `claims[]` | yes | One per paper claim: `id`, `metric`, `threshold`, `unit`, `source`, `measurement_protocol`, `expected_verdict`, optional `tolerance`, optional `measure` |
| `expected_verdict` | yes | What the entry author expects overall: `REPRODUCED`, `NOT_REPRODUCED`, `NOT_COMPARABLE` |

## `measure`: reading the number out of the run

Without `measure`, a claim is carried into the bundle and gets
`NOT_COMPARABLE`: darnit has no way to know what number the run produced.
With it, darnit reads the value from an output file and compares it with
`threshold`.

```yaml
claims:
  - id: figure6a-queries-per-sec
    threshold: ">= 0"
    tolerance: 0.5          # optional, absolute, finite and >= 0, for numeric thresholds
    measure:
      file: amber-out/doram_timing_report1.txt   # relative to the checkout
      regex: '^Queries/sec: ([0-9.]+)'           # group 1 is the value, multiline
      scale: 100                                 # optional multiplier (0.71 -> 71)
      comparable: false                          # optional: record, do not judge
      reason: "throughput on different hardware"  # shown with NOT_COMPARABLE
```

`threshold` is `<op> <value>` with `op` in `==`, `!=`, `<`, `<=`, `>`, `>=`;
the value is numeric or a string (`== falsified`). Verdict per claim:

- `REPRODUCED`: value found and the comparison holds (within `tolerance`)
- `NOT_REPRODUCED`: value found, comparison fails
- `NOT_COMPARABLE`: no `measure`, file not produced by the experiment or
  regex missing, `comparable: false`, or a comparison that makes no sense
  (`<`, `<=`, `>`, `>=` need two numbers; `9 ms` against `> 10` is not
  reproduced, it is not comparable)

`measure.file` must be a file the experiment produced, as Witness recorded
it: a `results/table.txt` committed with the artifact is never measured,
however good its numbers look. The overall verdict is `REPRODUCED` only when
every claim is, `NOT_REPRODUCED` when any is, and `NOT_COMPARABLE` otherwise:
a claim that could not be measured counts against the run. Each claim also
records `matches_expected`, so a run of an entry doubles as a test of the
entry.

Use `comparable: false` for performance numbers measured on different
hardware than the paper's, or when the paper gives no tolerance: the value
is still recorded and compared across reruns, but no one is told the paper
failed to reproduce because of a slower machine.

## `environment`: the image the experiment runs in

Many experiments only run inside a specific toolchain. Two cases:

1. The authors publish an image (AEADProtocols: `docker.io/aeads/tamarin`).
   `run.command` runs it with `podman run` and mounts the checkout.
2. No image exists (GigaDORAM). The entry carries the Containerfile that
   builds one, and names the image by tag and digest:

```yaml
environment:
  image: "localhost/gigadoram:06cfefb"
  image_digest: "sha256:60457c90…"
  containerfile: |
    FROM docker.io/library/ubuntu:22.04
    …
  notes: "emp-tool pinned to 0.2.5; tc needs --cap-add NET_ADMIN"
```

Today the image is built by hand from `containerfile` on the machine that
runs the entry. A later step can build and push it to a registry (GHCR)
and pin the digest automatically. `environment` is recorded verbatim in
the bundle, next to the host's `environment` snapshot in the predicate.

## Bundle contents

`run` produces an in-toto statement with predicate
`https://darnit.dev/amber/run/v1`: the entry (`corpus_entry`, `claims`
with `measured`, `verdict`, `reason`), the Amber audit result, the
experiment (`command`, `exit_code`, `outputs` with sha256), the overall
`verdict`, the `environment` snapshot, the signer (`signing`) and the
digest of each Witness envelope. The bundle holds that statement, its
signature (`statement_envelope`, a DSSE envelope over the canonical
statement, signed and timestamped like the steps), the Witness envelopes
for both steps (git, command-run and product attestations), and a
`publication` slot, empty until the bundle is recorded in a transparency
log. The bundle id is the sha256 of the
canonical statement. A bundle made with `--no-timestamp` is signed but
cannot be `verified`: nothing places its signatures in time.

`rerun` executes the same command at the same commit, re-measures the
claims, and stores a new bundle with `reruns.of`, `reruns.outputs` (digest
first vs rerun) and `reruns.claims` (value and verdict first vs rerun).
`drift` is true when the exit status changed, when a claim's verdict
changed, or when nothing was measured and an output changed, appeared or
went missing. A timing report that differs byte for byte but gives the
same verdict is not drift.

## Example entries

| Entry | Experiment | Verdict | Rerun |
|---|---|---|---|
| `usenixsec2024-spf-centralization` | Python script over precomputed data, 3 s | NOT_COMPARABLE (71.3 %, expected) | outputs identical |
| `usenixsec2023-aeadprotocols` | Tamarin proof in the authors' image, ~1 min | REPRODUCED (`falsified`) | outputs identical |
| `usenixsec2023-gigadoram` | C++ benchmark in a locally built image, 2 s (10 min build) | NOT_COMPARABLE (126.8 queries/s) | report changed, verdict same, no drift |
