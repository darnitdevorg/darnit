# Phase 1 Data Model: Canonical Vocabulary and Value Lifecycle

This feature ships no code, so this document is not a schema. It fixes the
vocabulary and the state machine the amended text must express, so that the
constitution, CLAUDE.md, and ARCHITECTURE.md can be checked for agreement
against something concrete rather than against each other.

## Vocabulary

Use these terms consistently across all amended documents. The right-hand
column names what the term must not be confused with, because each confusion
has already appeared somewhere in the repository.

| Term | Meaning | Not to be confused with |
|---|---|---|
| User-judgment key | A context key whose correct value requires a person's decision rather than observation. Marked `auto_detect = false`. | Any key that merely happens to be unset. |
| Candidate | A value produced by detection for a user-judgment key. Never the key's value. | A default. A candidate is never applied on silence. |
| Confirmation | An explicit human decision accepting a candidate or supplying a replacement. | Persistence. Writing a candidate to disk is not confirming it. |
| Propose | Produce and display a candidate. Gated by `allow_sieve_hints`. | Conclude. |
| Conclude | Settle the key's value without a person. Gated by `auto_detect`. | Propose. |
| Origin | How a candidate was produced (file read, detection method, model). Carried with the candidate. | Confidence. A high-confidence guess is still a guess. |

## Value lifecycle

```text
                    (no value)
                        |
        detection runs  |  gated by allow_sieve_hints
                        v
                    CANDIDATE  --------- ignored / never answered --------.
                        |                                                 |
          human confirms|  the only transition that makes a value usable  |
                        v                                                 |
                    CONFIRMED                                             |
                        |                                                 |
        configured age  |  FR-006                                         |
                        v                                                 v
                    CANDIDATE                                    key stays unverified
```

State rules the amended text must support:

1. Only CONFIRMED is usable. A key in CANDIDATE state is treated exactly as a
   key with no value at all: unverified, and unverified counts as FAIL for
   compliance (Principle II, unchanged).
2. The CANDIDATE -> CONFIRMED transition requires a person. No confidence
   value, at any threshold, substitutes for it (FR-004).
3. CONFIRMED -> CANDIDATE happens on expiry and only on expiry. A newly
   detected conflicting value does not demote a confirmation; it may surface
   the conflict for a person to resolve.
4. Confirmation does not upgrade the origin. A confirmed value records that a
   person accepted a candidate and what that candidate was based on. A later
   run must not report it as though a tool observed it directly. This is
   RFC-0001's "persistence does not launder authority."
5. There is no timeout that promotes a candidate. Silence keeps the key
   unverified indefinitely.

## Consumption paths

FR-002 names five paths. They are listed here so the amendment can be checked
sentence by sentence against them, which is what SC-003 measures.

| Path | May consume CANDIDATE | May consume CONFIRMED |
|---|---|---|
| Control verification result | No | Yes |
| Compliance calculation | No | Yes |
| Remediation action input | No | Yes |
| Generated attestation | No | Yes, recorded with its origin |
| Persisted project context | Only as a candidate, distinguishable on read | Yes |

The last row is the one most easily got wrong: a candidate may be written down,
but it must be readable as a candidate afterwards. If a later run cannot tell
the difference, persistence has laundered authority and rule 4 is broken.

## Two flags, two axes

The safety property is enforced by a pair of flags, not by a single ban. The
amendment needs to say so, because Principle IV currently reads as though
`auto_detect` alone carries the weight.

| | `allow_sieve_hints = false` | `allow_sieve_hints = true` |
|---|---|---|
| **`auto_detect = false`** | Ask the person cold. No candidate produced. | Propose a candidate, require confirmation. The case this feature legitimizes. |
| **`auto_detect = true`** | Detect and conclude without display. | Detect, conclude, and show what was found. |

Both cells in the `auto_detect = false` row are safe, because neither concludes.
The current constitutional text permits only the left cell, while the shipped
configuration uses the right one for `maintainers` and `security_contact`.
