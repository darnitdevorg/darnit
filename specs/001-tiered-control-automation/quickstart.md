# Quickstart: Adding Automated Passes to a Control

This guide shows how to convert a manual-only control to use
cascading automated passes.

## Example: Adding file_must_exist to a documentation control

**Before** (manual only):
```toml
[[controls."OSPS-DO-01.01".passes]]
handler = "manual"
description = "Verify README exists"
verification_steps = [
    "Check for README.md in the repository root",
    "Verify it contains project description"
]
```

**After** (deterministic → heuristic → manual fallback):
```toml
# Pass 1: Deterministic — does the file exist?
[[controls."OSPS-DO-01.01".passes]]
handler = "file_must_exist"
description = "Check for README file"
files = ["README.md", "README.rst", "README.txt", "README"]

# Pass 2: Heuristic — does it have meaningful content?
[[controls."OSPS-DO-01.01".passes]]
handler = "pattern"
description = "Verify README has project description"
file_patterns = ["README*"]
patterns = ["(?i)(description|overview|about|introduction)"]
expr = 'output.any_match'

# Pass 3: Manual fallback — human verification
[[controls."OSPS-DO-01.01".passes]]
handler = "manual"
description = "Verify README adequately describes the project"
verification_steps = [
    "Check README contains project description",
    "Verify it includes basic usage instructions"
]
```

## Example: Adding LLM evaluation for content quality

For controls that need to assess whether a document adequately
covers a topic:

```toml
# Pass 1: Deterministic — does the file exist?
[[controls."OSPS-SA-01.01".passes]]
handler = "file_must_exist"
description = "Check for design documentation"
files = ["docs/ARCHITECTURE.md", "docs/DESIGN.md", "ARCHITECTURE.md"]

# Pass 2: Heuristic — does it mention architecture keywords?
[[controls."OSPS-SA-01.01".passes]]
handler = "pattern"
description = "Check for architecture keywords"
file_patterns = ["docs/*.md", "*.md"]
patterns = ["(?i)(architecture|design|component|module|system)"]
expr = 'output.any_match'

# Pass 3: LLM — does it adequately explain the design?
[[controls."OSPS-SA-01.01".passes]]
handler = "llm_eval"
description = "Evaluate design documentation quality"
prompt = "Does this document adequately explain the system architecture and design decisions? Look for: component descriptions, interaction patterns, and rationale for key decisions."

# Pass 4: Manual fallback
[[controls."OSPS-SA-01.01".passes]]
handler = "manual"
description = "Verify design documentation quality"
verification_steps = [
    "Check document explains system architecture",
    "Verify design decisions are documented with rationale"
]
```

## Key Rules

1. **Order matters**: Passes execute in TOML declaration order.
   Put cheapest/most-deterministic first, most-expensive/least-
   certain last.

2. **INCONCLUSIVE continues**: If a pass cannot determine the
   result, it returns INCONCLUSIVE and the next pass runs.
   Only PASS, FAIL, or ERROR stop the cascade.

3. **CEL post-evaluation**: Any pass can include an `expr` field.
   The CEL expression runs after the handler and can override
   the result. `true` → PASS, `false` → INCONCLUSIVE.

4. **Manual is always last**: Manual passes always return
   INCONCLUSIVE (displayed as WARN). They document what a human
   should check but never produce a conclusive result.

5. **Conservative by default**: When in doubt, return INCONCLUSIVE
   and let the next pass (or manual fallback) handle it. Never
   promote an uncertain result to PASS.

## Confidence Configuration

To configure how aggressively context fields are auto-accepted:

```toml
[config]
auto_accept_confidence = 0.8  # Accept fields with confidence >= 0.8

[config.context.maintainers]
auto_detect = true
confidence = 0.9  # CODEOWNERS is a canonical source

[config.context.governance_model]
auto_detect = true
confidence = 0.4  # Heuristic — will prompt user
```

Set `auto_accept_confidence = 1.0` to require manual confirmation
for every auto-detected field.

## Verifying Your Changes

After adding new passes:

```bash
# Run the audit and check that the control now resolves
uv run darnit audit /path/to/repo --level 1

# Verify the control produces PASS or FAIL (not WARN)
# Check that resolving_pass_handler shows your new handler

# Run tests
uv run pytest tests/ --ignore=tests/integration/ -q

# Validate TOML sync
uv run python scripts/validate_sync.py --verbose
```
