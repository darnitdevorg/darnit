# Feature Specification: Threat-Model Coverage for Cobra-Based Go CLIs

**Feature Branch**: `014-cobra-threat-model`

**Created**: 2026-05-18

**Status**: Draft

**Input**: User description: "let's work on 3, let's see what we can get done for threat model of cobra. Again, when building out this threat model we want to be accurate, but don't necessarily need to be complete, we just need to have something that looks pretty reasonable and other humans can then take to further refine."

## Clarifications

### Session 2026-05-18

- Q: How should the generator decide which cobra commands belong to the same "family"? → A: Hybrid — filesystem layout as the grouping key, with the parent command's `Use:` text as the display name when available, falling back to the directory name.
- Q: When a cobra command's purpose isn't discernible from the source, what STRIDE category should the finding default to? → A: Small import-based heuristic — file imports `os.Write*` → Tampering; `crypto/*` or signature ops → Repudiation; `net/http` → Spoofing + Information Disclosure; fall back to Tampering.
- Q: When a project mixes cobra commands AND HTTP routes, how should they appear in the rendered output? → A: Separate top-level sections ("CLI Entry Points" and "HTTP Entry Points") as siblings in the document, each with their findings underneath.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Maintainer audits a cobra-based Go CLI and gets a usable draft threat model (Priority: P1)

A maintainer (or auditor) runs darnit's threat-model generator against a Go repository that uses [Cobra](https://github.com/spf13/cobra) for its CLI surface (e.g., gittuf, cosign, slsa-verifier). The generator identifies the project's commands as the program's external entry points, categorises a plausible STRIDE threat against each command family, and writes a `THREAT_MODEL.md` whose contents a reviewer can scan, sanity-check, and refine within ten minutes — instead of the current behaviour, which is a structurally-complete-but-empty report claiming "Total findings: 0."

**Why this priority**: Without this, darnit's flagship SA-03.02 remediation (threat-model generation) produces misleadingly-empty output for the dominant shape of Go security tooling in the OpenSSF / Sigstore / SLSA ecosystem. This blocks audits, blocks demos, and undermines the credibility of the tool. Solving it for cobra alone covers the large majority of relevant Go projects.

**Independent Test**: Run the threat-model generator cold against a fixture project that uses cobra (and against gittuf as the real-world reference). Verify the output is non-empty, names each major command family, and includes a STRIDE category and a file:line pointer for each finding.

**Acceptance Scenarios**:

1. **Given** a Go repository that uses cobra with at least one `Use:`/`RunE:` command definition, **When** the threat-model generator runs, **Then** the resulting threat-model document contains at least one finding per major command family, each with a STRIDE category and a source location.
2. **Given** a Go repository with a mix of cobra commands and HTTP routes (e.g., a CLI tool that also exposes a debug server), **When** the threat-model generator runs, **Then** both kinds of entry points appear in the output and the existing HTTP behaviour is unchanged.
3. **Given** the gittuf repository cold (no staging, current main), **When** the threat-model generator runs, **Then** the resulting document contains between 5 and 15 distinct command-family findings — enough that a reviewer can read them all in under ten minutes.

---

### User Story 2 - Reviewer reads the draft and refines it without spelunking the codebase (Priority: P2)

A human or LLM reviewer opens the generated threat model intending to refine it. Each finding tells them which command family it covers, where to find the source, and what STRIDE category was guessed — enough context that they can verify or recategorise it without scanning the whole repository. The document itself states it is a draft that requires human refinement and includes verification prompts so an LLM can confidently take the next pass.

**Why this priority**: Drafts that don't tell you where they came from waste reviewer time. The user explicitly framed the goal as "looks reasonable, a human refines" — so the refinement workflow must be a first-class concern, not an afterthought.

**Independent Test**: Hand the generated document to a reviewer who hasn't read the target project. They should be able to navigate from any finding to the corresponding source code in under 30 seconds using only the information in the document.

**Acceptance Scenarios**:

