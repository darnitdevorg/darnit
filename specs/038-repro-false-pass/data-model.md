# Phase 1 Data Model: Honest Verdicts for Reproducibility Controls

**Feature**: 038 | **Date**: 2026-09-20

Two new models and one changed verdict table. All within `darnit-reproducibility`.

---

## Container pinning (`darnit_reproducibility.container_pinning`)

A pure text-to-classification module, matching the boundary feature 037 drew for `requirements_pins`: it takes the contents of a container build file and returns a classification. It performs no file discovery and constructs no `HandlerResult`.

### `ImageReference`

One `FROM` line, after stage names are resolved.

| Field | Type | Notes |
|---|---|---|
| `raw` | `str` | the `FROM` line as written, for messages and evidence |
| `image` | `str \| None` | the reference; `None` for a stage reference |
| `stage_name` | `str \| None` | the `AS <name>` alias, when present |
| `pin` | `PinKind` | derived |

### `PinKind`

| Value | Condition |
|---|---|
| `DIGEST` | reference carries `@sha256:<64 hex>` |
| `SCRATCH` | `FROM scratch` -- the empty image, nothing to resolve |
| `STAGE_REF` | names a stage introduced by an earlier `AS` clause; not an image at all |
| `TAG` | any tag, including `latest` and specific-looking ones |
| `INDETERMINATE` | built from an `ARG` or variable the tool cannot resolve |

`DIGEST`, `SCRATCH`, and `STAGE_REF` are acceptable. `TAG` and `INDETERMINATE` are not: a tag is mutable, and an unresolvable reference cannot be claimed as pinned (Principle II).

**Stage names must be collected before classification.** A multi-stage build introduces names with `AS`, and later `FROM <name>` lines refer to them. Classifying those as images produces a spurious finding on every multi-stage Dockerfile -- including `packaging/container/Dockerfile` in this repository.

### `ContainerClassification`

The verdict about the file. **The weakest reference governs.**

| Value | Condition | RE-01.02 verdict |
|---|---|---|
| `PINNED` | at least one image reference, all acceptable | PASS @ 0.85 |
| `UNPINNED` | at least one `TAG` or `INDETERMINATE` | WARN @ 0.85, message names the reference |
| `NO_IMAGES` | no `FROM` lines found | treated as no container declaration |

Confidence stays at 0.85, the value this handler already uses. Feature 037 settled that content inspection does not by itself justify moving confidence, and this feature follows it.

---

## Build environment declarations (RE-01.02)

The existing `env_files` map splits in two.

| Class | Files | Behavior |
|---|---|---|
| Inherently pinned | `flake.nix`, `shell.nix`, `.tool-versions`, `.nvmrc`, `.python-version` | PASS on presence, output byte-identical to today (SC-006) |
| Content-dependent | `Dockerfile`, `Containerfile` | classified per the table above |
| Deferred | `.devcontainer`, `Vagrantfile` | PASS on presence, unchanged in v0 (research.md R2) |

Resolution order:

```text
any inherently-pinned declaration present?   -> PASS                      (unchanged)
Dockerfile or Containerfile present?
    classify contents
    PINNED      -> PASS                                                   (unchanged shape)
    UNPINNED    -> WARN, naming the offending reference
    NO_IMAGES   -> fall through as if the file were absent
.devcontainer or Vagrantfile present?        -> PASS                      (unchanged)
nothing                                      -> INCONCLUSIVE @ 0.0        (unchanged)
```

A repository with both a `flake.nix` and an unpinned `Dockerfile` passes on the flake. That is deliberate: the flake is a stronger declaration, and the first branch is reached first.

---

## Hermeticity scan (RE-02.01)

### `_ScanKind` gains a member

| Value | Meaning | Reported as |
|---|---|---|
| `safe` | known-good, blank, or comment | not reported |
| `deferred` | acceptable in this file type (`apt-get` in a Dockerfile) | noted, not a violation |
| `violation` | live network fetch during build | "Possible live network fetches in build files" |
| **`nondeterminism`** | **non-deterministic compiler flag** | **"Non-deterministic compiler flags"** |

The fourth kind exists so the two findings do not share a message. Reporting `-march=native` as a network fetch would be a false statement about what was found.

### Pattern tables

| Table | Added |
|---|---|
| `_SUSPICIOUS_PATTERNS` | `go install `, `go get `, `cargo install `, `gem install ` |
| `_NONDETERMINISTIC_FLAGS` (new) | `-ffast-math`, `-march=native`, `-mtune=native` |

`-O3` is excluded: at a fixed toolchain it is deterministic, and the non-determinism #432 describes comes from the unpinned toolchain rather than the flag (research.md R5).

A version-pinned installer (`go install pkg@v1.2.3`) remains a violation -- it still fetches at build time -- but the message names the pinned version, so a pinned fetch is distinguishable from a floating one (FR-011).

---

## Bit-for-bit signals (RE-03.01)

No model change. The signal scan and its evidence are unchanged; only the verdict drawn from them moves.

| Condition | Before | After |
|---|---|---|
| Signals found | PASS @ 0.8 | **WARN @ 0.8**, naming the signal and stating reproducibility was not verified |
| No signals found | INCONCLUSIVE | INCONCLUSIVE (unchanged) |

---

## Cross-control dependency (FR-010)

`_detect_strong_hermeticity_signal` reads `dependency_results.get("RE-01.02") == "PASS"` to gate its Nix path. Nothing about that expression changes. Its *inputs* change, because RE-01.02 now returns WARN for an unpinned container declaration.

| RE-01.02 | Nix signal available? | RE-02.01 outcome for a flake-plus-`nix build` repo |
|---|---|---|
| PASS (flake, or pinned Dockerfile) | yes | PASS, unchanged |
| WARN (unpinned Dockerfile, no flake) | no | falls through to the scan; INCONCLUSIVE if clean |

The second row is the accepted cost. The RE-02.01 result must say that the Nix signal was withheld because RE-01.02 did not pass, rather than leaving the operator to infer that the flake was not found (SC-010).
