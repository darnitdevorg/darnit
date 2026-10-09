# darnit-testchecks

The test-only plugin for [darnit](https://github.com/kusari-oss/darnit). The test suite uses it; it is not published and is not a template. To write a plugin, start from [`darnit-hello`](../darnit-hello/).

It provides two frameworks, both defined in TOML inside `src/darnit_testchecks/`:

- **`testchecks`** (`testchecks.toml`): 12 trivial controls across 3 levels, built only from built-in step types. The CLI and harness tests audit it.
- **`testchecks-steps`** (`testchecks-steps.toml`): 2 controls built on step types this package registers in `register_handlers()` (`testchecks_readme_description`, `testchecks_readme_quality`, `testchecks_ci_config`, in `handlers.py`). Tests use it as the plugin with custom step types.

It also provides in-memory store backends (`darnit_testchecks.stores`).

## Installation

It is in the workspace `dev` dependency group, so `uv sync` installs it.

## testchecks controls

### Level 1 - Basic Project Setup

| Control ID | Name | Description |
|------------|------|-------------|
| TEST-DOC-01 | HasReadme | Repository must have a README file |
| TEST-DOC-02 | HasChangelog | Repository should have a CHANGELOG file |
| TEST-LIC-01 | HasLicense | Repository must have a LICENSE file |
| TEST-IGN-01 | HasGitignore | Repository should have a .gitignore file |

### Level 2 - Code Quality

| Control ID | Name | Description |
|------------|------|-------------|
| TEST-QA-01 | NoTodoComments | Code should not contain TODO comments |
| TEST-QA-02 | NoPrintStatements | Python code should use logging, not print() |
| TEST-CFG-01 | HasEditorConfig | Repository should have .editorconfig |
| TEST-CFG-02 | HasPreCommitConfig | Repository should have pre-commit hooks |

### Level 3 - Security & CI

| Control ID | Name | Description |
|------------|------|-------------|
| TEST-SEC-01 | NoHardcodedPasswords | No hardcoded secrets in code |
| TEST-SEC-02 | GitignoreSecrets | .gitignore excludes secret files |
| TEST-CI-01 | HasCIConfig | Repository has CI/CD configuration |
| TEST-CI-02 | CIRunsTests | CI configuration runs tests |

## Usage

### Loading the Framework

```python
from darnit_testchecks import get_framework_path
from darnit.config.merger import load_framework_config

framework = load_framework_config(get_framework_path())
print(f"Loaded {len(framework.controls)} controls")
```

### Selecting the Framework and Claiming Controls Not Applicable

Select this framework per run:

```bash
darnit audit --framework testchecks /path/to/repo
```

A project claims a control is not applicable in `.project/darnit.yaml`. The
claim counts only when the operator trusts the repository and no evidence
contradicts it, or after the operator confirms it:

```yaml
controls:
  TEST-QA-01:
    status: n/a
    reason: TODOs are acceptable in this project
```

## License

Apache-2.0
