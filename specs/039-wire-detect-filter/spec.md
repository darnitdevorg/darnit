# Feature Specification: Wire detect_filter Into Context Detection

**Feature Branch**: `039-wire-detect-filter`

**Created**: 2026-09-22

**Status**: Draft

**Input**: Issues #165 and #150 -- the `detect_filter` CEL expression declared on a context key is never evaluated.

## Context

`openssf-baseline.toml:303` declares a filter on the `security_contact` context key:

```toml
[context.security_contact]
auto_detect = true
allow_sieve_hints = true
# Filter: reject detected values containing "example.com" or "example.org"
detect_filter = "!value.contains('example.com') && !value.contains('example.org')"
```

The string `detect_filter` appears in exactly one TOML file and in **zero lines of Python**. It is not a declared field on `ContextDefinitionConfig`. Because that model sets `extra="allow"`, the value is retained in `model_extra` rather than dropped -- it is parsed and then never read by anything.

The filter exists to stop a boilerplate address in a template-generated `SECURITY.md` from being taken as the project's real security contact. That address then feeds `OSPS-VM-01.01`, `OSPS-VM-02.01` and `OSPS-VM-03.01`.

### The severity is higher than #165 recorded

#165 assessed impact as "Low -- the context collection step still asks the user to confirm, so the value isn't silently applied." There is a path where it does not ask.

`context_storage.py:556`:

```python
if current_value is not None and current_value.confidence >= auto_accept_threshold:
    current_value.auto_accepted = True
    ...
    save_context_value(local_path, key, current_value.value,
                       source=ContextSource.AUTO_DETECTED, ...)
```

`auto_accept_threshold` defaults to 0.8 and `openssf-baseline.toml:274` sets `auto_accept_confidence = 0.8`. A detect-pipeline result carrying no explicit confidence is normalized to 0.8, which meets the threshold exactly. So a detected `security@example.com` at or above 0.8 is written to `.project/` as `AUTO_DETECTED` with no prompt.

This is permitted by the constitution: `security_contact` has `auto_detect = true`, so it is not a user-judgment key and confidence-based auto-acceptance applies to it. `detect_filter` is the only thing standing between a placeholder value and the audit record, and it is not running.

### Why this keeps happening

