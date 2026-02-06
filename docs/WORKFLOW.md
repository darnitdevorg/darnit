# Darnit Workflow

Visual guide to how darnit operates end-to-end: from server startup through audit, remediation, and git workflows.

## 1. High-Level Session Flow

A typical AI-driven compliance session. The AI calls MCP tools in sequence, with darnit handling all the heavy lifting.

```mermaid
sequenceDiagram
    participant AI as AI Assistant
    participant MCP as Darnit MCP Server
    participant FS as Filesystem

    AI->>MCP: audit_openssf_baseline(level=1)
    MCP->>FS: Load TOML configs + .project/
    MCP-->>AI: Markdown report (PASS/FAIL/WARN)

    AI->>MCP: get_pending_context()
    MCP-->>AI: Missing context + prompts

    AI->>MCP: confirm_project_context(ci_provider="github", ...)
    MCP->>FS: Update .project/project.yaml
    MCP-->>AI: Confirmation

    AI->>MCP: remediate_audit_findings(dry_run=true)
    MCP-->>AI: Preview of changes

    AI->>MCP: remediate_audit_findings(dry_run=false)
    MCP->>FS: Create files, run commands, update .project/
    MCP-->>AI: Remediation results

    AI->>MCP: create_remediation_branch()
    MCP->>FS: git checkout -b fix/openssf-baseline-compliance
    MCP-->>AI: Branch name

    AI->>MCP: commit_remediation_changes()
    MCP->>FS: git add + commit
    MCP-->>AI: Commit SHA

    AI->>MCP: create_remediation_pr()
    MCP-->>AI: PR URL

    AI->>MCP: audit_openssf_baseline(level=1)
    MCP-->>AI: Updated report (more passes)
```

## 2. Audit Internals

What happens inside `audit_openssf_baseline()`.

```mermaid
flowchart TD
    A[audit_openssf_baseline called] --> B[Load framework TOML]
    B --> C[Load .baseline.toml user overrides]
    C --> D[Merge configs → EffectiveConfig]
    D --> E[load_controls_from_effective]
    E --> F[Convert each control → ControlSpec + Pass objects]
    F --> G[Filter by level]
    G --> H{Filter by tags?}
    H -->|Yes| I[Apply tag filter]
    H -->|No| J[Use all controls at level]
    I --> J

    J --> K[Load .project/project.yaml]
    K --> L["For each control"]

    L --> M[Create CheckContext<br/>inject owner, repo, local_path, project_context]
    M --> N[SieveOrchestrator.verify]
    N --> O[Collect SieveResult]
    O --> P{More controls?}
    P -->|Yes| L
    P -->|No| Q[Calculate summary<br/>PASS / FAIL / WARN counts]
    Q --> R[Format as markdown]
    R --> S[Return to AI]
```

## 3. Sieve Pipeline (Single Control)

How a control is verified through the 4-phase waterfall. Stops at the first conclusive result.

```mermaid
flowchart TD
    Start[SieveOrchestrator.verify] --> D

    subgraph Phase1["Phase 1: DETERMINISTIC"]
        D[Execute deterministic pass<br/>file_must_exist / exec / expr / api_check]
    end

    D --> D_check{Result?}
    D_check -->|PASS| D_pass[Apply on_pass updates → .project/]
    D_pass --> Done[Return SieveResult]
    D_check -->|FAIL| Done
    D_check -->|INCONCLUSIVE| P

    subgraph Phase2["Phase 2: PATTERN"]
        P[Execute pattern pass<br/>file_patterns + content_patterns + expr]
    end

    P --> P_check{Result?}
    P_check -->|PASS| P_pass[Apply on_pass updates → .project/]
    P_pass --> Done
    P_check -->|FAIL| Done
    P_check -->|INCONCLUSIVE| LLM

    subgraph Phase3["Phase 3: LLM"]
        LLM[Execute LLM pass<br/>consultation_request for AI analysis]
    end

    LLM --> LLM_check{Result?}
    LLM_check -->|PASS / FAIL| Done
    LLM_check -->|PENDING_LLM| Pending[Return PENDING_LLM<br/>AI must analyze]
    LLM_check -->|INCONCLUSIVE| Manual

    subgraph Phase4["Phase 4: MANUAL"]
        Manual[Execute manual pass<br/>verification_steps for human review]
    end

    Manual --> Warn[Return WARN<br/>manual verification needed]

    style Phase1 fill:#e8f5e9,stroke:#4caf50
    style Phase2 fill:#e3f2fd,stroke:#2196f3
    style Phase3 fill:#fff3e0,stroke:#ff9800
    style Phase4 fill:#fce4ec,stroke:#e91e63
```