1. **Given** a generated threat-model document, **When** a reviewer opens any finding, **Then** the finding includes the command name, a file path, and a line range, and a brief one-line description of what the command does (where derivable from the command's `Use:` or `Short:` text).
2. **Given** a generated threat-model document, **When** a reviewer reaches the end, **Then** the document explicitly states it is a draft, lists known limitations, and embeds a verification-prompt block targeted at the next reviewer (human or LLM).

---

### User Story 3 - The output is presentable on stage in a live demo (Priority: P3)

A maintainer runs the generator live during a 15-minute conference demo against gittuf (or a similar cobra CLI). The output renders cleanly, contains no error messages or empty sections, names commands the audience would recognise from the project's `--help` output, and finishes in under sixty seconds.

**Why this priority**: The immediate motivating use case is a demo within days. A demo-shippable result is a forcing function for "looks reasonable" — if it'd embarrass the demo, it isn't ready.

**Independent Test**: Dry-run the demo flow three times against gittuf. Each run finishes inside the time budget, the rendered document has no empty sections, and the command-family names match what `gittuf --help` shows.

**Acceptance Scenarios**:

1. **Given** the generator runs against a cobra-based Go CLI on a modern laptop, **When** the user invokes the threat-model generation step, **Then** it completes within sixty seconds and writes a document with no empty sections and no rendered error markers.
2. **Given** the generated document is shown to an audience, **When** a viewer compares the command-family names to the target project's `--help` output, **Then** the names match the project's vocabulary (e.g., gittuf's `cache`, `attest`, `rsl`, `verify` families).

---

### Edge Cases

- **Non-cobra Go projects**: the system must not produce false-positive cobra findings, and existing HTTP-route detection (`net/http`, chi, gorilla) must continue to work unchanged.
- **Very small CLIs (1-2 commands)**: still produce a usable draft, not a crash and not an empty report.
- **Cobra commands defined in unusual patterns**: builder-style construction, factory functions returning `*cobra.Command` through indirection, commands assembled at runtime — these should be skipped silently and reported as a limitation in the document's "known gaps" section, rather than producing garbled output.
- **Generated or vendored cobra code**: should be excluded from discovery, matching how the rest of the pipeline already handles vendor/build directories.
- **Repositories with hundreds of commands**: command-family grouping must keep the output legible; the document should not contain hundreds of individual findings.
- **Cobra used in a non-CLI context** (e.g., a library that exposes cobra commands for embedding): the output may be less meaningful, but the generator should still produce something rather than fail.
- **Mixed entry points** (cobra + HTTP routes in the same repository): both surface in the output as separate top-level sections ("CLI Entry Points" and "HTTP Entry Points"), each carrying their own family/finding structure underneath; neither suppresses the other.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When the threat-model generator encounters a Go source tree that defines cobra commands, it MUST identify each command definition as an entry point in the model.
- **FR-002**: The generator MUST produce a non-empty threat-model document (at least one STRIDE-categorised finding with a location and a command name) for any cobra-based Go CLI containing at least one command definition.
- **FR-003**: The generator MUST group sibling cobra commands into command families so a project with N commands does not produce N individually-rendered findings. Families are derived from filesystem layout: each top-level subdirectory under the project's command root (e.g., `cmd/`, `internal/cmd/`) defines one family containing all cobra commands discovered in that subdirectory tree. The family display name SHOULD be taken from the parent command's `Use:` string where a parent command exists in the family's root directory; otherwise the directory name is used. Individual commands surface as locations within their family.
- **FR-004**: Each finding MUST include a source location pointer (file path plus line range) sufficient for a reviewer to navigate to the underlying code without searching.
- **FR-005**: Each finding MUST be assigned at least one STRIDE category, derived from a small import-based heuristic applied to the file containing the command:
  - File imports `os.Write*`, file-truncating, or path-walking writers → **Tampering**
  - File imports `crypto/*`, signature operations, or attestation primitives → **Repudiation**
  - File imports `net/http` (or other HTTP clients/servers) → **Spoofing + Information Disclosure**
  - File imports `os/exec`, `syscall`, or process-spawning primitives → **Elevation of Privilege**
  - Otherwise → fall back to **Tampering**

  All findings MUST be marked as needing reviewer attention so the next reviewer (human or LLM) understands the category is a heuristic default and may need recategorisation. Multi-category assignments (e.g., HTTP → Spoofing + Information Disclosure) are rendered as a list, not collapsed.
- **FR-006**: The generated document MUST state explicitly that it is a draft requiring human refinement, AND it MUST include a verification-prompt block aimed at the next reviewer (human or LLM).
- **FR-007**: The generator MUST list any known coverage gaps (unrecognised command patterns, scanned-but-skipped files, missing taint analysis, etc.) in a dedicated "Limitations" section of the output, so reviewers know what the draft does not cover.
- **FR-008**: Existing Go HTTP-service detection (`net/http`, chi, gorilla) MUST continue to function with no regression. Cobra discovery MUST NOT suppress HTTP entry-point discovery in repositories that contain both.
- **FR-009**: Non-cobra Go projects MUST NOT produce false-positive cobra findings. Detection MUST be triggered by recognisable cobra patterns in the source, not by file paths or naming conventions.
- **FR-010**: The system MUST scan Go source files for cobra patterns without requiring any third-party Go tooling to be installed (no `go build`, no `go vet`, no Go compiler invocation at audit time).
- **FR-011**: When the generator encounters cobra command-construction patterns it does not recognise, it MUST skip them silently (no crash, no malformed output) and surface the skipped patterns in the Limitations section if any exist.
- **FR-012**: The generated output MUST be suitable for live demonstration: no internal error markers in the rendered text, no empty findings sections, and every finding fully populated with the required fields (family, location, STRIDE category, brief description).
- **FR-013**: The generator MUST finish writing the document within sixty seconds when run against a repository of up to roughly five hundred Go source files on a modern developer laptop.
- **FR-014**: When a project contains both cobra command definitions and HTTP route registrations, the rendered document MUST organise findings into two separate top-level sections ("CLI Entry Points" and "HTTP Entry Points") that coexist as siblings, each with its own family/finding structure underneath. When a project contains only one shape, only the corresponding section is rendered (no empty placeholder for the absent shape).
- **FR-015**: When the rendered Markdown document contains a `### CLI Entry Points` subsection, the companion artefacts (SARIF report and `raw-findings.json` summary) MUST surface the same CLI findings consistently with the Markdown output: one SARIF result per family with the family's source directory as the primary location and individual subcommand files as related locations; one JSON entry per family carrying `kind: "cli_command"` plus the field schema documented in [`contracts/output-document-contract.md`](contracts/output-document-contract.md). SARIF level for heuristic findings MUST be `note` (not `warning` or `error`).

### Key Entities

- **Cobra Command**: a definition in the source tree representing a CLI subcommand (its `Use:` text, optional short/long description, and the function it dispatches to). Discovered structurally from the source.
- **Command Family**: a coalesced group of sibling cobra commands sharing a parent. The unit of rendering for the threat model — one family yields one finding (or a small number of category-specific findings) rather than one per individual command.
- **Entry Point**: an external surface through which the program can be invoked. For cobra projects, each top-level command and each subcommand qualifies. (Existing concept extended.)
- **Finding**: a STRIDE-categorised observation tied to an entry point, with a location, a brief description, and a refinement-ready phrasing that invites human review rather than making categorical claims.
- **Verification Prompt Block**: an embedded section of the generated document that tells the next reviewer (human or LLM) what to verify, what to refine, and how to recognise findings that were over- or under-categorised.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any cobra-based Go CLI containing at least one command definition, the threat-model generator produces a non-empty document — at minimum one finding with a command name, a source location, and a STRIDE category. (Current behaviour: empty output regardless of project size.)
- **SC-002**: For the gittuf repository at current `main` (42 cobra command constructors, currently producing zero findings), the generator produces between 5 and 15 distinct command-family findings — a quantity a reviewer can read and refine inside ten minutes.
- **SC-003**: A human reviewer who has not read the target project can navigate from any finding in the generated document to the corresponding source location in under 30 seconds, using only the information in the document.
- **SC-004**: Existing Python and Go-HTTP test fixtures continue to pass with no regression: zero existing tests fail because of this work.
- **SC-005**: The generated output is suitable for live conference demo: zero internal errors in the rendered text, zero empty findings sections, every finding fully populated with family name, location, STRIDE category, and brief description.
- **SC-006**: For findings inspected by an independent reviewer at PR time (the canonical validation moment for this criterion — not a CI gate), at least 70% of the assigned STRIDE categories are judged "plausible" (consistent with the command's apparent function). The remaining findings may need recategorisation but must not be obvious nonsense. Snapshot tests on synthetic fixtures provide a deterministic regression guard for the heuristic table; the wider plausibility judgment is intrinsically reviewer work.
- **SC-007**: The generator finishes writing the document within sixty seconds on a modern developer laptop for repositories up to roughly five hundred Go source files (the size class of gittuf, slsa-verifier, and similar).

## Assumptions

- **Accuracy over completeness**: the user's explicit instruction is that the output should look reasonable and a human will refine it. The bar is "useful draft," not "exhaustive analysis." Findings may be over- or under-categorised; that is acceptable provided each one is plausible enough to invite refinement rather than rejection.
- **Cobra is the only Go CLI framework in scope for this feature**. Other Go CLI frameworks (`urfave/cli`, `alecthomas/kingpin`, viper-only setups, hand-rolled command dispatchers) are out of scope here and are tracked separately as the broader "Phase 2" of the threat-model coverage work in the project's issue tracker.
- **Pattern coverage**: the feature targets cobra's two idiomatic construction patterns — the `&cobra.Command{Use: ..., RunE: ..., ...}` composite literal and the `func New() *cobra.Command` convention used by projects such as gittuf and cosign. Less common patterns (builder-style construction, factory functions returning Command pointers through indirection, commands assembled at runtime) are best-effort and may be reported as limitations rather than recognised.
- **Output remains a draft**: the document is positioned as the starting point of a review, not the conclusion. The verification-prompt block is part of the contract — downstream skills and human reviewers are expected to take the next pass.
- **No new runtime dependencies**: the work uses darnit's existing tree-sitter pipeline. Opengrep / semgrep taint analysis remains optional, and the output must be useful without it (consistent with how the Python pipeline degrades).
- **Existing pipeline stages are extended, not replaced**: discovery, ranking, grouping, and rendering already exist for HTTP entry points; this feature plugs into those stages rather than introducing a parallel pipeline.
- **Test reference**: gittuf is the canonical real-world reference target. Synthetic fixtures (small cobra programs) cover the unit-test surface; gittuf covers the integration-level "does it actually work on real code" surface.

## Out of Scope

- Other Go CLI frameworks (`urfave/cli`, `kingpin`, viper-only setups).
- **Python CLI frameworks** (`argparse`, `click`, `typer`). This feature does NOT improve threat-model coverage for Python CLI projects — including darnit's own argparse-based CLI surface. Tracked separately as #264 (sibling to the cobra issue #262). The grouping algorithm and STRIDE heuristic table introduced by this feature are framework-agnostic and reusable by #264.
- Non-CLI Go entry points beyond what's already supported: gRPC servers, message-queue consumers, goroutine-style event handlers, custom-built command dispatchers that don't use a recognised framework. Tracked separately.
- New STRIDE heuristics tuned specifically to git-policy primitives (refspec tampering, signature bypass, etc.). The output uses darnit's existing STRIDE categorisation; refining the category set for Git-specific threats is its own follow-up.
- Optional taint analysis via Opengrep / semgrep tuned for cobra patterns. The non-taint path must produce useful output; taint-augmented findings are a future enhancement.
- A formal "this project's threat model is complete" attestation. The output is explicitly a draft; downstream attestation flows are unchanged.
