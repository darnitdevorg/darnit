# Design: Strengthen Baseline Checks & Remediations

## 1. `files_to_include` in llm_eval Handler

**File**: `packages/darnit/src/darnit/sieve/builtin_handlers.py`

The spec (Section 3.5) defines `files_to_include` but the handler ignores it. Add file content reading before returning the consultation request.

- Read `config.get("files_to_include", [])`
- Resolve `$FOUND_FILE` → `context.gathered_evidence.get("found_file", "")`
- Read file contents (10KB limit per file, max 5 files)
- Include `file_contents` dict in the `consultation_request`

**Spec delta**: Section 3.5 gets a note that `$FOUND_FILE` is resolved from gathered evidence and file contents are included in the consultation request.

## 2. `llm_enhance` in Remediation Executor

**File**: `packages/darnit/src/darnit/remediation/executor.py`

After a successful `file_create` handler, propagate `llm_enhance` config to the result details. This is non-blocking metadata — the MCP layer can use it to offer AI-assisted customization of generated files.

- Check for `llm_enhance` key in handler config after successful execution
- Add `llm_enhance` dict (prompt + file_path) to result details
- Update `to_markdown()` to display enhancement suggestions

**Spec delta**: Section 4.2 gets `llm_enhance` as an optional field. New scenario: "WHEN a file_create handler has llm_enhance, THEN the remediation result MUST include the enhancement prompt in details."

## 3. Strengthened Regex Passes (8 Controls)

**File**: `packages/darnit-baseline/openssf-baseline.toml`

| Control | Current Pattern | Replacement Strategy |
|---------|----------------|---------------------|
| DO-01.01 | `(?i)^#` | Heading + 200+ chars of content |
| VM-02.01 | `security\|contact` | 3 patterns: reporting process, contact method, timeline |
| GV-01.01 | `maintainer\|governance` | Named person + decision process |
| GV-03.01 | `contribut\|pull request` | Steps + PR guidelines |
| LE-01.01 | `permission\|license` | Copyright + grant clause |
| GV-04.01 | (no content check) | Path assignment syntax (`*\s+@`) |
| BR-07.01 | 2 patterns | Add credential file patterns |
| DO-02.01 | Weak single pattern | Template structure markers |

## 4. New llm_eval Passes (5 Controls)

Each uses `files_to_include = ["$FOUND_FILE"]` with a targeted prompt:

| Control | Focus |
|---------|-------|
| DO-01.01 | Project explanation, install steps, usage examples |
| VM-02.01 | Actionable reporting instructions |
| GV-01.01 | Real governance vs. boilerplate |
| SA-01.01 | Real components and data flows |
| SA-02.01 | Actual endpoints/interfaces |

Pipeline becomes: `file_exists → strong regex → llm_eval → manual`

## 5. Template Rewrites (5 Templates)

| Template | Change |
|----------|--------|
| `readme_basic` | Real sections with placeholder descriptions instead of TODO comments |
| `architecture_template` | STRIDE-like table, example components, actors section |
| `threat_model_basic` (if exists) | STRIDE table with example threats |
| `changelog_template` (if exists) | Keep It Simple entry format |
| `governance_template` | Already decent — minor improvements |

Plus `llm_enhance` prompts on file_create handlers for DO-01.01, VM-02.01, GV-01.01, SA-01.01, SA-02.01.
