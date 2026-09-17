# Contract: requirements.txt Pin Classification

**Feature**: 037 | **Package**: `darnit-reproducibility` | **Status**: proposed

The classifier takes text and returns a classification. It performs no file discovery, constructs no `HandlerResult`, and makes no decision about what verdict a classification deserves -- that mapping belongs to the handler. Keeping the boundary there is what lets the table below be tested as a pure function.

## Interface

```text
classify(text: str) -> FileClassification
```

`text` is the decoded contents of a `requirements.txt`. Unreadable and undecodable files never reach this function; the handler reports those as not-inspectable without calling it.

## Preprocessing, in order

1. Join backslash continuations into logical lines. **Before** hash extraction -- `pip-compile --generate-hashes` puts hashes on continuation lines, so extracting first would miss them.
2. Strip comments and drop blank lines.
3. Collect `--hash=<alg>:<digest>` values off each logical line.
4. Drop pip option lines (`--index-url`, `--extra-index-url`, `--find-links`, and siblings) and self-references (`-e .`, bare local paths). These are skipped, not classified (FR-018).
5. Flag `-r` / `-c` includes. The file is not-inspectable (FR-007); includes are not followed in v0.
6. Parse what remains as PEP 440 requirements.

## Line classification

| Input | Classification | Why |
|---|---|---|
| `numpy==1.26.4 --hash=sha256:...` | `HASH_PINNED` | exact version plus a hash |
| `numpy==1.26.4` | `EXACTLY_PINNED` | exact version, no hash |
| `numpy===1.26.4` | `EXACTLY_PINNED` | arbitrary equality is exact (spec Assumptions) |
| `pkg[extra]==1.0; python_version < "3.11"` | `EXACTLY_PINNED` | extras and markers do not bear on pinning (FR-009) |
| `pkg @ git+https://x/y@<40 or 64 hex>` | `EXACTLY_PINNED` | full object id; pinned, but not hash evidence (FR-010) |
| `pkg==1.*` | `NOT_PINNED` | wildcard; operator is `==` but the version is not exact (FR-008) |
| `pkg>=1.0,<2.0` | `NOT_PINNED` | compound specifier |
| `pkg>=1.0` / `pkg~=1.0` / `pkg!=1.0` | `NOT_PINNED` | open specifier |
| `numpy` | `NOT_PINNED` | no specifier at all |
| `pkg @ git+https://x/y@main` | `NOT_PINNED` | branch or tag, not an object id |
| `pkg @ git+https://x/y@abc1234` | `NOT_PINNED` | abbreviated ids resolve against repository state |

## File classification

The weakest line governs.

| Condition | Result |
|---|---|
| >= 1 line, all `HASH_PINNED` | `HASH_PINNED` |
| >= 1 line, all pinned, at least one without a hash | `VERSION_PINNED` |
| any line `NOT_PINNED` | `UNPINNED` |
| unresolved include, or a surviving line that fails to parse | `NOT_INSPECTABLE` |
| zero requirement lines after preprocessing | `NO_REQUIREMENTS` |

## Handler mapping

| Classification | Status | Confidence | Message must say |
|---|---|---|---|
| `HASH_PINNED` | PASS | 0.8 | that pinning was confirmed by reading the file, and that hashes were found (FR-004, US1 scenario 2) |
| `VERSION_PINNED` | WARN | 0.8 | that direct dependencies are pinned and transitive dependencies are not (FR-005) |
| `UNPINNED` | FAIL | 0.8 | at least one offending requirement by name (FR-006) |
| `NOT_INSPECTABLE` | FAIL | 0.8 | that contents could not be inspected -- never that they were read and found wanting (FR-007) |
| `NO_REQUIREMENTS` | n/a | n/a | handler proceeds as though the file were absent (FR-011) |

## Evidence (FR-012)

Every content-derived result records: the inspected file path, the classification reached, the number of requirement lines, and the specific requirements that drove the verdict. For `UNPINNED` that is the offending lines; for `VERSION_PINNED`, the lines lacking hashes. Evidence is bounded -- a file with 400 unpinned requirements must not paste 400 lines into the result -- so cap the enumerated examples and record the total count alongside.

## Test obligations

| ID | Assertion |
|---|---|
| T-1 | Every row of the line-classification table, one case each. |
| T-2 | Every row of the file-classification table. |
| T-3 | A mixed file (some hashed, some `==`) classifies `VERSION_PINNED`, not `HASH_PINNED`. |
| T-4 | A file of pinned requirements plus `-e .` and `--index-url` classifies on its requirements alone (FR-018). |
| T-5 | Hashes on continuation lines are collected, using a real `pip-compile --generate-hashes` fixture. |
| T-6 | A comments-and-blank-lines-only file yields `NO_REQUIREMENTS` and the handler falls through to the absent-file path. |
| T-7 | An unreadable file and an undecodable file both reach `NOT_INSPECTABLE` without the classifier being called. |
| T-8 | A lock file plus an all-`>=` requirements.txt still PASSes on the lock file, and the requirements contents are never read (US3, FR-001). |
