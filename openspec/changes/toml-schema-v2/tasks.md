# Implementation Tasks

## Pre-Commit Requirements

**MANDATORY before every commit:**

1. Run linting: `uv run ruff check .`
2. Run tests: `uv run pytest tests/ --ignore=tests/integration/ -q`
3. Fix any issues before committing

This ensures CI will pass and prevents broken commits from being pushed.

---

## 1. Phase 1: .project/ Integration

### 1.1 Core Parser

- [x] 1.1.1 Create `packages/darnit/src/darnit/context/dot_project.py` module
- [x] 1.1.2 Implement YAML parser for `.project/project.yaml` using ruamel.yaml
- [x] 1.1.3 Define dataclass/Pydantic models matching CNCF types.go struct
- [x] 1.1.4 Implement tolerant parsing (unknown fields preserved, not errored)
- [x] 1.1.5 Add validation for required fields (name, repositories)

### 1.2 Context Mapping

- [x] 1.2.1 Create context mapping from .project/ sections to sieve context variables
- [x] 1.2.2 Map `security` section → `project.security.*`
- [x] 1.2.3 Map `governance` section → `project.governance.*`
- [x] 1.2.4 Map maintainers → `project.maintainers`
- [x] 1.2.5 Inject .project/ context into sieve orchestrator

### 1.3 Write-Back

- [x] 1.3.1 Implement YAML writer that preserves comments (ruamel.yaml round-trip)
- [x] 1.3.2 Add `project_update` remediation action type
- [x] 1.3.3 Implement write-back for `security.policy.path` after SECURITY.md creation
- [x] 1.3.4 Implement write-back for `governance.codeowners.path` after CODEOWNERS creation
- [x] 1.3.5 Create .project/ directory and project.yaml if not exists

### 1.4 Upstream Tracking

- [x] 1.4.1 Create GitHub Action workflow for nightly .project/ spec check
- [x] 1.4.2 Implement hash comparison against cncf/automation types.go
- [x] 1.4.3 Auto-create issue when upstream changes detected
- [x] 1.4.4 Document targeted .project/ spec version in code (DOT_PROJECT_SPEC_VERSION)

### 1.5 Testing

- [x] 1.5.1 Add unit tests for .project/ parser
- [x] 1.5.2 Add unit tests for tolerant parsing of unknown fields
- [x] 1.5.3 Add unit tests for write-back with comment preservation
- [x] 1.5.4 Add integration test with real .project/ file

## 2. Phase 2: Context Collection

### 2.1 Schema Definition

- [x] 2.1.1 Add `[context]` section to framework_schema.py
- [x] 2.1.2 Define ContextVariable Pydantic model with all fields
- [x] 2.1.3 Support types: string, list[string], boolean, email
- [x] 2.1.4 Add validation for pattern constraints

### 2.2 Resolution Logic

- [x] 2.2.1 Create `packages/darnit/src/darnit/context/collection.py`
- [x] 2.2.2 Implement resolution priority: .project/ → file source → prompt
- [x] 2.2.3 Implement file parsers: markdown_list, yaml_path, json_path
- [x] 2.2.4 Implement user confirmation flow for auto-detected values

### 2.3 Prompt UI

- [x] 2.3.1 Add context prompt capability to MCP tools
- [x] 2.3.2 Implement multi-line input for list types
- [x] 2.3.3 Implement validation feedback (re-prompt on invalid input)
- [x] 2.3.4 Add --non-interactive flag to skip prompts (N/A for MCP tools - inherently interactive)

### 2.4 Persistence

- [x] 2.4.1 Implement save-to-.project/ for collected context
- [x] 2.4.2 Implement save-to-.baseline.toml for darnit-specific context
- [x] 2.4.3 Add user prompt "Save this value for future runs?" (handled by confirm_project_context flow)

### 2.5 Testing

- [x] 2.5.1 Add unit tests for context resolution priority
- [x] 2.5.2 Add unit tests for file parsers
- [x] 2.5.3 Add integration test for context flow into remediation

## 3. Phase 3: CEL Expressions

### 3.1 Dependencies

- [x] 3.1.1 Evaluate cel-python vs celpy libraries
- [x] 3.1.2 Add chosen CEL library to pyproject.toml
- [x] 3.1.3 Document CEL library choice and rationale

