# OpenSSF Baseline MCP - Decision Flow Diagrams

This document maps out the decision-making processes in the OpenSSF Baseline MCP server.

## Table of Contents

1. [Main Audit Flow](#main-audit-flow)
2. [Sieve Verification Flow](#sieve-verification-flow) *(NEW)*
3. [Project Context Flow](#project-context-flow) *(NEW)*
4. [Context Sieve Flow](#context-sieve-flow) *(NEW - Remediation)*
5. [Project Configuration Lifecycle](#project-configuration-lifecycle)
6. [CI Discovery](#ci-discovery)
7. [Attestation Generation](#attestation-generation)

---

## Main Audit Flow

```text
┌────────────────────────────────────────────────────────────────┐
│ audit_openssf_baseline(owner, repo, local_path, level)         │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Validate the repository path and identity                      │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Load framework rules and operator configuration                │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Read .project/ metadata and resolve context values             │
│ Reads do not create files or save discoveries                  │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Run selected controls through the sieve                        │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Calculate compliance and format the report                     │
└────────────────────────────────────────────────────────────────┘
```

Auditing does not create project configuration or save discovered values.
Unconfirmed candidates remain pending until the person confirms them.

---

## Sieve Verification Flow

The sieve system implements a 4-phase progressive verification pipeline. Each control is defined with multiple "passes" that run in order, stopping as soon as a conclusive result (PASS or FAIL) is reached.

### 2.1 Control Verification Pipeline

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SieveOrchestrator.verify(control_spec)                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │  For each pass in control.passes │
                    │  (ordered: DET → PAT → LLM → MAN)│
                    └─────────────────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
              ▼                       ▼                       ▼
    ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
    │ DETERMINISTIC   │     │    PATTERN      │     │      LLM        │
    │                 │     │                 │     │                 │
    │ • file_exists   │     │ • regex match   │     │ • prompt LLM    │
    │ • API boolean   │     │ • content scan  │     │ • parse response│
    │ • config lookup │     │ • multi-file    │     │ • confidence    │
    └─────────────────┘     └─────────────────┘     └─────────────────┘
              │                       │                       │
              ▼                       ▼                       ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                      PassResult.outcome                          │
    │                                                                  │
    │  ┌─────────┐    ┌─────────┐    ┌─────────────┐    ┌─────────┐   │
    │  │  PASS   │    │  FAIL   │    │ INCONCLUSIVE│    │  ERROR  │   │
    │  └────┬────┘    └────┬────┘    └──────┬──────┘    └────┬────┘   │
    │       │              │                │                │        │
    │       ▼              ▼                ▼                ▼        │
    │   Return         Return          Continue to       Return      │
    │   "PASS"         "FAIL"          next pass         "ERROR"     │
    └─────────────────────────────────────────────────────────────────┘
                                      │
                         (if all passes INCONCLUSIVE)
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │           MANUAL Pass            │
                    │                                  │
                    │  Returns "WARN" with list of    │
                    │  human verification steps        │
                    └─────────────────────────────────┘
```

### 2.2 Pass Type Details

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PASS TYPES                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ DeterministicPass                                                      │  │
│  │ ──────────────────                                                     │  │
│  │ file_exists: ["SECURITY.md", ".github/SECURITY.md"]                   │  │
│  │ exec: { command = [...], expr = 'output.json.key == true' }           │  │
│  │ handler: "my_module:my_func"  (custom plugin handler)                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ PatternPass                                                            │  │
│  │ ───────────                                                            │  │
│  │ file_patterns: ["SECURITY.md", "README.md"]                           │  │
│  │ content_patterns: {"contact": r"(email|security.*contact)"}           │  │
│  │ expr: 'output.any_match'  (CEL expression for pass/fail)             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ LLMPass                                                                │  │
│  │ ───────                                                                │  │
│  │ prompt_template: "Analyze if this SECURITY.md provides..."            │  │
│  │ files_to_include: ["SECURITY.md"]  (content passed to LLM)            │  │
│  │ analysis_hints: ["Look for email", "Check disclosure process"]        │  │
│  │ confidence_threshold: 0.8  (below this → INCONCLUSIVE)                │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ ManualPass                                                             │  │
│  │ ──────────                                                             │  │
│  │ verification_steps: [                                                  │  │
│  │   "Open SECURITY.md and verify contact method exists",                 │  │
│  │   "Confirm the contact is actively monitored"                          │  │
│  │ ]                                                                      │  │
│  │ verification_docs_url: "https://baseline.openssf.org/..."             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Evidence Accumulation

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Evidence Flows Through Passes                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Pass 1 (DET)                 Pass 2 (PAT)                 Pass 3 (LLM)    │
│   ┌───────────┐                ┌───────────┐                ┌───────────┐   │
│   │ evidence: │                │ evidence: │                │ evidence: │   │
│   │  file_found│ ──────────►   │  file_found│ ──────────►   │  file_found│   │
│   │           │                │  patterns  │                │  patterns  │   │
│   │           │                │  _matched  │                │  _matched  │   │
│   │           │                │           │                │  llm_reason│   │
│   └───────────┘                └───────────┘                └───────────┘   │
│                                                                              │
│   context.gathered_evidence accumulates across passes                        │
│   Final SieveResult.evidence contains all gathered evidence                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Project Context Flow

The project context system allows users to confirm facts about their project that affect how controls are evaluated. This handles cases where automatic detection is ambiguous.

> **Current rules (feature 042).** The diagrams in this section and the next predate the framework TOML and are kept for their decision logic. The authoritative rules are in `docs/architecture/framework-design.md` section 7. In short: every key resolves (`darnit.config.context_resolve.resolve_context`) to one standing, `confirmed`, `concluded` (an `auto_detect = true` key detected in this run, never persisted), `candidate`, or `unknown`. Checks, remediation, and attestations read only confirmed and concluded values. A value stored in `.project/` without a matching confirmation record is a candidate. Reads never write; only `confirm_project_data` (on a person's explicit instruction) and answers a person types into `darnit run` record confirmations.

### 3.1 Context Resolution

```text
┌────────────────────────────────────────────────────────────────┐
│ resolve_context(local_path, definitions)                       │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Read stored values, confirmation records,                      │
│ and current detection results                                  │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Assign each key a standing:                                    │
│ confirmed, concluded, candidate, or unknown                    │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ usable(): confirmed + concluded auto-detect values             │
│ get_pending_data(): relevant candidates + unknown values       │
└────────────────────────────────────────────────────────────────┘
```

A value entered by hand in `.project/` is not automatically confirmed.
`confirm_project_data` records an explicit answer for the named repository.

### 3.2 Context Keys & Affected Controls

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONTEXT_KEYS Registry                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Context Key          │ Type    │ Affects Controls                          │
│  ─────────────────────┼─────────┼──────────────────────────────────────────  │
│  has_subprojects      │ bool    │ OSPS-QA-04.01, OSPS-QA-04.02              │
│  has_releases         │ bool    │ OSPS-BR-02.01, BR-04.01, BR-06.01,        │
│                       │         │ OSPS-DO-01.01, DO-03.01                   │
│  is_library           │ bool    │ OSPS-SA-02.01                             │
│  has_compiled_assets  │ bool    │ OSPS-QA-02.02                             │
│  ci_provider          │ string  │ OSPS-BR-01.01, BR-01.02, AC-04.01,        │
│                       │         │ AC-04.02, QA-06.01, VM-05.02,             │
│                       │         │ VM-05.03, VM-06.02                        │
│  ci_config_path       │ string  │ (same as ci_provider)                     │
│                                                                              │
│  Valid ci_provider values:                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ "github" │ "gitlab" │ "jenkins" │ "circleci" │ "azure" │ "travis"  │    │
│  │ "none"   │ "other"                                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 CI Provider Context

```text
┌────────────────────────────────────────────────────────────────┐
│ Read CI files and resolve context values                       │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Use confirmed values or concluded auto-detect values           │
│ Keep unconfirmed values as candidates                          │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Evaluate the control using the available evidence              │
│ A tool name in a workflow does not prove its checks pass       │
└────────────────────────────────────────────────────────────────┘
```

CI files provide evidence about the provider and configured tools. Context values
are read through `resolve_context()`; checks use only confirmed values or values
concluded by an `auto_detect = true` key in the current run. Finding a tool name
in a workflow is evidence, not proof that its checks pass.

### 3.4 Confirming Project Context

Use the MCP tools instead of editing a legacy TOML context section:

```text
┌────────────────────────────────────────────────────────────────┐
│ get_pending_data(local_path=..., owner=..., repo=...)          │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Show questions and unconfirmed candidates to the person        │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Person answers or explicitly accepts a candidate               │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ confirm_project_data(local_path=..., owner=..., repo=...)      │
│ Record only the answers the person provided                    │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Call get_pending_data again for the next batch                 │
│ Repeat until no questions remain                               │
└────────────────────────────────────────────────────────────────┘
```

For example, after the person explicitly says the project has no subprojects:

```python
confirm_project_data(
    local_path="/path/to/repo",
    owner="example",
    repo="project",
    has_subprojects=False,
)
```

Confirmations are stored in `.project/darnit.yaml` for a trusted repository,
otherwise in operator-side storage. Reads never write.

---

## Context Sieve Flow

The Context Sieve provides progressive auto-detection of project context (maintainers, security contacts, governance model) for remediation. It runs cheap/fast checks first and stops when confidence is sufficient.

For a user-judgment key (`auto_detect = false`, which includes `maintainers`, `security_contact`, and `governance_model` in OpenSSF Baseline), a detection only proposes a candidate, whatever its confidence; only a person's confirmation makes the value usable. Confidence thresholds apply only to `auto_detect = true` keys.

### 4.1 Context Sieve Pipeline

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ContextSieve.detect(key, local_path, owner, repo)         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │  Phase 1: DETERMINISTIC          │
                    │  (High confidence: 0.9)          │
                    │                                  │
                    │  • MAINTAINERS.md parsing        │
                    │  • CODEOWNERS file extraction    │
                    │  • SECURITY.md email detection   │
                    │  • GOVERNANCE.md model keywords  │
                    └─────────────────────────────────┘
                                      │
                           ┌──────────┴──────────┐
                           │                     │
                           ▼                     ▼
                   [Signals Found]         [No Signals]
                           │                     │
                           ▼                     │
              ┌─────────────────────┐            │
              │ confidence >= 0.9?  │            │
              └─────────────────────┘            │
                           │                     │
                   ┌───────┴───────┐             │
                   ▼               ▼             │
                [Yes]            [No]            │
                   │               │             │
                   ▼               └──────┬──────┘
          Return early                   │
          (high confidence)              ▼
                              ┌─────────────────────────────────┐
                              │  Phase 2: HEURISTIC              │
                              │  (Medium confidence: 0.7-0.8)    │
                              │                                  │
                              │  • package.json author/contribs  │
                              │  • pyproject.toml authors        │
                              │  • Git commit top contributors   │
                              │  • README.md author mentions     │
                              └─────────────────────────────────┘
                                              │
                                   ┌──────────┴──────────┐
                                   │                     │
                                   ▼                     ▼
                           [Signals Found]         [No Signals]
                                   │                     │
                                   ▼                     │
                  ┌─────────────────────┐                │
                  │ confidence >= 0.7?  │                │
                  └─────────────────────┘                │
                                   │                     │
                           ┌───────┴───────┐             │
                           ▼               ▼             │
                        [Yes]            [No]            │
                           │               │             │
                           ▼               └──────┬──────┘
                  Return early                   │
                  (good enough)                  ▼
                              ┌─────────────────────────────────┐
                              │  Phase 3: API                    │
                              │  (Lower confidence: 0.6-0.7)     │
                              │                                  │
                              │  • GitHub collaborators API      │
                              │    (admin/maintain roles)        │
                              │  • GitHub security policy        │
                              │  • Organization membership       │
                              │                                  │
                              │  (Requires owner/repo params)    │
                              └─────────────────────────────────┘
                                              │
                                              ▼
                              ┌─────────────────────────────────┐
                              │  Phase 4: COMBINE SIGNALS        │
                              │                                  │
                              │  • Aggregate all signals         │
                              │  • Calculate agreement factor    │
                              │  • Apply agreement boost/penalty │
                              │  • Return best value with        │
                              │    provenance                    │
                              └─────────────────────────────────┘
                                              │
                                              ▼
                              ┌─────────────────────────────────┐
                              │  ContextDetectionResult          │
                              │                                  │
                              │  • key: "maintainers"            │
                              │  • value: ["@alice", "@bob"]     │
                              │  • confidence: 0.78              │
                              │  • signals: [ContextSignal...]   │
                              │  • needs_confirmation: bool      │
                              └─────────────────────────────────┘
```

### 4.2 Signal Source Weights

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SIGNAL SOURCE WEIGHTS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Source               │ Weight │ Rationale                                   │
│  ─────────────────────┼────────┼─────────────────────────────────────────────│
│  USER_CONFIRMED       │  1.0   │ User explicitly confirmed via MCP tool      │
│  EXPLICIT_FILE        │  0.9   │ Dedicated files (MAINTAINERS.md) are        │
│                       │        │ authoritative                               │
│  PROJECT_MANIFEST     │  0.8   │ Package files (package.json) usually        │
│                       │        │ accurate                                    │
│  GITHUB_API           │  0.7   │ API data may include inactive contributors  │
│  GIT_HISTORY          │  0.6   │ Commit count doesn't equal maintainership   │
│  PATTERN_MATCH        │  0.5   │ Heuristic matching, may have false          │
│                       │        │ positives                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Confidence Calculation

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                      CONFIDENCE CALCULATION ALGORITHM                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Input: List[ContextSignal]                                                  │
│                                                                              │
│  Step 1: Calculate weighted confidence for each signal                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  weighted_conf = signal.raw_confidence × SIGNAL_WEIGHTS[signal.source]  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Step 2: Calculate agreement factor (do signals agree?)                      │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  agreement = overlap(signal_values) / total_unique_values               │ │
│  │                                                                         │ │
│  │  • All agree (same values):     agreement = 1.0                         │ │
│  │  • Partial overlap:             agreement = 0.5-0.9                     │ │
│  │  • Complete disagreement:       agreement = 0.0                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Step 3: Apply agreement boost/penalty                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  • Multiple signals agree:      boost = 1.2                             │ │
│  │  • Single signal:               boost = 1.0                             │ │
│  │  • Signals conflict:            boost = 0.8                             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Step 4: Final confidence                                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  final_confidence = weighted_avg × agreement_factor × boost             │ │
│  │  final_confidence = min(1.0, final_confidence)  # Cap at 1.0            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.4 Integration with Context Validator

```text
check_context_requirements(requirements, local_path, owner, repo)
  |
  +-- resolve_context(local_path)          (reads only; writes nothing)
  |
  +-- for each requirement { key, required, confidence_threshold,
  |                          prompt_if_auto_detected }:
        |
        +-- standing = confirmed  -> ready (unless the value only names
        |                            one of the key's hint_sources files)
        +-- standing = concluded  -> ready, unless prompt_if_auto_detected
        |                            is set or confidence < threshold
        +-- standing = candidate  -> not ready; the candidate is shown as
        |                            labelled, unconfirmed data with its
        |                            origin and digest
        +-- standing = unknown    -> not ready; ask the person
```

Independently of `requires_context`, a remediation template or `when` clause that reads a key without a usable value stops that control with `confirmation required: <key>` and writes nothing.

### 4.5 Supported Context Keys

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                      SUPPORTED CONTEXT DETECTION KEYS                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Key              │ Deterministic        │ Heuristic       │ API            │
│  ─────────────────┼──────────────────────┼─────────────────┼────────────────│
│  maintainers      │ MAINTAINERS.md       │ package.json    │ GitHub         │
│                   │ CODEOWNERS           │ pyproject.toml  │ collaborators  │
│                   │                      │ Git top commits │                │
│  ─────────────────┼──────────────────────┼─────────────────┼────────────────│
│  security_contact │ SECURITY.md email    │ README security │ GitHub         │
│                   │ extraction           │ section         │ security       │
│                   │                      │                 │ policy         │
│  ─────────────────┼──────────────────────┼─────────────────┼────────────────│
│  governance_model │ GOVERNANCE.md        │ README gov      │ -              │
│                   │ keyword detection    │ section         │                │
│                   │ (committee, bdfl,    │                 │                │
│                   │  foundation, etc.)   │                 │                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.6 Example: Maintainers Detection

```text
detect("maintainers", "/path/to/repo")

Phase 1 (Deterministic):
  .github/CODEOWNERS found: "* @alice @bob"
  signal { source: EXPLICIT_FILE, value: ["@alice", "@bob"], raw_confidence: 0.95 }
  confidence = 0.95 x 0.9 (EXPLICIT_FILE weight) = 0.855

Phase 2 (Heuristic):
  package.json author "Alice Smith"
  signal { source: PROJECT_MANIFEST, value: ["alice"], raw_confidence: 0.8 }

Phase 4 (Combine):
  result { value: ["@alice", "@bob"], confidence: 0.67, signals: [...] }

Standing: candidate (origin sieve_hint, method CODEOWNERS). maintainers is a
user-judgment key, so this holds at any confidence.
```

`get_pending_data` shows the candidate as data, never inside a command:

```json
{
  "key": "maintainers",
  "candidate": {
    "value": ["@alice", "@bob"],
    "origin": {"kind": "sieve_hint", "method": "CODEOWNERS", "confidence": 0.67},
    "digest": "sha256:...",
    "label": "UNCONFIRMED candidate - show it to the person; do not confirm without their answer"
  },
  "command_template": "confirm_project_data(accept_candidates={\"maintainers\": \"<candidate digest if the person accepts it>\"}, owner=..., repo=...)  OR  confirm_project_data(maintainers=<the person's answer>, owner=..., repo=...)"
}
```

Only after the person accepts does the agent fill in the digest; the confirmation records who, when, and the candidate it was based on.

---

## Project Configuration Lifecycle

### 5.1 Loading Project Configuration

```text
┌────────────────────────────────────────────────────────────────┐
│ load_project_config_checked(local_path)                        │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Read .project/project.yaml: standard project metadata          │
│ Read .project/darnit.yaml: DARNIT context and claims           │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Validate each file independently                               │
│ Report absent, valid, or invalid; do not write files           │
└────────────────────────────────────────────────────────────────┘
```

`load_project_config()` provides the combined project configuration for readers.
It does not create files or save discoveries.

### 5.2 Writing Project Data

```text
┌────────────────────────────────────────────────────────────────┐
│ Person explicitly confirms project data                        │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ confirm_project_data → config/context_writes.py                │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Validate project files                                         │
│ If either file is invalid: refuse the write                    │
└────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Trusted repository: write to .project/darnit.yaml              │
│ Otherwise: store the confirmation operator-side                │
└────────────────────────────────────────────────────────────────┘
```

Context confirmations go through `confirm_project_data` and
`config/context_writes.py`. Writers refuse invalid project files instead of
replacing them. Applied remediation can record a document reference when its
`file_create` step declares `project_reference`; reading or auditing alone does
not sync discovered files into the configuration.

---

## CI Discovery

### 6.1 Provider Detection

```text
┌──────────────────────────────────────────────────────────────────┐
│                   discover_ci_config(local_path)                  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │     Check for CI indicators       │
              └───────────────────────────────────┘
                              │
    ┌─────────────────────────┼─────────────────────────┐
    │           │             │             │           │
    ▼           ▼             ▼             ▼           ▼
.github/    .gitlab-      .circleci/   Jenkinsfile  .travis.yml
workflows/   ci.yml       config.yml                    │
    │           │             │             │           │
    ▼           ▼             ▼             ▼           ▼
"github"    "gitlab"     "circleci"    "jenkins"    "travis"
    │           │             │             │           │
    └───────────┴─────────────┴─────────────┴───────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │  Set provider in ci_config        │
              └───────────────────────────────────┘
```

### 6.2 GitHub Capability Detection

```text
┌──────────────────────────────────────────────────────────────────┐
│              For each workflow in .github/workflows/              │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │      Read workflow YAML content    │
              │      (as text, pattern matching)   │
              └───────────────────────────────────┘
                              │
    ┌─────────────────────────┼─────────────────────────┐
    │                         │                         │
    ▼                         ▼                         ▼
┌─────────────┐       ┌─────────────┐          ┌─────────────┐
│   Testing   │       │   Security  │          │   Quality   │
│  Detection  │       │  Scanning   │          │   Checks    │
└─────────────┘       └─────────────┘          └─────────────┘
    │                         │                         │
    ▼                         ▼                         ▼
pytest, jest,         codeql, snyk,            eslint, pylint,
mocha, npm test,      trivy, semgrep,          ruff, black,
yarn test, go test    sonarqube, bandit        prettier, rubocop
    │                         │                         │
    ▼                         ▼                         ▼
ci_config["testing"]  ci_config                ci_config
  .append(path)       ["security_scanning"]    ["code_quality"]
                        .append(path)            .append(path)


┌─────────────────────────────────────────────────────────────────────────────┐
│                     Additional Capability Detection                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Contributor Verification:                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  .github/dco.yml exists?  ──► contributor_verification = "dco"      │    │
│  │  Workflow contains "dco" or "signed-off-by"? ──► type = "dco"       │    │
│  │  Workflow contains "cla" (not "class")? ──► type = "cla"            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Dependency Management:                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  .github/dependabot.yml exists? ──► Parse ecosystems list           │    │
│  │  renovate.json exists? ──► dependency_management = path             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Release Automation:                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Workflow name in ["release", "publish", "deploy"]?                  │    │
│  │  ──► release_automation = workflow_path                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Capability → OSPS Control Mapping

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Capability-Based Naming → OSPS Controls                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CI Capability                │  OSPS Control(s)                             │
│  ─────────────────────────────┼──────────────────────────────────────────    │
│  contributor_verification     │  OSPS-LE-01.01 (DCO/CLA enforcement)         │
│  testing                      │  OSPS-QA-06.01 (Automated tests)             │
│  code_quality                 │  OSPS-QA-02.* (Linting/formatting)           │
│  security_scanning            │  OSPS-QA-04.* (SAST/security scans)          │
│  dependency_management        │  OSPS-VM-05.* (SCA/dependency updates)       │
│  release_automation           │  OSPS-BR-01.* (CI/CD pipelines)              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.4 Non-GitHub CI Provider Handling

For projects not using GitHub Actions, CI-related controls use project context and manual verification.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Non-GitHub CI Provider Decision Flow                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │  Check project.context.ci_provider │
                    └─────────────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
        ▼                             ▼                             ▼
   [Not Set]                    [ci_provider=                  [ci_provider=
        │                        "none"]                       "gitlab"|
        │                             │                        "jenkins"|...]
        ▼                             │                             │
┌───────────────┐                     │                             ▼
│ Check for     │                     │              ┌─────────────────────────┐
│ CI config     │                     │              │ Look for provider's     │
│ files:        │                     │              │ config file:            │
│               │                     │              │                         │
│ .gitlab-ci.yml│                     │              │ gitlab → .gitlab-ci.yml │
│ Jenkinsfile   │                     │              │ jenkins → Jenkinsfile   │
│ .circleci/    │                     │              │ circleci → .circleci/   │
│ azure-pipes   │                     │              │ azure → azure-pipelines │
│ .travis.yml   │                     │              │ travis → .travis.yml    │
└───────────────┘                     │              └─────────────────────────┘
        │                             │                             │
        ▼                             ▼                             ▼
  ┌──────────┐                  ┌──────────┐                 ┌──────────┐
  │ Config   │                  │ N/A for  │                 │ Config   │
  │ found?   │                  │ CI-based │                 │ found?   │
  └──────────┘                  │ controls │                 └──────────┘
        │                       └──────────┘                        │
   ┌────┴────┐                                                ┌────┴────┐
   │         │                                                │         │
   ▼         ▼                                                ▼         ▼
 [Yes]      [No]                                           [Yes]      [No]
   │         │                                                │         │
   ▼         ▼                                                │         │
Infer   INCONCLUSIVE:                                         │         │
provider  "Confirm CI                                         │         │
from      provider in                                         │         │
file      MCP tools"                                          │         │
   │                                                          │         │
   └──────────────────────────────────────────────────────────┘         │
                              │                                         │
                              ▼                                         │
                ┌─────────────────────────────────┐                     │
                │ Basic pattern matching:          │                     │
                │ Look for SAST/test/lint tools    │                     │
                │ in config file content           │                     │
                └─────────────────────────────────┘                     │
                              │                                         │
                    ┌─────────┴─────────┐                               │
                    │                   │                               │
                    ▼                   ▼                               ▼
             [Patterns Match]    [No Clear Match]                WARN: "Manual
                    │                   │                         verification
                    ▼                   ▼                         required"
               PASS with         WARN: "Manual
               evidence          verification
                                 required"
```

### 6.5 CI Provider Configuration Reference

CI references belong in `.project/darnit.yaml`, not `project.toml`:

```yaml
ci:
  provider: gitlab
  workflows:
    - .gitlab-ci.yml
  testing:
    - .gitlab-ci.yml
  security_scanning:
    - .gitlab-ci.yml
```

These are configuration references, not confirmation records or proof of a
successful CI run. Confirm context answers through `confirm_project_data`.

---

## Attestation Generation

### 7.1 Main Attestation Flow

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         generate_attestation()                               │
│            (owner, repo, local_path, level, sign, output_dir)               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │   Validate & Resolve local_path  │
                    │   Get git commit SHA             │
                    │   Get git ref (branch/tag)       │
                    └─────────────────────────────────┘
                                      │
                           ┌──────────┴──────────┐
                           │                     │
                           ▼                     ▼
                    [Commit Found]         [No Commit]
                           │                     │
                           │                     └──► Return Error
                           ▼
          ┌────────────────────────────────────────────┐
          │      Auto-detect owner/repo from git        │
          │      Read .project/ configuration           │
          └────────────────────────────────────────────┘
                           │
                           ▼
          ┌────────────────────────────────────────────┐
          │           Run Sieve Audit                   │
          │                                             │
          │   Select controls from framework TOML      │
          │   Run their configured passes             │
          │   Resolve context without writing files   │
          └────────────────────────────────────────────┘
                           │
                           ▼
          ┌────────────────────────────────────────────┐
          │     Apply Control Applicability Filters     │
          │     (project type, N/A overrides)           │
          └────────────────────────────────────────────┘
                           │
                           ▼
          ┌────────────────────────────────────────────┐
          │       Build Assessment Predicate            │
          │                                             │
          │   • assessor info (name, version)          │
          │   • timestamp                               │
          │   • baseline version                        │
          │   • repository info (url, commit, ref)     │
          │   • summary (level_achieved, pass/fail)    │
          │   • per-level compliance                    │
          │   • all control results with messages      │
          └────────────────────────────────────────────┘
                           │
                           ▼
                  ┌────────────────┐
                  │   sign=True?   │
                  └────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
           [Yes]                      [No]
              │                         │
              ▼                         ▼
    ┌─────────────────┐      ┌─────────────────────┐
    │  Sign with      │      │  Build unsigned     │
    │  Sigstore       │      │  in-toto statement  │
    │  (see 6.2)      │      │  with gitCommit     │
    └─────────────────┘      └─────────────────────┘
              │                         │
              └────────────┬────────────┘
                           │
                           ▼
          ┌────────────────────────────────────────────┐
          │          Save to output file                │
          │                                             │
          │   Default: {repo}-baseline-attestation      │
          │            .sigstore.json (signed)          │
          │            .intoto.json (unsigned)          │
          └────────────────────────────────────────────┘
```

### 7.2 Sigstore Signing Flow

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          _sign_attestation()                                 │
│              (predicate, predicate_type, subject_name, commit)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │   Create sigstore-compatible     │
                    │   subject:                       │
                    │                                  │
                    │   name: git+https://...@{commit} │
                    │   digest: sha256(commit)         │
                    └─────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │   Build statement using          │
                    │   sigstore.dsse.StatementBuilder │
                    └─────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │   Create SigningContext          │
                    │   (production or staging)        │
                    └─────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │     Get OIDC Identity Token      │
                    └─────────────────────────────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     │                                 │
                     ▼                                 ▼
          ┌──────────────────┐            ┌──────────────────┐
          │   CI Environment  │            │  Local Machine   │
          │   (GitHub Actions,│            │                  │
          │    GitLab CI...)  │            │                  │
          └──────────────────┘            └──────────────────┘
                     │                                 │
                     ▼                                 ▼
          ┌──────────────────┐            ┌──────────────────┐
          │  Ambient OIDC    │            │  Browser opens   │
          │  credentials     │            │  for OAuth flow  │
          │  auto-detected   │            │  (GitHub/Google/ │
          │                  │            │   Microsoft)     │
          └──────────────────┘            └──────────────────┘
                     │                                 │
                     └────────────────┬────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │      Sign with DSSE envelope     │
                    │      signer.sign_dsse(stmt)      │
                    └─────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │   Signature recorded in Rekor    │
                    │   transparency log               │
                    └─────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │   Return signed bundle           │
                    │   (.sigstore.json)               │
                    └─────────────────────────────────┘
```

### 7.3 Subject Format Differences

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Signed vs Unsigned Subject Format                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  UNSIGNED (in-toto native format):                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  "subject": [{                                                         │ │
│  │    "name": "git+https://github.com/owner/repo",                        │ │
│  │    "digest": {                                                         │ │
│  │      "gitCommit": "abc123def456789..."   ◄── Git commit SHA directly   │ │
│  │    }                                                                   │ │
│  │  }]                                                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  SIGNED (sigstore-compatible format):                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  "subject": [{                                                         │ │
│  │    "name": "git+https://github.com/owner/repo@abc123def...",           │ │
│  │                                              ▲                         │ │
│  │                                              │                         │ │
│  │                              Commit included in name                   │ │
│  │    "digest": {                                                         │ │
│  │      "sha256": "5a28927f..."   ◄── sha256(commit) for sigstore        │ │
│  │    }                                                                   │ │
│  │  }]                                                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Why the difference?                                                         │
│  • Sigstore only accepts standard hash algorithms (sha256, sha384, sha512)  │
│  • gitCommit is valid in-toto but not supported by sigstore's DSSE impl    │
│  • Commit SHA is preserved in subject name AND in predicate.repository     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.4 Attestation Verification

**Note:** `cosign verify-blob-attestation` does not work for these attestations because
there is no external blob being attested - the DSSE envelope contains the statement itself.
Use the provided verification script instead.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Attestation Verification                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SIGNED ATTESTATIONS (using verify-attestation.sh):                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  # Basic verification                                                  │ │
│  │  ./scripts/verify-attestation.sh my-repo-baseline-attestation.sigstore.json │
│  │                                                                        │ │
│  │  # With expected signer identity                                       │ │
│  │  ./scripts/verify-attestation.sh attestation.sigstore.json user@example.com │
│  │                                                                        │ │
│  │  # With expected identity and issuer                                   │ │
│  │  ./scripts/verify-attestation.sh attestation.sigstore.json \           │ │
│  │      user@example.com https://github.com/login/oauth                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  The script verifies:                                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  1. DSSE signature (PAE reconstruction + public key verification)     │ │
│  │  2. Certificate identity and OIDC issuer                              │ │
│  │  3. Certificate timestamps                                             │ │
│  │  4. Rekor transparency log entry (confirms public logging)            │ │
│  │  5. RFC 3161 timestamps (if present)                                  │ │
│  │  6. Displays attestation content summary                              │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Requirements: jq, openssl, curl, base64                                     │
│                                                                              │
│  OIDC Issuers:                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Provider          │  Issuer URL                                       │ │
│  │  ─────────────────────────────────────────────────────────────────────  │ │
│  │  Google            │  https://accounts.google.com                      │ │
│  │  GitHub            │  https://github.com/login/oauth                   │ │
│  │  Microsoft         │  https://login.microsoftonline.com                │ │
│  │  GitHub Actions    │  https://token.actions.githubusercontent.com      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  UNSIGNED ATTESTATIONS (manual verification):                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  1. Validate JSON schema                                               │ │
│  │  2. Check subject.digest.gitCommit matches repo HEAD                   │ │
│  │  3. Verify predicate.repository.url matches expected repo              │ │
│  │  4. Inspect predicate.controls for pass/fail details                   │ │
│  │  5. Re-run audit and compare results (optional)                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.5 Attestation Predicate Structure

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│            Assessment Predicate (https://openssf.org/baseline/assessment/v1)│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  {                                                                           │
│    "assessor": {                                                             │
│      "name": "openssf-baseline",                                            │
│      "version": "0.1.1",                                                    │
│      "uri": "https://github.com/darnitdevorg/darnit"                        │
│    },                                                                        │
│    "timestamp": "2024-11-30T12:00:00Z",                                     │
│    "baseline": {                                                             │
│      "version": "2026.02.19",                                               │
│      "specification": "https://baseline.openssf.org/versions/2026-02-19"    │
│    },                                                                        │
│    "repository": {                                                           │
│      "url": "https://github.com/owner/repo",                                │
│      "commit": "abc123...",                                                 │
│      "ref": "main"                      ◄── branch or tag                   │
│    },                                                                        │
│    "configuration": {                                                        │
│      "project_type": "software",                                            │
│      "excluded_controls": ["OSPS-BR-02.01"]                                │
│    },                                                                        │
│    "summary": {                                                              │
│      "level_assessed": 3,                                                   │
│      "level_achieved": 1,               ◄── Highest fully-passing level    │
│      "total_controls": 65,                                                  │
│      "passed": 45,                                                          │
│      "failed": 15,                                                          │
│      "warnings": 3,                                                         │
│      "not_applicable": 2,                                                   │
│      "errors": 0                                                            │
│    },                                                                        │
│    "levels": {                          ◄── Per-level breakdown             │
│      "1": { "total": 24, "passed": 24, "failed": 0, "compliant": true },    │
│      "2": { "total": 18, "passed": 15, "failed": 3, "compliant": false },   │
│      "3": { "total": 23, "passed": 6,  "failed": 12, "compliant": false }   │
│    },                                                                        │
│    "controls": [                        ◄── Every single check result       │
│      {                                                                       │
│        "id": "OSPS-AC-03.01",                                               │
│        "level": 1,                                                          │
│        "category": "AC",                                                    │
│        "status": "PASS",                                                    │
│        "message": "Branch protection enabled on main",                      │
│        "source": "builtin"                                                  │
│      },                                                                      │
│      ...                                                                     │
│    ]                                                                         │
│  }                                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Configuration Files Summary

```text
┌────────────────────────────────────────────────────────────────┐
│ .project/project.yaml                                          │
│ Standard project metadata and document references              │
│ Written by project authors or declared remediation updates     │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ .project/darnit.yaml                                           │
│ DARNIT context, confirmations, and control claims              │
│ Written by explicit confirmations for trusted repositories     │
│ or declared remediation updates                                │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ ~/.config/darnit/config.toml                                   │
│ Operator settings, trust, plugins, and control overrides       │
│ Written by the operator                                        │
└────────────────────────────────────────────────────────────────┘
```

An audit reads these files without syncing discoveries back into them. Repository
content cannot override operator settings. `.baseline.toml` is no longer read;
use `darnit config migrate` to migrate old configuration.

---

## Quick Reference: Key Functions

### Main Audit Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `audit_openssf_baseline()` | `darnit_baseline/tools.py` | Main entry point for audits |
| `load_project_config()` | `darnit/config/loader.py` | Read project configuration from `.project/` |
| `discover_ci_config()` | `darnit/config/discovery.py` | Discover CI configuration without writing it |

### Sieve System Functions

| Function/Class | Location | Purpose |
|----------------|----------|---------|
| `SieveOrchestrator` | sieve/orchestrator.py | Runs 4-phase verification pipeline |
| `SieveOrchestrator.verify()` | sieve/orchestrator.py | Verify single control through passes |
| `ControlRegistry` | sieve/registry.py | Registry of control specifications |
| `get_control_registry()` | sieve/registry.py | Get global control registry |
| `ControlSpec` | sieve/models.py | Control definition with passes |
| `PassResult` | sieve/models.py | Result from a single pass |
| `SieveResult` | sieve/models.py | Final verification result |
| `CheckContext` | sieve/models.py | Context for check execution |

### Project Context Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `resolve_context()` | config/context_resolve.py | Every key's value and standing; `usable()` is the only mapping consumers read |
| `get_pending_data()` | `darnit_baseline/tools.py` | MCP tool for pending questions and unconfirmed candidates |
| `get_pending_context()` | `darnit/config/context_storage.py` | Internal read-only helper used by the MCP tool |
| `confirm_project_data()` | `darnit_baseline/tools.py` | MCP tool to record a person's explicit answers |
| `context_writes` | config/context_writes.py | The only writer of context values and confirmation records |
| `[context.*]` | framework TOML | Context keys, vocabularies, and affected controls |
