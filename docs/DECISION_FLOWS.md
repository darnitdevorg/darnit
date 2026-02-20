# OpenSSF Baseline MCP - Decision Flow Diagrams

This document maps out the decision-making processes in the OpenSSF Baseline MCP server.

## Table of Contents

1. [Main Audit Flow](#main-audit-flow)
2. [Sieve Verification Flow](#sieve-verification-flow) *(NEW)*
3. [Project Context Flow](#project-context-flow) *(NEW)*
4. [Context Sieve Flow](#context-sieve-flow) *(NEW - Remediation)*
5. [Project Configuration Lifecycle](#project-configuration-lifecycle)
6. [Adapter Selection & Check Routing](#adapter-selection--check-routing)
7. [Control Applicability](#control-applicability)
8. [CI Discovery](#ci-discovery)
9. [Attestation Generation](#attestation-generation)

---

## Main Audit Flow

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                        audit_openssf_baseline()                              │
│                     (owner, repo, local_path, level)                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │   Validate & Resolve local_path  │
                    │   - Must be absolute path        │
                    │   - Must exist                   │
                    │   - Check owner/repo match       │
                    └─────────────────────────────────┘
                                      │
                           ┌──────────┴──────────┐
                           │                     │
                           ▼                     ▼
                     [Valid Path]          [Invalid Path]
                           │                     │
                           │                     └──► Return Error
                           ▼
          ┌────────────────────────────────────────────┐
          │        Load project.toml (if exists)        │
          └────────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
        [Exists]    [Not Found]   [auto_init=False]
              │            │            │
              │            │            └──► Skip config
              │            │
              ▼            ▼
   ┌──────────────┐  ┌──────────────────────────┐
   │ Sync missing │  │ Auto-create project.toml │
   │ discoveries  │  │ from discovered files    │
   └──────────────┘  └──────────────────────────┘
              │                    │
              └────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────────────────┐
          │   Discover files & CI config        │
          │   (SECURITY.md, workflows, etc.)    │
          └────────────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────────────────┐
          │     Run Checks via Sieve System     │
          │                                     │
          │  Level 1: 24 controls (always)      │
          │  Level 2: 18 controls (if level≥2)  │
          │  Level 3: 20 controls (if level≥3)  │
          │                                     │
          │  Each control runs through 4-phase  │
          │  sieve (see Sieve Verification)     │
          └────────────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────────────────┐
          │    Filter by Control Applicability  │
          │    (project type, N/A overrides)    │
          └────────────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────────────────┐
          │      Generate Markdown Report       │
          │   - Summary (PASS/FAIL/WARN/N/A)    │
          │   - Failures with remediation       │
          │   - Warnings                        │
          └────────────────────────────────────┘
```

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
│  │ file_must_exist: ["SECURITY.md", ".github/SECURITY.md"]               │  │
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

### 3.1 Context Resolution

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Check needs project context                              │
│                  (e.g., CI provider, has_subprojects)                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │ is_context_confirmed(local_path, │
                    │                    context_key)  │
                    └─────────────────────────────────┘
                                      │
                           ┌──────────┴──────────┐
                           │                     │
                           ▼                     ▼
                    [Key in config]        [Key not found]
                           │                     │
                           ▼                     ▼
              ┌─────────────────────┐   ┌─────────────────────┐
              │ get_context_value() │   │ Return INCONCLUSIVE │
              │                     │   │ with prompt to      │
              │ Returns user's      │   │ confirm in          │
              │ confirmed value     │   │ project.toml        │
              └─────────────────────┘   └─────────────────────┘
                           │                     │
                           ▼                     │
              ┌─────────────────────┐            │
              │ Use value in check  │            │
              │ logic:              │            │
              │                     │            │
              │ ci_provider="none"  │            │
              │  → N/A for CI checks│            │
              │                     │            │
              │ ci_provider="gitlab"│            │
              │  → Check .gitlab-ci │            │
              │    OR manual verify │            │
              └─────────────────────┘            │
                           │                     │
                           └──────────┬──────────┘
                                      │
                                      ▼
                                [Continue check]
```

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

### 3.3 CI Provider Decision Tree

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                  CI-related check (e.g., OSPS-VM-06.02 SAST)                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │  .github/workflows/ exists?      │
                    └─────────────────────────────────┘
                                      │
                           ┌──────────┴──────────┐
                           │                     │
                           ▼                     ▼
                        [Yes]                  [No]
                           │                     │
                           ▼                     ▼
              ┌─────────────────────┐   ┌─────────────────────┐
              │ Scan workflows for  │   │ Check other CI      │
              │ SAST tools:         │   │ config files:       │
              │                     │   │                     │
              │ • codeql            │   │ • .gitlab-ci.yml    │
              │ • semgrep           │   │ • Jenkinsfile       │
              │ • sonar             │   │ • .circleci/config  │
              │ • bandit            │   │ • azure-pipelines   │
              └─────────────────────┘   │ • .travis.yml       │
                           │            └─────────────────────┘
                           │                     │
                           │            ┌────────┴────────┐
                           │            │                 │
                           │            ▼                 ▼
                           │      [Config found]    [No config]
                           │            │                 │
                           │            ▼                 ▼
                           │    ┌───────────────┐ ┌───────────────┐
                           │    │ Scan for SAST │ │ Check         │
                           │    │ in that CI    │ │ project.toml  │
                           │    └───────────────┘ │ [ci_provider] │
                           │            │         └───────────────┘
                           │            │                 │
                           │            │         ┌───────┴───────┐
                           │            │         │               │
                           │            │         ▼               ▼
                           │            │   [Confirmed]     [Not set]
                           │            │         │               │
                           │            │    ┌────┴────┐          │
                           │            │    │         │          │
                           │            │    ▼         ▼          │
                           │            │ "none"    "other"       │
                           │            │    │         │          │
                           │            │    ▼         ▼          ▼
                           │            │  N/A     WARN:      INCONCLUSIVE:
                           │            │         "manual     "confirm CI
                           │            │         verify"     in project.toml"
                           ▼            ▼
              ┌─────────────────────────────────────────┐
              │  Tool found? → PASS with evidence       │
              │  No tool?    → FAIL or INCONCLUSIVE     │
              └─────────────────────────────────────────┘
```

### 3.4 project.toml Context Section

```toml
# In project.toml

[project.context]
# User-confirmed facts that affect control evaluation

# Does this project have subprojects or related repositories?
has_subprojects = false

# Does this project make official releases?
has_releases = true

# Is this a library/framework consumed by other projects?
is_library = false

# Does this project have compiled/binary release assets?
has_compiled_assets = false

# What CI/CD system does this project use?
# Options: github, gitlab, jenkins, circleci, azure, travis, none, other
ci_provider = "gitlab"

# Path to CI config (for non-GitHub CI)
ci_config_path = ".gitlab-ci.yml"
```

---

## Context Sieve Flow

The Context Sieve provides progressive auto-detection of project context (maintainers, security contacts, governance model) for remediation. It runs cheap/fast checks first and stops when confidence is sufficient.

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
┌─────────────────────────────────────────────────────────────────────────────┐
│        check_context_requirements(requirements, local_path, owner, repo)     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │  For each ContextRequirement:    │
                    │  { key, required, threshold,     │
                    │    prompt_if_auto_detected }     │
                    └─────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────┐
                    │  get_context_value(local_path,   │
                    │                    key)          │
                    └─────────────────────────────────┘
                                      │
                           ┌──────────┴──────────┐
                           │                     │
                           ▼                     ▼
                    [Value Found]          [Value Missing]
                    (in .project.yaml)           │
                           │                     │
                           │                     ▼
                           │     ┌─────────────────────────────────┐
                           │     │  _try_sieve_detection(          │
                           │     │      key, local_path,           │
                           │     │      owner, repo)               │
                           │     │                                 │
                           │     │  Run Context Sieve pipeline     │
                           │     └─────────────────────────────────┘
                           │                     │
                           │          ┌──────────┴──────────┐
                           │          │                     │
                           │          ▼                     ▼
                           │   [Sieve Found]          [Nothing Found]
                           │   (auto-detected)              │
                           │          │                     │
                           │          ▼                     ▼
                           │   Store in result.       Mark as missing,
                           │   auto_detected          add to prompts
                           │          │
                           └──────────┴──────────────┐
                                                     │
                                                     ▼
                              ┌─────────────────────────────────┐
                              │  Check confidence threshold      │
                              │                                  │
                              │  confidence >= threshold?        │
                              │  prompt_if_auto_detected?        │
                              └─────────────────────────────────┘
                                                     │
                              ┌───────────────────────┴───────────────────────┐
                              │                                               │
                              ▼                                               ▼
                  ┌──────────────────────┐                    ┌──────────────────────┐
                  │ Ready to proceed     │                    │ Needs confirmation   │
                  │                      │                    │                      │
                  │ result.ready = True  │                    │ result.ready = False │
                  │                      │                    │ Add prompt message   │
                  └──────────────────────┘                    └──────────────────────┘
```

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
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Example: detect("maintainers", "/path/to/repo")           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Phase 1 (Deterministic):                                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  • Check MAINTAINERS.md → Not found                                    │ │
│  │  • Check .github/CODEOWNERS → Found!                                   │ │
│  │    Content: "* @alice @bob"                                            │ │
│  │    Signal: { source: EXPLICIT_FILE, value: ["@alice", "@bob"],         │ │
│  │              raw_confidence: 0.95 }                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  confidence = 0.95 × 0.9 (EXPLICIT_FILE weight) = 0.855                     │
│  0.855 < 0.9 threshold → Continue to Phase 2                                │
│                                                                              │
│  Phase 2 (Heuristic):                                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  • Check package.json → Found!                                         │ │
│  │    Content: { "author": "Alice Smith <alice@example.com>" }            │ │
│  │    Signal: { source: PROJECT_MANIFEST, value: ["alice"],               │ │
│  │              raw_confidence: 0.8 }                                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 4 (Combine):                                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Signals: [CODEOWNERS: @alice, @bob], [package.json: alice]            │ │
│  │                                                                         │ │
│  │  Agreement: "alice" appears in both → agreement_factor = 0.75          │ │
│  │                                                                         │ │
│  │  weighted_avg = (0.855 + 0.64) / 2 = 0.7475                            │ │
│  │  boost = 1.2 (signals agree)                                           │ │
│  │                                                                         │ │
│  │  final_confidence = 0.7475 × 0.75 × 1.2 = 0.67                         │ │
│  │                                                                         │ │
│  │  Result: { value: ["@alice", "@bob"], confidence: 0.67,                │ │
│  │            signals: [...], needs_confirmation: True }                  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Output to user:                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  🔍 Auto-detected maintainers (confidence: 67%):                       │ │
│  │     - @alice (from CODEOWNERS, package.json)                           │ │
│  │     - @bob (from CODEOWNERS)                                           │ │
│  │                                                                         │ │
│  │  Confidence below 90% threshold. Please confirm:                       │ │
│  │     confirm_project_context(maintainers=["@alice", "@bob"])            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Project Configuration Lifecycle

### 4.1 Loading project.toml

```text
┌──────────────────────────────────────────────────────────────────┐
│                    load_project_config(local_path)                │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │  Look for config file:            │
              │  1. project.toml                  │
              │  2. .project.toml                 │
              └───────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
              [File Found]        [Not Found]
                    │                   │
                    │                   └──► Return None
                    ▼
              ┌─────────────────────────────┐
              │      Parse TOML file         │
              └─────────────────────────────┘
                    │
                    ├──► schema_version
                    ├──► [project] section → name, type, controls
                    ├──► [security] section → policy, threat_model, ...
                    ├──► [governance] section → contributing, codeowners, ...
                    ├──► [legal] section → license, contributor_agreement
                    ├──► [testing] section → docs, requirements
                    ├──► [releases] section → verification, ...
                    └──► [ci] section → provider, github.*, ...
                              │
                              ▼
                    ┌─────────────────────────┐
                    │  Return ProjectConfig    │
                    └─────────────────────────┘
```

### 4.2 Syncing Discovered Items

```text
┌──────────────────────────────────────────────────────────────────┐
│        sync_discovered_to_config(config, local_path)              │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │   For each discovered file:       │
              │   (SECURITY.md, LICENSE, etc.)    │
              └───────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
           [Already in config]   [Not in config]
                    │                   │
                    │                   ▼
                    │           ┌───────────────────┐
                    │           │ Add to config as  │
                    │           │ ResourceReference │
                    │           └───────────────────┘
                    │                   │
                    └─────────┬─────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │   For each CI capability:         │
              │   (testing, security_scanning...) │
              └───────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
           [Already in config]   [Not in config]
                    │                   │
                    │                   ▼
                    │           ┌───────────────────┐
                    │           │   Merge into CI   │
                    │           │   (add, don't     │
                    │           │    overwrite)     │
                    │           └───────────────────┘
                    │                   │
                    └─────────┬─────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │ Return (modified: bool, changes)  │
              └───────────────────────────────────┘
```

---

## Adapter Selection & Check Routing

### 5.1 Which Adapter to Use?

```text
┌──────────────────────────────────────────────────────────────────┐
│                 get_check_adapter(control_id)                     │
│                      (from ToolRegistry)                          │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │  Check .baseline.toml for         │
              │  control-specific adapter config  │
              └───────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
      [Custom Adapter]  [Default Setting]  [No Config]
              │               │               │
              │               │               │
              ▼               ▼               ▼
      ┌───────────┐    ┌───────────┐   ┌───────────┐
      │  "kusari" │    │ "builtin" │   │ "builtin" │
      │  "script" │    │  (from    │   │ (hardcoded│
      │  "custom" │    │  settings)│   │  default) │
      └───────────┘    └───────────┘   └───────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │     Look up adapter instance      │
              │   check_adapters[adapter_name]    │
              └───────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
             [Adapter Found]     [Adapter Not Found]
                    │                   │
                    │                   ▼
                    │           ┌───────────────────┐
                    │           │ Fallback to       │
                    │           │ "builtin" adapter │
                    │           └───────────────────┘
                    │                   │
                    └─────────┬─────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │     Return CheckAdapter instance   │
              └───────────────────────────────────┘
```

### 5.2 Adapter Types

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ADAPTER TYPES                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     BuiltinCheckAdapter                               │   │
│  │  - Default adapter for all controls                                   │   │
│  │  - Hardcoded check logic in Python                                    │   │
│  │  - Routes by control prefix (OSPS-AC, OSPS-BR, etc.)                  │   │
│  │  - Uses GitHub API + local file analysis                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                       KusariAdapter                                   │   │
│  │  - Integration with Kusari security scanner                           │   │
│  │  - Maps controls to Kusari check names                                │   │
│  │  - Runs: kusari repo scan --format json                               │   │
│  │  - Supports: OSPS-VM-05.*, OSPS-SA-02.*                               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                       ScriptAdapter                                   │   │
│  │  - Runs custom shell commands                                         │   │
│  │  - Passes context via environment variables:                          │   │
│  │      OSPS_CONTROL_ID, OSPS_OWNER, OSPS_REPO, OSPS_LOCAL_PATH          │   │
│  │  - Expects JSON output: {status, message, details}                    │   │
│  │  - Supports batch mode for multiple controls                          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Builtin Adapter - Check Routing

```text
┌──────────────────────────────────────────────────────────────────┐
│            BuiltinCheckAdapter.check(control_id)                  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │  Extract prefix from control_id   │
              │  "OSPS-AC-03.01" → "OSPS-AC"      │
              └───────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │  Map prefix to category:          │
              │                                   │
              │  OSPS-AC → access_control         │
              │  OSPS-BR → build_release          │
              │  OSPS-DO → documentation          │
              │  OSPS-GV → governance             │
              │  OSPS-LI → legal                  │
              │  OSPS-QA → quality                │
              │  OSPS-SA → security_architecture  │
              │  OSPS-VM → vulnerability          │
              └───────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │  Determine level from control_id  │
              │  and call appropriate function:   │
              │                                   │
              │  check_level1_{category}()        │
              │  check_level2_{category}()        │
              │  check_level3_{category}()        │
              └───────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │   Return List[CheckResult]        │
              └───────────────────────────────────┘
```

---

## Control Applicability

```text
┌──────────────────────────────────────────────────────────────────┐
│             is_control_applicable(control_id)                     │
│                  (from ProjectConfig)                             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────────┐
              │  Step 1: Check explicit overrides │
              │  (from [project.controls])        │
              └───────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
    [Override exists]               [No override]
              │                               │
              ▼                               │
    ┌─────────────────────┐                   │
    │ status == "n/a"?    │                   │
    └─────────────────────┘                   │
              │                               │
        ┌─────┴─────┐                         │
        │           │                         │
        ▼           ▼                         │
     [Yes]        [No]                        │
        │           │                         │
        ▼           │                         │
  Return (False,    │                         │
   override.reason) │                         │
                    │                         │
                    └────────────┬────────────┘
                                 │
                                 ▼
              ┌───────────────────────────────────┐
              │  Step 2: Check project type       │
              │  exclusions                       │
              └───────────────────────────────────┘
                                 │
                                 ▼
              ┌───────────────────────────────────┐
              │  PROJECT_TYPE_EXCLUSIONS lookup   │
              │                                   │
              │  software → (none)                │
              │  specification → BR-02, BR-03,    │
              │                   VM-05, QA-02    │
              │  documentation → BR-02, BR-03,    │
              │                   VM-05, QA-02,   │
              │                   SA-02, SA-03    │
              │  infrastructure → BR-02           │
              │  data → BR-01, BR-02, BR-03,      │
              │         QA-02, QA-03              │
              └───────────────────────────────────┘
                                 │
                                 ▼
              ┌───────────────────────────────────┐
              │  Does control_id start with       │
              │  any exclusion prefix?            │
              └───────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                    ▼                         ▼
                 [Yes]                      [No]
                    │                         │
                    ▼                         ▼
          Return (False,              Return (True, None)
          "Not applicable for         [Control IS applicable]
          {type} projects")
```

---

## CI Discovery

### 7.1 Provider Detection

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

### 7.2 GitHub Capability Detection

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

### 7.3 Capability → OSPS Control Mapping

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

### 7.4 Non-GitHub CI Provider Handling

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
file      project.toml"                                       │         │
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

### 7.5 CI Provider Configuration Reference

```toml
# project.toml example for non-GitHub CI

[project.context]
# Tell the audit which CI system you use
ci_provider = "gitlab"    # or jenkins, circleci, azure, travis, none, other
ci_config_path = ".gitlab-ci.yml"

[ci]
provider = "gitlab"
provider_config = ".gitlab-ci.yml"

# For GitLab CI, can specify capabilities discovered/confirmed
[ci.gitlab]
testing = [".gitlab-ci.yml"]           # Jobs that run tests
security_scanning = [".gitlab-ci.yml"]  # Jobs that run SAST
code_quality = [".gitlab-ci.yml"]       # Jobs that run linting
```

---

## Attestation Generation

### 8.1 Main Attestation Flow

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
          │      Load/create project.toml               │
          └────────────────────────────────────────────┘
                           │
                           ▼
          ┌────────────────────────────────────────────┐
          │           Run All Check Functions           │
          │                                             │
          │   Level 1: check_level1_*() → results      │
          │   Level 2: check_level2_*() → results      │
          │   Level 3: check_level3_*() → results      │
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

### 8.2 Sigstore Signing Flow

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

### 8.3 Subject Format Differences

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

### 8.4 Attestation Verification

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

### 8.5 Attestation Predicate Structure

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│            Assessment Predicate (https://openssf.org/baseline/assessment/v1)│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  {                                                                           │
│    "assessor": {                                                             │
│      "name": "openssf-baseline-mcp",                                        │
│      "version": "0.1.0",                                                    │
│      "uri": "https://github.com/ossf/baseline-mcp"                          │
│    },                                                                        │
│    "timestamp": "2024-11-30T12:00:00Z",                                     │
│    "baseline": {                                                             │
│      "version": "2025.10.10",                                               │
│      "specification": "https://baseline.openssf.org/versions/2025-10-10"    │
│    },                                                                        │
│    "repository": {                                                           │
│      "url": "https://github.com/owner/repo",                                │
│      "commit": "abc123...",                                                 │
│      "ref": "main"                      ◄── branch or tag                   │
│    },                                                                        │
│    "configuration": {                                                        │
│      "project_type": "software",                                            │
│      "excluded_controls": ["OSPS-BR-02.01"],                                │
│      "adapters_used": ["builtin"]                                           │
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
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Configuration Files                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  project.toml                      │  .baseline.toml                         │
│  ─────────────────────────────────────────────────────────────────────────   │
│  Purpose: Project metadata &       │  Purpose: MCP server configuration      │
│           documentation locations  │           & adapter settings            │
│                                    │                                         │
│  Contains:                         │  Contains:                              │
│  • schema_version                  │  • schema_version                       │
│  • [project] name, type, controls  │  • [settings] defaults, timeouts        │
│  • [security] policy, threat_model │  • [adapters.*] custom adapter configs  │
│  • [governance] contributing, etc. │  • [controls.*] per-control overrides   │
│  • [testing] docs, requirements    │                                         │
│  • [releases] verification         │                                         │
│  • [ci.github] workflows, etc.     │                                         │
│                                    │                                         │
│  Created by: audit (auto) or user  │  Created by: user only                  │
│  Auto-synced: Yes                  │  Auto-synced: No                        │
│                                    │                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference: Key Functions

### Main Audit Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `audit_openssf_baseline()` | main.py | Main entry point for audits |
| `load_project_config()` | main.py | Load project.toml |
| `sync_discovered_to_config()` | main.py | Sync discovered items to config |
| `discover_ci_config()` | main.py | Discover CI capabilities |
| `is_control_applicable()` | main.py | Check if control applies |

### Sieve System Functions

| Function/Class | Location | Purpose |
|----------------|----------|---------|
| `SieveOrchestrator` | sieve/orchestrator.py | Runs 4-phase verification pipeline |
| `SieveOrchestrator.verify()` | sieve/orchestrator.py | Verify single control through passes |
| `ControlRegistry` | sieve/registry.py | Registry of control specifications |
| `get_control_registry()` | sieve/registry.py | Get global control registry |
| `ControlSpec` | sieve/models.py | Control definition with passes |
| `DeterministicPass` | sieve/passes.py | File/API boolean checks |
| `PatternPass` | sieve/passes.py | Regex content matching |
| `LLMPass` | sieve/passes.py | LLM-assisted verification |
| `ManualPass` | sieve/passes.py | Human verification steps |
| `PassResult` | sieve/models.py | Result from a single pass |
| `SieveResult` | sieve/models.py | Final verification result |
| `CheckContext` | sieve/models.py | Context for check execution |

### Project Context Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `is_context_confirmed()` | main.py | Check if context key is set in project.toml |
| `get_context_value()` | main.py | Get user-confirmed context value |
| `CONTEXT_KEYS` | main.py | Registry of context keys and affected controls |

### Adapter Functions (Legacy)

| Function | Location | Purpose |
|----------|----------|---------|
| `ToolRegistry.get_check_adapter()` | main.py | Get adapter for control |
| `BuiltinCheckAdapter.check()` | main.py | Route to builtin checks |
| `check_level{1,2,3}_{category}()` | checks/level{1,2,3}.py | Actual check implementations |
