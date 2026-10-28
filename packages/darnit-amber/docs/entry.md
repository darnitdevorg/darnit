# Amber run entry

An entry is a YAML (or JSON) file that tells `darnit-amber run` what an
experiment is, how to run it, and how to read its result. The researcher
writes one per experiment; the files in `entries/` are the three used to
test the loop end to end (SPF, AEADProtocols, GigaDORAM).

darnit-amber run <git url> --ref <commit> --claims entry.yaml --key key.pem --store s3 --bucket …
darnit-amber verify <bundle id> [--pubkey key.pub]
darnit-amber rerun <bundle id> --key key.pem


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
    tolerance: 0.5          # optional, absolute, for numeric thresholds
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
- `NOT_COMPARABLE`: no `measure`, file or regex missing, or `comparable: false`

The overall verdict is the worst claim. Each claim also records
`matches_expected`, so a run of an entry doubles as a test of the entry.

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
the bundle, next to Witness's own environment attestation of the host.

## What goes into the bundle

`run` produces an in-toto statement with predicate
`https://darnit.dev/amber/run/v1`: the entry (`corpus_entry`, `claims`
with `measured`, `verdict`, `reason`), the Amber audit result, the
experiment (`command`, `exit_code`, `outputs` with sha256), the overall
`verdict`, and the Witness envelopes for both steps (environment, git,
command-run, product attestations, signed with `--key`). The bundle id is
the sha256 of the canonical statement.

`rerun` executes the same command at the same commit, re-measures the
claims, and stores a new bundle with `reruns.of`, `reruns.outputs` (digest
first vs rerun) and `reruns.claims` (value and verdict first vs rerun).
`drift` is true when a claim's verdict changed, or when an output changed
and nothing was measured. A timing report that differs byte for byte but
gives the same verdict is not drift.

## Entries in this directory

| Entry | Experiment | Verdict | Rerun |
|---|---|---|---|
| `usenixsec2024-spf-centralization` | Python script over precomputed data, 3 s | NOT_COMPARABLE (71.3 %, expected) | outputs identical |
| `usenixsec2023-aeadprotocols` | Tamarin proof in the authors' image, ~1 min | REPRODUCED (`falsified`) | outputs identical |
| `usenixsec2023-gigadoram` | C++ benchmark in a locally built image, 2 s (10 min build) | NOT_COMPARABLE (126.8 queries/s) | report changed, verdict same, no drift |
