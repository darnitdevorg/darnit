# Quickstart: Honest Verdicts for Reproducibility Controls

**Feature**: 038 | **Date**: 2026-09-20

## What changed, in one paragraph

Three reproducibility controls used to report repositories as better than the evidence supported. RE-03.01 said a build was bit-for-bit reproducible because `SOURCE_DATE_EPOCH` appeared in a workflow file. RE-01.02 said a build environment was declared because a `Dockerfile` existed, even `FROM alpine:latest`. RE-02.01 missed `go install` and `cargo install` entirely, and never looked at compiler flags. All three now say what they actually found.

## Before and after

| Repository shape | Control | Before | After |
|---|---|---|---|
| `SOURCE_DATE_EPOCH` in `publish.yml` | RE-03.01 | PASS | WARN, naming the signal and the gap |
| `Dockerfile` with `FROM alpine:latest` | RE-01.02 | PASS | WARN, naming `alpine:latest` |
| `Dockerfile` with `FROM alpine@sha256:...` | RE-01.02 | PASS | PASS, unchanged |
| `flake.nix` | RE-01.02 | PASS | PASS, unchanged |
| Workflow running `go install` | RE-02.01 | not detected | violation naming the command |
| Makefile with `-march=native` | RE-02.01 | not detected | finding naming the flag |

## Running it

```bash
uv run pytest tests/darnit_reproducibility/ -v
uv run ruff check .
uv run pytest tests/ --ignore=tests/integration/ --ignore=tests/darnit/parity/tier2 -q
uv run python scripts/validate_sync.py --verbose
```

Note the test-ignore spelling: `--ignore=tests/darnit/parity/tier2`, not `--ignore=tests/darnit/parity`. The broader form skips parity tier 1, which CI runs.

## Try it on this repository

```bash
uv run darnit audit --framework reproducibility . --no-fail
```

RE-01.02 **passes**, and the reason is worth understanding before you use this
feature anywhere else:

```text
RE-01.02: PASS - Build environment declared via: .python-version (pyenv)
```

darnit has a `.python-version` at its root. That is an inherently-pinned
declaration, it is checked before any container file, and a stronger
declaration wins (contract BE C-6). So the `Dockerfile` is never inspected.

It would not have passed on its own:

```bash
grep '^FROM' packaging/container/Dockerfile
# FROM python:3.12-slim-bookworm AS builder
# FROM python:3.12-slim-bookworm
```

Copy that Dockerfile into an otherwise empty directory and audit it, and
RE-01.02 returns:

```text
WARN - Build environment is declared but not pinned:
Dockerfile: python:3.12-slim-bookworm; Dockerfile: python:3.12-slim-bookworm
-- a tag is mutable, so the environment resolves differently on different builds.
Pin by digest (image@sha256:...)
```

Two things to notice. `python:3.12-slim-bookworm` is a tag, so it fails even
though it looks specific. And `AS builder` introduces a stage name that the
second `FROM` refers back to -- the result names the real image twice and never
mentions `builder`, which is what a naive scan gets wrong on every multi-stage
build.

**The consequence worth weighing**: a Python project with a `.python-version`
never has its container file checked, no matter how floating its base image is.
That follows from BE C-6 and is implemented as specified, but it narrows the
reach of this change considerably for exactly the ecosystem darnit is written
in.

## The change that will surprise people

A repository with a `flake.nix`, `nix build` in CI, and an unpinned `Dockerfile` **loses an RE-02.01 PASS without having changed anything.**

The Nix hermeticity signal has always been gated on RE-01.02 having passed -- the reasoning being that a bare flake which is not the project's confirmed build environment is not a strong signal on its own. Once RE-01.02 stops confirming an unpinned container declaration, the gate's premise is gone.

Keeping the PASS would preserve a verdict whose justification this change removes. The result message says the Nix signal was withheld because of RE-01.02, so the cause is visible rather than inferred.

## What did not change

- Repositories declaring their environment via `flake.nix`, `.tool-versions`, `.python-version`, or `.nvmrc`: byte-identical RE-01.02 output.
- `.devcontainer` and `Vagrantfile`: still judged by presence in v0.
- RE-02.01's existing PASS conditions: a verified Witness attestation and Bazel with a blocking flag are untouched.
- RE-03.01 with no signals found: unchanged.
- Every control outside these three, in every framework: unchanged.

## Reviewing a verdict

Each changed verdict names what was examined and what was concluded. For RE-01.02 that is the offending image reference; for RE-02.01, the command or flag and the file it came from; for RE-03.01, the signal found and the statement that reproducibility was not verified.