### 3.2 CEL Evaluator

- [x] 3.2.1 Create `packages/darnit/src/darnit/sieve/cel_evaluator.py`
- [x] 3.2.2 Implement CEL expression parsing and validation
- [x] 3.2.3 Implement sandboxed evaluation with timeout (1s limit)
- [ ] 3.2.4 Implement memory limiting

### 3.3 Context Variables

- [x] 3.3.1 Define standard CEL context variables (output, files, response, project, context)
- [x] 3.3.2 Implement output.stdout, output.stderr, output.exit_code, output.json for exec
- [x] 3.3.3 Implement response.status_code, response.body, response.headers for API
- [x] 3.3.4 Implement files, matches for pattern pass

### 3.4 Custom Functions

- [ ] 3.4.1 Implement `file_exists(path)` function
- [ ] 3.4.2 Implement `json_path(obj, path)` function
- [ ] 3.4.3 Register custom functions in CEL environment

### 3.5 Pass Integration

- [ ] 3.5.1 Add `expr` field to pass schema
- [ ] 3.5.2 Integrate CEL evaluator into exec pass
- [ ] 3.5.3 Integrate CEL evaluator into pattern pass
- [ ] 3.5.4 Integrate CEL evaluator into deterministic pass

### 3.6 Backward Compatibility

- [ ] 3.6.1 Keep old-style fields working (pass_if_json_path, etc.)
- [ ] 3.6.2 Add deprecation warnings with migration hints
- [ ] 3.6.3 Implement precedence: expr > old-style fields

### 3.7 Testing

- [x] 3.7.1 Add unit tests for CEL expression parsing
- [x] 3.7.2 Add unit tests for CEL sandboxing (timeout, no filesystem)
- [ ] 3.7.3 Add unit tests for custom functions
- [ ] 3.7.4 Add integration test comparing old-style vs CEL expression

## 4. Phase 4: Plugin System

### 4.1 Schema

- [ ] 4.1.1 Add `[plugins]` section to framework_schema.py
- [ ] 4.1.2 Define PluginConfig model with version constraints
- [ ] 4.1.3 Add allow_unsigned and trusted_publishers fields

### 4.2 Auto-Registration

- [ ] 4.2.1 Create `@register_handler` decorator
- [ ] 4.2.2 Create `@register_pass` decorator
- [ ] 4.2.3 Implement handler discovery on plugin load
- [ ] 4.2.4 Implement template discovery from plugin templates/ directory
- [ ] 4.2.5 Build handler registry keyed by short name

### 4.3 Plugin Resolution

- [ ] 4.3.1 Resolve handler references by short name from registry
- [ ] 4.3.2 Validate explicit module paths against whitelist
- [ ] 4.3.3 Add helpful error for missing handlers

### 4.4 Sigstore Integration

- [ ] 4.4.1 Add sigstore-python dependency
- [ ] 4.4.2 Implement signature verification for installed packages
- [ ] 4.4.3 Implement trusted_publishers verification
- [ ] 4.4.4 Implement graceful degradation when Sigstore unavailable
- [ ] 4.4.5 Cache verification results

### 4.5 Migration

- [ ] 4.5.1 Migrate darnit-baseline to use auto-registration
- [ ] 4.5.2 Sign darnit-baseline package with Sigstore
- [ ] 4.5.3 Update existing handler references to short names

### 4.6 Documentation

- [ ] 4.6.1 Document plugin security model
- [ ] 4.6.2 Document signing process for plugin authors
- [ ] 4.6.3 Add warning about arbitrary code execution

### 4.7 Testing

- [ ] 4.7.1 Add unit tests for auto-registration
- [ ] 4.7.2 Add unit tests for handler resolution
- [ ] 4.7.3 Add unit tests for Sigstore verification (mocked)
- [ ] 4.7.4 Add integration test with darnit-baseline plugin

## 5. Documentation & Cleanup

- [ ] 5.1 Update CLAUDE.md with new TOML schema sections
- [ ] 5.2 Update framework-design spec with final schema
- [ ] 5.3 Regenerate docs/generated/ from updated spec
- [ ] 5.4 Add migration guide for existing configs
- [ ] 5.5 Update README with new features