This is the second instance of the same defect in recent memory. `value_if_fail` was likewise declared in TOML, parsed, and never read, until it was found by diagnosing a reproducibility complaint (PR #417).

`ContextDefinitionConfig` sets `extra="allow"`. Nothing rejects an undeclared key, and nothing reports one. A typo -- `detect_fliter` -- is accepted in silence and behaves exactly like the working spelling: it does nothing. The wiring fix closes one hole; it does not close the class.

## Clarifications

### Session 2026-09-23

- Q: How does the filter evaluate a list-valued key, given the shipped expression uses `value.contains(...)` and `maintainers` is `list_or_path` with `auto_detect = true`? -> A: Element-wise. Evaluate once per element, keep the elements that pass, discard the rest; a key whose elements all fail becomes unset.
- Q: What happens to values already stored in `.project/` from before this fix, given the read path does no re-validation? -> A: Re-evaluate the filter on read. A stored value that now fails is treated as unset and reported; `.project/` is not modified.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A placeholder address is not adopted as the security contact (Priority: P1)

A maintainer whose `SECURITY.md` came from a template still containing `security@example.com` runs context collection. That address is not written to their project context, and not offered to them as a candidate.

**Why this priority**: it is the case the filter was written for, and the auto-accept path means the value can reach `.project/` without anyone seeing it.

**Independent Test**: a repo whose `SECURITY.md` contains only `security@example.com`. Run context collection. Nothing is stored for `security_contact`.

**Acceptance Scenarios**:

1. **Given** a repo whose only security contact evidence contains `example.com`, **When** context collection runs, **Then** no value is stored for `security_contact` and none is auto-accepted.
2. **Given** the same repo, **When** context collection runs, **Then** the rejected value is not presented to the user as a candidate.
3. **Given** a repo whose `SECURITY.md` contains a real address, **When** context collection runs, **Then** behaviour is unchanged from today.

---

### User Story 2 - A filter that cannot run is visible rather than silent (Priority: P1)

An operator or framework author whose `detect_filter` expression is malformed learns that it did not run, instead of getting the same outcome as having no filter at all.

**Why this priority**: the bug being fixed is precisely "a guard that is not running looks identical to no guard." Replacing one silent no-op with another would repeat it.

**Independent Test**: define a context key with a syntactically invalid `detect_filter`. Run detection. The failure is reported.

**Acceptance Scenarios**:

1. **Given** a `detect_filter` that fails to compile, **When** detection runs for that key, **Then** the failure is logged at a level visible by default, naming the key and the expression.
2. **Given** a `detect_filter` that raises at evaluation time for a particular value, **When** that value is evaluated, **Then** the failure is logged and the value is handled per FR-006.

---

### User Story 3 - An undeclared context key is caught, not accepted in silence (Priority: P2)

A framework author who misspells a context field gets told, rather than shipping a setting that does nothing.

**Why this priority**: this is the recurrence guard. It is lower priority only because the immediate hole is closed by Stories 1 and 2; it is the part that stops a third instance.

**Independent Test**: add an undeclared key to a `[context.*]` block in a shipped TOML. Validation fails, naming the key.

**Acceptance Scenarios**:

1. **Given** a shipped framework TOML containing a `[context.*]` key not declared on the schema, **When** the repository's validation runs, **Then** it fails and names the offending key and file.
2. **Given** shipped TOMLs whose context keys are all declared, **When** validation runs, **Then** it passes.

---

### Edge Cases

- **Non-string detected values**: `detect_filter` uses `value.contains(...)`, which assumes a string. Resolved for lists: filtering is element-wise (FR-012). Note that a list bound whole does NOT error -- CEL's `contains` on a list is membership rather than substring, so the expression returns true and keeps a list containing the very value it was written to reject. That is a guard failing open, and it is why FR-012 binds scalars only. A boolean- or number-valued key does fail at evaluation time and is governed by FR-006.
- **A filter on a key with no detection configured**: harmless but pointless. Worth surfacing as a config smell rather than an error.
- **Both detection routes**: a key can be resolved by the TOML `detect` pipeline or by the hardcoded Python sieve fallback (`context_storage.py:548-553`). A filter that applies to one and not the other would be a guard with a hole in it.
- **Auto-accept ordering**: filtering must happen before the confidence threshold is consulted, or a rejected value can still be written.
- **An empty string or `None` result**: distinguish "detection found nothing" from "detection found something the filter rejected", because the second is worth telling the user about and the first is not.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `detect_filter` MUST be a declared field on the context definition schema rather than an undeclared extra.
- **FR-002**: When a context key declares `detect_filter`, the expression MUST be evaluated against each detected value for that key before the value is used for anything.
- **FR-003**: A value for which the filter evaluates false MUST be discarded: not stored, not auto-accepted, and not offered to the user as a candidate.
- **FR-004**: Filtering MUST apply to values produced by the TOML `detect` pipeline and to values produced by the hardcoded sieve fallback. A value reaching the user or the stored context by either route MUST have passed the filter.
- **FR-005**: Filtering MUST occur before the auto-accept confidence threshold is consulted.
- **FR-006**: When the filter cannot be evaluated -- malformed expression, or a runtime error against a particular value -- the value MUST be discarded, and the failure MUST be reported per FR-007.

  Failing closed is the point. The defect being fixed is a guard that failed open, and a filter that cannot run is not evidence that the value is acceptable. Halting context collection for the key was considered and rejected: a framework author's typo would then become an outage for every user of that framework, none of whom can fix it. Discarding plus a visible report puts the cost on the author who can act on it.
- **FR-007**: A filter that fails to compile or evaluate MUST be reported at a level visible in default output, naming the context key and the expression. A guard that silently does not run is the defect being fixed.
- **FR-008**: A discarded value MUST be distinguishable in logs from "detection found nothing", so an operator can tell why a key is unset.
- **FR-014**: A value read from stored project context MUST be re-evaluated against its key's `detect_filter`. A stored value that fails is treated as unset for the purposes of control verification, compliance calculation and remediation input, and the rejection MUST be reported.

  The read path (`get_context_value`) performs no validation today, so a value auto-accepted before this fix persists indefinitely -- and the repositories most likely to hold one are exactly those audited while the guard was not running. Without this, the fix protects only repositories that have never been audited.
- **FR-015**: Re-evaluation on read MUST NOT modify stored project context. A stored value may have been placed or edited by a person, and Principle IV treats human confirmation as the thing that makes a value usable; silently rewriting that file would discard a confirmation the framework is not entitled to revoke.
- **FR-012**: For a list-valued key, the filter MUST be evaluated once per element. Elements that pass are kept, elements that fail are discarded, and a key whose elements all fail is left unset.

  Binding the whole list instead would mean a single bad entry discards every good one, and the shipped expression shape (`value.contains(...)`) would error against a list rather than filter it -- which under FR-006 empties the key silently. Element-wise is what a filter on a list means.
- **FR-013**: The number of elements discarded MUST be reported alongside the survivors, so a maintainer list that arrives shorter than the evidence suggests is explicable.
- **FR-009**: Behaviour for context keys that declare no `detect_filter` MUST be unchanged.
- **FR-010**: The repository's existing validation MUST reject a `[context.*]` block containing a key not declared on the schema, naming the key and the file. This is a check over the TOMLs shipped in this repository, run in CI.

  The schema itself keeps `extra="allow"` and continues to accept undeclared keys at load time. Tightening it to reject them would change how third-party plugin configs load, which is a behaviour change deserving its own decision rather than a side effect of this fix. The CI check catches the cases that matter here -- a misspelled or unwired field in a TOML darnit ships -- without touching what a plugin author may write.
- **FR-011**: No detected value that would have been stored before this change may be stored after it, other than values the declared filters reject.

### Key Entities

- **Context definition**: the `[context.<key>]` block declaring how a key is prompted, detected, filtered and stored.
- **Detected value**: a candidate produced by the detect pipeline or the sieve fallback, carrying a value, a confidence and a detection method.
- **Detect filter**: a CEL expression over a detected value that decides whether the candidate survives.

## Success Criteria *(mandatory)*

- **SC-001**: A repository whose only security-contact evidence contains `example.com` stores nothing for `security_contact`. Verified by fixture.
- **SC-002**: The same repository does not auto-accept that value, at any confidence including 1.0. Verified by fixture.
- **SC-003**: A repository with a real security contact stores it exactly as it does today. Verified by comparing stored context before and after the change.
- **SC-004**: A malformed `detect_filter` produces a visible report naming the key. Verified by fixture.
- **SC-009**: A repository whose stored context already contains a value the filter rejects reports that value as unset on the next audit, and its `.project/` file is byte-identical afterwards. Verified by fixture.
- **SC-008**: A list-valued key with a filter keeps its passing elements and drops the failing ones, and the count of discarded elements is reported. Verified by fixture.
- **SC-005**: Both detection routes are covered: a value from the TOML `detect` pipeline and a value from the sieve fallback are each filtered. Verified by separate fixtures.
- **SC-006**: Validation fails on a shipped TOML containing an undeclared `[context.*]` key, and passes on the current shipped TOMLs once `detect_filter` is declared.
- **SC-007**: Context keys declaring no filter produce byte-identical stored context before and after this change.

## Assumptions

- The CEL evaluator in `darnit/sieve/cel_evaluator.py` is the evaluator to use; this feature introduces no second expression language.
- `value` is the binding name the existing expression uses and is the binding this feature provides.
- Re-evaluation on read (FR-014) covers repositories audited before this fix. The accepted cost is that a filter change can retroactively unset a stored value, which is the intended direction: a value that fails its own declared filter was never one the framework should have been asserting.
- The auto-accept mechanism itself is correct and is not revisited. `security_contact` being eligible for auto-acceptance follows from `auto_detect = true`, which this feature does not change.
- A filter that cannot be evaluated discards the value rather than halting collection (FR-006). The accepted cost is that a malformed expression makes its key permanently unset until someone reads the log.
- The schema stays permissive (FR-010). Undeclared keys remain loadable; only TOMLs shipped in this repository are checked.
- `openssf-baseline.toml` is the only shipped TOML declaring a `detect_filter` today, so the blast radius of wiring it is one key in one framework.

## Dependencies

None. The CEL evaluator, the detect pipeline, and the validation script all exist.

## Out of Scope

- **Adding filters to other context keys.** This feature makes the mechanism work; deciding which keys deserve one is separate.
- **Revisiting the auto-accept threshold or which keys carry `auto_detect = true`.** Both are governed by the constitution's Principle IV and are deliberate.
- **Auditing every other TOML field for the same unwired-key defect.** `value_if_fail` and `detect_filter` are two known instances; FR-010 is the guard that would surface the rest, and acting on what it finds is follow-up work.
- **Changing how rejected candidates are surfaced to the user beyond logging.** A richer "we found this and rejected it" flow is a UX question, not a correctness one.
