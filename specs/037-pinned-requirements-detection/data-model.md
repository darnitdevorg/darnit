# Phase 1 Data Model: Pinned-Requirements Detection

**Feature**: 037 | **Date**: 2026-09-17

Two models, in two packages. The plugin model describes what a requirements file says; the framework model describes what a handler is allowed to conclude.

---

## Plugin model (`darnit_reproducibility.requirements_pins`)

### `RequirementLine`

One logical dependency declaration, after continuations are joined and comments stripped.

| Field | Type | Notes |
|---|---|---|
| `raw` | `str` | the joined logical line, for messages and evidence |
| `name` | `str \| None` | `None` for a line that failed to parse |
| `specifier` | `str` | PEP 440 specifier set, empty string when absent |
| `hashes` | `list[str]` | `--hash=` values collected from the line and its continuations |
| `url` | `str \| None` | direct reference target, when the line uses `@` |
| `pin` | `PinClassification` | derived, see below |

Validation rules (FR-008, FR-009, FR-010, FR-018):

- A line that is a pip option (`--index-url`, `--extra-index-url`, `--find-links`, and siblings) or a self-reference (`-e .`, a bare local path) is **not** a `RequirementLine`. It is dropped during preprocessing and never classified.
- An `InvalidRequirement` from a line that survived preprocessing is a parse failure, not a skip. It makes the file not-inspectable -- the tool cannot claim to have understood a file containing a line it could not read.

### `PinClassification`

The verdict about a single line.

| Value | Condition |
|---|---|
| `HASH_PINNED` | exact version (see below) **and** at least one hash |
| `EXACTLY_PINNED` | exact version and no hash, **or** a direct reference at a full commit SHA |
| `NOT_PINNED` | anything else |

"Exact version" means a specifier set of exactly one clause whose operator is `==` or `===` and whose version contains no wildcard. `pkg==1.*` parses with operator `==` and version `1.*`, which is why the wildcard test is on the version string and not on the operator (FR-008). A compound specifier such as `pkg>=1.0,<2.0` has more than one clause and is `NOT_PINNED` without needing a substring check.

Extras and environment markers are parsed and discarded -- they decorate a requirement without bearing on whether its version is pinned (FR-009).

### `FileClassification`

The verdict about the file. **The weakest line governs.**

| Value | Condition | Control verdict |
|---|---|---|
| `HASH_PINNED` | at least one requirement line, and every line is `HASH_PINNED` | PASS @ 0.8 |
| `VERSION_PINNED` | at least one line, every line is `HASH_PINNED` or `EXACTLY_PINNED`, and at least one is `EXACTLY_PINNED` | WARN @ 0.8 |
| `UNPINNED` | at least one line is `NOT_PINNED` | FAIL @ 0.8 |
| `NOT_INSPECTABLE` | unreadable, undecodable, an unresolved `-r`/`-c` include, or a line that failed to parse | FAIL @ 0.8, message says contents could not be inspected |
| `NO_REQUIREMENTS` | zero requirement lines after preprocessing | treated as file absent (FR-011) |

`VERSION_PINNED` deliberately covers "some lines hashed, some not." A partially hashed file has no stronger guarantee than its weakest line, and pip's require-hashes mode refuses to install such a file at all.

Confidence is 0.8 for every content-derived verdict (FR-020), matching the lock-file path.

### Evaluation order in the handler (FR-001, FR-002, FR-011, FR-019)

```text
lock file present?            -> PASS, contents never read            (unchanged)
root requirements.txt present?
    classify contents
    NO_REQUIREMENTS           -> fall through as if the file were absent
    otherwise                 -> PASS / WARN / FAIL per the table
any other loose manifest?     -> FAIL by presence                     (unchanged)
nothing                       -> INCONCLUSIVE @ 0.0                   (unchanged)
```

Only the middle branch is new. The first, third, and fourth are the existing code paths and must produce byte-identical output (SC-004, SC-005).

---

## Framework model (`darnit.sieve`)

### `HandlerResultStatus` gains `WARN`

| Member | Meaning | Concludes the control? |
|---|---|---|
| `PASS` | satisfied | yes, under terminal authority |
| `FAIL` | not satisfied | yes, under terminal authority |
| **`WARN`** | **determined to be incomplete -- evidence was read and found insufficient** | **yes, under terminal authority** |
| `INCONCLUSIVE` | nothing determined | no, pipeline continues |
| `ERROR` | did not complete | terminal regardless of authority |

WARN is not a weaker INCONCLUSIVE. INCONCLUSIVE means the handler learned nothing; WARN means it learned that the answer is "not enough." That distinction is the whole point of FR-016.

### `StepDisposition` gains `CONCLUDE_WARN`

The disposition table after this change (`resolve_step_result`):

| Handler status | Terminal authority | Non-terminal, not last | Non-terminal, last step |
|---|---|---|---|
| `ERROR` | `TERMINATE_ERROR` | `TERMINATE_ERROR` | `TERMINATE_ERROR` |
| `PASS` | `CONCLUDE_PASS` | `ATTACH_EVIDENCE_AND_CONTINUE` | `TERMINATE_INCONCLUSIVE` |
| `FAIL` | `CONCLUDE_FAIL` | `ATTACH_EVIDENCE_AND_CONTINUE` | `TERMINATE_INCONCLUSIVE` |
| **`WARN`** | **`CONCLUDE_WARN`** | **`ATTACH_EVIDENCE_AND_CONTINUE`** | **`TERMINATE_INCONCLUSIVE`** |
| `INCONCLUSIVE` | `ATTACH_EVIDENCE_AND_CONTINUE` | `ATTACH_EVIDENCE_AND_CONTINUE` | `TERMINATE_INCONCLUSIVE` |

The WARN row is the PASS/FAIL row. That is the design: WARN is a conclusion, so it is gated like one.

### `PassOutcome` gains `WARN`

Records in `pass_history` that this pass concluded WARN rather than reaching no conclusion (research.md R2).

### `SieveResult` -- no change

`status` is already `CheckStatus = Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM"]` (`sieve/models.py:93`), and `darnit.core.models.CheckStatus` already has a `WARN` member. Downstream consumers -- formatters, compliance arithmetic, harness exit codes -- already handle WARN, because the all-inconclusive fallthrough has been producing it all along. **This feature adds no new value to any downstream type.** It adds a second, more informative way to arrive at a value they already accept.

### `CONCLUDE_WARN` result construction

The new branch in `_dispatch_handler_invocations` mirrors `CONCLUDE_FAIL`, carrying `message`, `confidence`, `evidence`, `resolving_pass_index`, `resolving_pass_handler`, `authority`, and `error_class`.

`error_class` is carried for the same reason `CONCLUDE_FAIL` carries it: a handler that classified an environmental failure and returned WARN should not lose that classification. Unlike `CONCLUDE_PASS` -- where `HandlerResult.__post_init__` provably forbids the pairing -- nothing forbids `WARN` with an `error_class`, so it must be threaded rather than reasoned away.
