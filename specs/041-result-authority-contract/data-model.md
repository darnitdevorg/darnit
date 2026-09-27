# Data Model: Result and Authority Contract

## HandlerCeiling (registered per step type)

| Field | Type | Notes |
|---|---|---|
| `handler` | str | Step type name. |
| `ceiling` | set[{pass, fail}] | Outcomes it can conclude by default. |
| `existence_ceiling` | set[{pass, fail}] or null | Ceiling when the step declares `existence = true` (presence/pattern types only). |

| Step type | ceiling | existence_ceiling |
|---|---|---|
| `file_exists` | {fail} | {pass, fail} |
| `regex` / `pattern` | {fail} | {pass, fail} |
| `exec` | {pass, fail} | -- |
| `gh_api` | {pass, fail} | -- |
| `github_branch_protection` | {pass, fail} | -- |
| `llm_eval` | {} | -- |
| `manual` | {} | -- |

## StepDeclaration (per step in a control, framework TOML)

| Field | Type | Notes |
|---|---|---|
| `handler` | str | |
| `concludes` | list[{pass, fail}] | Optional; must be a subset of the effective ceiling. |
| `existence` | bool | Presence/pattern only; the control's requirement is literally existence. |
| `fail_on_miss` | bool | Pattern only; requires `fail` in the effective set. |
| `fail_on_status` | list[int] | `gh_api` only; HTTP statuses that prove failure. |
| `promotion` | Promotion or null | Required to exceed the ceiling. |

Effective set = (`existence_ceiling` if `existence` else `ceiling`) intersected with `concludes` if given, union the promoted outcome if a promotion exists.

## Promotion

| Field | Type | Notes |
|---|---|---|
| `outcome` | "pass" | Only PASS promotions exist in this feature. |
| `corpus` | str | Corpus version the measurement came from. |
| `note` | str | Human rationale. |

Validation (load time, every control-loading path): a declared outcome outside the ceiling without a promotion is an error naming framework, control, step index, and outcome.

## Result

| Field | Type | Notes |
|---|---|---|
| `status` | enum | PASS, FAIL, WARN, N/A, ERROR, PENDING |
| `authority` | enum | dispositive, suggestive, asserted |
| `concluded_by` | str | Step handler, `llm_judgment`, `confirmation`, or `none`. |
| `error` | {class, cause} or null | Required when `status = ERROR`. |
| `pending` | {kind: llm_judgment \| confirmation} or null | Required when `status = PENDING`. |
| `candidate` | Candidate or null | Present when `pending.kind = confirmation`. |
| `confirmation` | {confirmed_by, confirmed_at, expires_at} or null | Present when a PASS came from a confirmed candidate. |
| `evidence` | list | Evidence gathered by all steps. |

Compliance (single rule, `calculate_compliance`): a level is compliant only if every applicable control is PASS or N/A (N/A per feature 040 rules). FAIL, WARN, ERROR, and PENDING are non-compliant.

## Candidate (PASS candidate)

| Field | Type | Notes |
|---|---|---|
| `verdict` | "pass" | |
| `reasoning` | str | |
| `cited_evidence` | list[str] | Verbatim excerpts, each verified present in the gathered content. |
| `model` | str | |
| `model_version` | str | |
| `evidence_digest` | str | SHA-256 over gathered content and the control's rubric. |
| `source` | enum | harness, mcp_agent |

Stored operator-side (feature 040 confirmation store, claim `pass_candidate`), keyed by repository identity, control, and evidence digest.

## State transitions (judgment-requiring control)

```
gather evidence
   |
   v
no conclusive deterministic step --> PENDING(kind=llm_judgment)
   |
   | judgment arrives (harness LLM step or MCP submit_judgment)
   v
cited evidence verified? -- no --> WARN (invalid judgment recorded)
   | yes
   +-- negative --> FAIL (authority=suggestive, concluded_by=llm_judgment)
   +-- positive --> PENDING(kind=confirmation) with candidate
                       |
                       | operator confirms (digest matches, not expired)
                       v
                     PASS (authority=asserted, confirmation block)
                       |
                       | evidence digest changes or expiry
                       v
                     PENDING(kind=llm_judgment)
model service failure at any point --> ERROR for the model step
```

## Corpus

### CorpusFixture

`tests/darnit_baseline/corpus/<fixture>/`: file tree and `labels.toml` (expected outcomes and optional recorded platform responses):

| Field | Type | Notes |
|---|---|---|
| `[fixture].description` | str | |
| `[fixture].platform` | table | Recorded platform responses keyed by API path (status + body). |
| `[labels."<control_id>"].expected` | enum | PASS, FAIL, NOT_PASS, N/A |
| `[labels."<control_id>"].why` | str | Short rationale. |

### CorpusReport

| Field | Type | Notes |
|---|---|---|
| `corpus_version` | str | Digest over fixtures and labels. |
| `rows[]` | list | One per (framework, control, step index, outcome): `correct`, `incorrect`, `false_pass`, `eligible_for_promotion`. |
| `violations[]` | list | Steps allowed to conclude PASS that produced a false PASS (fails the run). |