## 4. Remediation Flow

What happens inside `remediate_audit_findings()`.

```mermaid
flowchart TD
    A[remediate_audit_findings called] --> B[Run audit to find failures]
    B --> C[Group failed controls by category]
    C --> Pre[Preflight: check context requirements<br/>for all categories]

    Pre --> Pre_check{Missing context?}
    Pre_check -->|Yes| Prompt[Return prompts<br/>AI must call confirm_project_context first]
    Pre_check -->|No| Loop[For each category]

    Loop --> Cat[For each failed control in category]
    Cat --> Applicable{is_control_applicable?}
    Applicable -->|No / N/A| Skip[Skip control]
    Applicable -->|Yes| TOML_check{Has TOML remediation?<br/>file_create / exec / api_call}

    TOML_check -->|Yes| Executor[RemediationExecutor]
    TOML_check -->|No| Legacy[Legacy Python handler]

    subgraph exec["RemediationExecutor"]
        Executor --> ExType{Remediation type?}
        ExType -->|file_create| FC[Substitute variables<br/>Write file from template/inline]
        ExType -->|exec| EX[Substitute variables<br/>Run subprocess]
        ExType -->|api_call| API[Build gh api command<br/>Execute with payload]
    end

    FC --> DryCheck
    EX --> DryCheck
    API --> DryCheck
    Legacy --> DryCheck

    DryCheck{dry_run?}
    DryCheck -->|Yes| Preview[Record what would change]
    DryCheck -->|No| Apply[Apply changes]
    Apply --> PU{Has project_update?}
    PU -->|Yes| Update[Update .project/project.yaml]
    PU -->|No| Next
    Update --> Next

    Preview --> Next[Next control]
    Skip --> Next
    Next --> More{More controls?}
    More -->|Yes| Cat
    More -->|No| MoreCat{More categories?}
    MoreCat -->|Yes| Loop
    MoreCat -->|No| Format[Format results]
    Format --> Return[Return to AI]
```

## 5. Context Lifecycle

How `.project/project.yaml` is created, read, enriched, and fed back into subsequent audits.

```mermaid
flowchart LR
    subgraph Sources["Context Sources"]
        User["AI calls<br/>confirm_project_context()"]
        OnPass["Control PASS<br/>→ on_pass config"]
        Remediation["Remediation success<br/>→ project_update config"]
    end

    subgraph Store[".project/project.yaml"]
        YAML["project context<br/>(maintainers, CI, governance,<br/>security policy, releases, ...)"]
    end

    subgraph Consumers["Context Consumers"]
        Sieve["Sieve passes<br/>(CEL expressions,<br/>context-aware checks)"]
        Preflight["Remediation preflight<br/>(are requirements met?)"]
        Pending["get_pending_context<br/>(what's still missing?)"]
    end

    User -->|"save_project_config()"| YAML
    OnPass -->|"apply_project_update()"| YAML
    Remediation -->|"apply_project_update()"| YAML

    YAML -->|"load at audit start"| Sieve
    YAML -->|"check before remediation"| Preflight
    YAML -->|"diff against requirements"| Pending

    Sieve -->|"control passes → triggers on_pass"| OnPass
    Preflight -->|"missing? → prompt user"| User
```

## 6. Server Startup

How the MCP server is assembled from TOML config and plugin entry points.

```mermaid
flowchart TD
    A[darnit serve] --> B[Load framework TOML<br/>metadata.framework_name]
    B --> C[Plugin discovery<br/>entry_points 'darnit.implementations']
    C --> D[Get implementation instance<br/>e.g. OpenSSFBaselineImplementation]
    D --> E["impl.register_handlers()<br/>populate handler registry"]
    E --> F["Read [mcp.tools] from TOML"]
    F --> G[For each tool definition]
    G --> H[Resolve handler<br/>short name → registry lookup<br/>module:function → import]
    H --> I[Register with FastMCP server]
    I --> J{More tools?}
    J -->|Yes| G
    J -->|No| K[Server ready<br/>listening for AI tool calls]
```

## Key

| Term | Meaning |
|------|---------|
| **TOML config** | Framework control definitions (`openssf-baseline.toml`) |
| **.baseline.toml** | User overrides (disable controls, change severity) |
| **.project/project.yaml** | Project context (maintainers, CI provider, etc.) |
| **ControlSpec** | A control with its passes, remediation, and metadata |
| **SieveResult** | Outcome of verifying a single control (PASS/FAIL/WARN) |
| **on_pass** | TOML config that updates .project/ when a control passes |
| **project_update** | TOML config that updates .project/ after successful remediation |
| **CheckContext** | Runtime context passed to each sieve pass (owner, repo, project_context) |
