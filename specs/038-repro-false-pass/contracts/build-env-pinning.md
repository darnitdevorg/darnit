# Contract: Build Environment Pinning (RE-01.02)

**Feature**: 038 (#431) | **Package**: `darnit-reproducibility` | **Status**: proposed

## Problem

RE-01.02 claims "Build environment is explicitly declared" and grants PASS at confidence 0.85 when any of eight filenames exists. A `Dockerfile` containing only `FROM alpine:latest` satisfies it. A floating tag is the opposite of a declared environment: it resolves to different bytes on different days, which is the property the control exists to rule out.

## Contract

### C-1: Two classes of declaration

A declaration is either inherently pinned or content-dependent. Inherently pinned declarations (`flake.nix`, `shell.nix`, `.tool-versions`, `.nvmrc`, `.python-version`) PASS on presence and MUST produce output byte-identical to today. Content-dependent declarations (`Dockerfile`, `Containerfile`) MUST be read.

### C-2: Only a digest pins

An image reference is acceptable when it carries `@sha256:<64 hex>`, is `scratch`, or names a stage declared earlier in the same file. Every tag is unacceptable, including specific-looking ones such as `3.12-slim-bookworm`. An image built from an unresolvable variable is unacceptable.

### C-3: Stage references are not images

Stage names introduced by `AS <name>` MUST be collected before classification and excluded from it. A later `FROM <name>` refers to a stage, not a registry image, and reporting it as unpinned is a false finding on every multi-stage build.

### C-4: The weakest reference governs

A file with one pinned and one floating `FROM` is unpinned.

### C-5: Verdict

| Classification | Status | Confidence | Message must |
|---|---|---|---|
| Pinned | PASS | 0.85 | name the declaration, as today |
| Unpinned | WARN | 0.85 | name the offending reference |
| No `FROM` lines | -- | -- | fall through as if the file were absent |

WARN rather than FAIL: the environment *is* declared, which is more than a repository with nothing. It is declared loosely, and WARN is the verdict for "we read it and it is incomplete." WARN counts as FAIL for compliance either way (Principle II), so nothing is softened -- only the message differs, and it should.

### C-6: A stronger declaration wins

A repository with both a `flake.nix` and an unpinned `Dockerfile` PASSes on the flake. Inherently-pinned declarations are checked first.

## Test obligations

| ID | Assertion |
|---|---|
| BE-1 | `FROM alpine@sha256:<64 hex>` gives PASS; output matches today's for the pinned case. |
| BE-2 | `FROM alpine:latest` gives WARN naming `alpine:latest`. |
| BE-3 | `FROM python:3.12-slim-bookworm` gives WARN. A specific-looking tag is still a tag. |
| BE-4 | A multi-stage file (`FROM x AS builder` then `FROM builder`) reports only the real image, never the stage name. |
| BE-5 | `FROM scratch` is acceptable. |
| BE-6 | `FROM $BASE_IMAGE` is unacceptable and says the reference could not be resolved. |
| BE-7 | Mixed pinned and floating gives WARN. |
| BE-8 | `flake.nix`, `.tool-versions`, `.python-version`, `.nvmrc` produce byte-identical output to before the change (SC-006). |
| BE-9 | `flake.nix` plus an unpinned `Dockerfile` gives PASS on the flake. |
| BE-10 | `.devcontainer` or `Vagrantfile` alone gives PASS, unchanged in v0. |
| BE-11 | A `Dockerfile` with no `FROM` lines is treated as absent. |
