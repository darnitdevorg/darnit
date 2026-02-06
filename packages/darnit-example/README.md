# darnit-example

A working example of a [darnit](../darnit/) compliance plugin that implements a
simple "Project Hygiene Standard" with 8 controls across 2 maturity levels.

This package is the companion reference implementation for
[docs/IMPLEMENTATION_GUIDE.md](../../docs/IMPLEMENTATION_GUIDE.md). Every pattern
described in that guide has a concrete counterpart here.

## Controls

### Level 1 — Basic Project Setup (6 controls)

| ID | Name | Defined In | Description |
|----|------|-----------|-------------|
| `PH-DOC-01` | ReadmeExists | TOML | Project has a README file |
| `PH-DOC-02` | LicenseExists | TOML | Project has a LICENSE file |
| `PH-DOC-03` | ReadmeHasDescription | Python | README contains a description |
| `PH-SEC-01` | SecurityPolicyExists | TOML | Project has a security policy |
| `PH-CFG-01` | GitignoreExists | TOML | Project has a .gitignore |
| `PH-CFG-02` | EditorConfigExists | TOML | Project has an .editorconfig |

### Level 2 — Quality Practices (2 controls)

| ID | Name | Defined In | Description |
|----|------|-----------|-------------|
| `PH-QA-01` | ContributingGuideExists | TOML | Project has a CONTRIBUTING guide |
| `PH-CI-01` | CIConfigExists | Python | Project has CI/CD configuration |

## Mapping to IMPLEMENTATION_GUIDE.md

| Guide Section | Example File |
|--------------|-------------|
| Step 1: Package skeleton | `pyproject.toml`, `src/darnit_example/__init__.py` |
| Step 2: Implementation class | `src/darnit_example/implementation.py` |
| Step 3: TOML config | `example-hygiene.toml` |
| Step 4: Python controls | `src/darnit_example/controls/level1.py` |
| Step 5: Remediation | `src/darnit_example/remediation/` |
| Step 6: Handler registration | `src/darnit_example/tools.py` |
| Step 7: Testing | `tests/darnit_example/` |

## Design Choices

- **6 TOML + 2 Python controls** — shows that most checks need no Python code
- **PH-SEC-01 has 3 pass types** — demonstrates the multi-phase sieve
  (deterministic → pattern → manual)
- **PH-DOC-03 uses a custom analyzer** — shows factory function pattern
- **PH-CI-01 uses glob patterns** — shows dynamic file matching in Python
- **No API checks** — keeps the example runnable offline

## Running Tests

```bash
# From the repository root
uv run pytest tests/darnit_example/ -v
```
