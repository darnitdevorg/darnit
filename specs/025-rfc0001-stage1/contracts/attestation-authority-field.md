# Contract: `authority` field in the OpenSSF Baseline attestation predicate

**Feature**: 025-rfc0001-stage1
**Date**: 2026-08-05

Stage 1 adds an `authority` field to per-result entries in the existing attestation predicate. Per Q2 clarification, this is an ADDITIVE change within the existing predicate type; no version bump, no dual-emit.

---

## Predicate type

`https://openssf.org/baseline/assessment/v1` (unchanged).

## Field addition

Each entry in `results[]` gets an additional key:

```jsonc
{
  "results": [
    {
      "id": "OSPS-VM-01.01",
      "status": "PASS",
      "authority": "dispositive",   // <-- Stage 1 addition
      // ... other existing fields ...
    }
  ]
}
```

Authority values follow the Literal domain defined in `data-model.md`: `"dispositive"`, `"suggestive"`, `"asserted"`.

## Contract items

- **T1**: The predicate type string in the DSSE envelope does NOT change (`https://openssf.org/baseline/assessment/v1`). Verified by test.
- **T2**: Every result entry produced by Stage-1 code MUST include `authority` with a value in the declared domain. A missing or unknown value is a schema violation. SC-007 tests this.
- **T3**: Older readers that permit unknown JSON keys (the common case; JSON Schema without `additionalProperties: false`) continue to load and verify the predicate unchanged. A regression test loads a Stage-1-produced attestation with a pre-Stage-1 reader stub and asserts it verifies successfully.
- **T4**: Newer readers CAN extract `authority` and reject a PASS whose authority is not in an accept-list. FR-005 requires a test asserting this (a mock policy engine configured to accept only `dispositive` passes rejects an `asserted` pass).
- **T5**: The `authority` field appears at the RESULT level (per-control), NOT at the top of the predicate. There is no aggregate `authority_summary` object; consumers who want summary information compute it from the per-result field.
- **T6**: PASS-from-dispositive and PASS-from-asserted MUST be distinguishable at read time. This is the same statement as T2, viewed from the consumer side. Tests verify both readings.

## Non-contract items

- Signing scope. Per RFC "Signing scope," Stage 1 does not change what is signed vs. what is attestable-but-unsigned. The `authority` field is a field on the existing signed structure.
- Version bump procedure. If Stage 2 or Stage 3 needs to bump to `v2` (e.g., because a required breaking field is added), that is future work, not Stage 1.
- Third-party predicate types (Scorecard, SLSA). Stage 1 does not touch those.

## Reader-compat test spec (SC-007 concrete)

The test at `tests/darnit_baseline/attestation/test_authority_field.py` MUST:

1. Run a Stage-1 audit on the reference SECURITY.md fixture (or minimal_repo).
2. Produce an attestation via the standard baseline path.
3. Assert every `results[i].authority` is present and in the Literal domain.
4. Load the attestation with a stub reader that permits unknown keys; assert the predicate verifies (T3).
5. Load the attestation with a stub reader configured with a strict accept-list on `authority`; assert it rejects an entry whose authority is not in the accept-list (T4).
