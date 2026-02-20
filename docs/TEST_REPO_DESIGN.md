# OpenSSF Baseline Test Repository Design

## Quick Start

**MCP Tool (Recommended):**
```python
# Create local + GitHub repo
create_test_repository(repo_name="my-test-repo")

# Create as a template you can copy
create_test_repository(repo_name="baseline-template", make_template=True)

# Local only (no GitHub)
create_test_repository(repo_name="local-test", create_github=False)
```

**Shell Script:**
```bash
./scripts/create-test-repo.sh my-test-repo          # Local + GitHub
./scripts/create-test-repo.sh my-test-repo myorg true true  # As template
```

---

## Purpose

This document describes a **minimal test repository** that intentionally fails all OpenSSF Baseline controls, making it easy to:

1. Run audits and see failures clearly
2. Implement fixes one-by-one to learn the requirements
3. Track progress from 0% to 100% compliance
4. Test the baseline-mcp tooling

## Design Philosophy

**Start with nothing, add everything.**

The test repo should be a functional project (builds and runs) but have zero security/governance artifacts. This lets you:
- See exactly what's missing
- Add each requirement incrementally
- Understand why each control matters

---

## Test Repository Specification

### Project Type: Simple Node.js CLI Tool

A minimal "hello world" CLI that:
- Has real code (so it's not just empty)
- Uses dependencies (to test dependency controls)
- Can actually run (proves it's a real project)

### Initial State (Intentionally Non-Compliant)

```
baseline-test-repo/
├── src/
│   └── index.js          # Main code
├── package.json          # Minimal, no metadata
└── .git/                 # Git initialized
```

**That's it.** No README, no LICENSE, no SECURITY.md, no CI, nothing.

---

## What Will Fail (All 62 Controls)

### Level 1 Failures (24 controls)

| Control | What's Missing |
|---------|----------------|
| OSPS-AC-01.01 | No org MFA requirement |
| OSPS-AC-02.01 | No permission settings |
| OSPS-AC-03.01 | No branch protection (direct commits allowed) |
| OSPS-AC-03.02 | No branch protection (deletion allowed) |
| OSPS-BR-01.01 | No CI workflows |
| OSPS-BR-01.02 | No CI workflows |
| OSPS-BR-03.01 | N/A or passes (no URLs to check) |
| OSPS-BR-03.02 | N/A or passes (no URLs to check) |
| OSPS-BR-07.01 | No .gitignore |
| OSPS-DO-01.01 | **No README.md** |
| OSPS-DO-02.01 | No issue templates |
| OSPS-GV-02.01 | Issues may be disabled |
| OSPS-GV-03.01 | **No CONTRIBUTING.md** |
| OSPS-LE-02.01 | **No LICENSE** |
| OSPS-LE-02.02 | No LICENSE in releases |
| OSPS-LE-03.01 | **No LICENSE file** |
| OSPS-LE-03.02 | No releases |
| OSPS-QA-01.01 | Repo is public (passes if public) |
| OSPS-QA-01.02 | Git history exists (passes) |
| OSPS-QA-02.01 | Has package.json (passes) |
| OSPS-QA-04.01 | N/A (single project) |
| OSPS-QA-05.01 | No .gitignore for binaries |
| OSPS-QA-05.02 | No .gitignore for binaries |
| OSPS-VM-02.01 | **No SECURITY.md** |

### Level 2 Failures (18 controls)

| Control | What's Missing |
|---------|----------------|
| OSPS-AC-04.01 | No CI workflows with permissions |
| OSPS-BR-02.01 | No releases |
| OSPS-BR-04.01 | No releases |
| OSPS-BR-05.01 | **No lockfile** |
| OSPS-BR-06.01 | No signed releases |
| OSPS-DO-06.01 | No DEPENDENCIES.md |
| OSPS-GV-01.01 | No GOVERNANCE.md/MAINTAINERS.md |
| OSPS-GV-01.02 | No governance docs |
| OSPS-GV-03.02 | No CONTRIBUTING.md with requirements |
| OSPS-LE-01.01 | No DCO/CLA requirement |
| OSPS-QA-03.01 | No branch protection |
| OSPS-QA-06.01 | No automated tests |
| OSPS-SA-01.01 | No ARCHITECTURE.md |
| OSPS-SA-02.01 | No API docs |
| OSPS-SA-03.01 | No security assessment |
| OSPS-VM-01.01 | No CVD policy |
| OSPS-VM-03.01 | No private reporting |
| OSPS-VM-04.01 | No security advisories |

### Level 3 Failures (19 controls)

| Control | What's Missing |
|---------|----------------|
| OSPS-AC-04.02 | No minimal CI permissions |
| OSPS-BR-02.02 | No releases |
| OSPS-BR-07.02 | No secrets management policy |
| OSPS-DO-03.01 | No verification instructions |
| OSPS-DO-03.02 | No author verification |
| OSPS-DO-04.01 | No SUPPORT.md |
| OSPS-DO-05.01 | No EOL notice |
| OSPS-GV-04.01 | No collaborator review policy |
| OSPS-QA-02.02 | No SBOM |
| OSPS-QA-04.02 | N/A (single project) |
| OSPS-QA-06.02 | No test documentation |
| OSPS-QA-06.03 | No test policy |
| OSPS-QA-07.01 | No branch protection |
| OSPS-SA-03.02 | No threat model |
| OSPS-VM-04.02 | No VEX policy |
| OSPS-VM-05.01 | No SCA policy |
| OSPS-VM-05.02 | No SCA in CI |
| OSPS-VM-05.03 | No dependency scanning |
| OSPS-VM-06.01 | No SAST policy |
| OSPS-VM-06.02 | No SAST in CI |

---

## Implementation Guide: Zero to Hero

### Phase 1: Quick Wins (Level 1 Files)

These can be added in minutes:

```bash
# 1. Add LICENSE (MIT is easiest)
# Creates: LICENSE
# Fixes: OSPS-LE-02.01, OSPS-LE-03.01

# 2. Add README.md
# Creates: README.md
# Fixes: OSPS-DO-01.01

# 3. Add SECURITY.md
# Creates: SECURITY.md
# Fixes: OSPS-VM-02.01

# 4. Add CONTRIBUTING.md
# Creates: CONTRIBUTING.md
# Fixes: OSPS-GV-03.01

# 5. Add .gitignore
# Creates: .gitignore
# Fixes: OSPS-BR-07.01, OSPS-QA-05.01, OSPS-QA-05.02

# 6. Generate lockfile
npm install  # Creates package-lock.json
# Fixes: OSPS-BR-05.01
```

**After Phase 1: ~10-15 controls pass**

### Phase 2: Enhanced Documentation (Level 2)

```bash
# 7. Add GOVERNANCE.md or MAINTAINERS.md
# Fixes: OSPS-GV-01.01, OSPS-GV-01.02

# 8. Enhance CONTRIBUTING.md with requirements
# Fixes: OSPS-GV-03.02

# 9. Add docs/ARCHITECTURE.md
# Fixes: OSPS-SA-01.01

# 10. Add docs/API.md or openapi.yaml
# Fixes: OSPS-SA-02.01

# 11. Add DEPENDENCIES.md
# Fixes: OSPS-DO-06.01

# 12. Enhance SECURITY.md with CVD policy
# Fixes: OSPS-VM-01.01, OSPS-VM-03.01, OSPS-SA-03.01
```

**After Phase 2: ~25-30 controls pass**

### Phase 3: CI/CD Setup (Level 2-3)

```yaml
# 13. Add .github/workflows/ci.yml
# - Explicit permissions block
# - Automated tests
# - Input sanitization
# Fixes: OSPS-AC-04.01, OSPS-QA-06.01, OSPS-BR-01.01, OSPS-BR-01.02

# 14. Add .github/workflows/security.yml
# - CodeQL or Semgrep (SAST)
# - npm audit or similar (SCA)
# Fixes: OSPS-VM-05.02, OSPS-VM-05.03, OSPS-VM-06.02

# 15. Add .github/dependabot.yml
# Fixes: OSPS-VM-05.03
```

**After Phase 3: ~40 controls pass**

### Phase 4: GitHub Settings (Requires API/UI)

```bash
# 16. Enable branch protection
# - Require PRs
# - Require status checks
# - Require approvals
# - Prevent deletion
# Fixes: OSPS-AC-03.01, OSPS-AC-03.02, OSPS-QA-03.01, OSPS-QA-07.01

# 17. Enable security advisories
# Fixes: OSPS-VM-04.01

# 18. Enable issues (if disabled)
# Fixes: OSPS-GV-02.01
```

**After Phase 4: ~50 controls pass**

### Phase 5: Advanced Requirements (Level 3)

```bash
# 19. Add SUPPORT.md
# Fixes: OSPS-DO-04.01, OSPS-DO-05.01

# 20. Add docs/THREAT_MODEL.md
# Fixes: OSPS-SA-03.02

# 21. Enhance SECURITY.md with policies
# - Secrets management
# - SCA remediation policy
# - SAST remediation policy
# - VEX policy
# Fixes: OSPS-BR-07.02, OSPS-VM-04.02, OSPS-VM-05.01, OSPS-VM-06.01

# 22. Add verification docs
# - How to verify releases
# - How to verify authors
# Fixes: OSPS-DO-03.01, OSPS-DO-03.02

# 23. Add DCO requirement
# - .github/dco.yml or mention in CONTRIBUTING.md
# Fixes: OSPS-LE-01.01
```

**After Phase 5: ~55+ controls pass**

### Phase 6: Releases (Complete Compliance)

```bash
# 24. Create a release with:
# - Signed artifacts or checksums
# - SBOM
# - LICENSE included
# - Release notes
# Fixes: OSPS-BR-02.01, OSPS-BR-02.02, OSPS-BR-04.01,
#        OSPS-BR-06.01, OSPS-LE-02.02, OSPS-LE-03.02, OSPS-QA-02.02
```

**After Phase 6: 62/62 controls (100%)**

---

## Repository Generator Script

```bash
#!/bin/bash
# generate-test-repo.sh
# Creates a minimal non-compliant test repository

REPO_NAME="${1:-baseline-test-repo}"

mkdir -p "$REPO_NAME/src"
cd "$REPO_NAME"

# Initialize git
git init

# Minimal package.json (no description, no license field)
cat > package.json << 'EOF'
{
  "name": "baseline-test",
  "version": "0.0.1",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js"
  },
  "dependencies": {
    "chalk": "^4.1.2"
  }
}
EOF

# Minimal code
cat > src/index.js << 'EOF'
const chalk = require('chalk');

console.log(chalk.green('Hello from baseline-test!'));
console.log('This repo intentionally has no security controls.');
console.log('Run an audit to see what is missing.');
EOF

# Initial commit
git add .
git commit -m "Initial commit - intentionally non-compliant"

echo ""
echo "Created $REPO_NAME"
echo "Run: cd $REPO_NAME && npm install && npm start"
echo ""
echo "Then run OpenSSF Baseline audit to see failures:"
echo "  audit_openssf_baseline(local_path='$(pwd)')"
```

---

## Tracking Progress

Use the baseline-mcp audit to track progress:

```python
# Run audit after each phase
audit_openssf_baseline(
    local_path="/path/to/baseline-test-repo",
    level=3,
    output_format="markdown"
)
```

The audit will show:
- Which controls pass/fail
- What's needed to fix failures
- Compliance percentage at each level

---

## Alternative: Python Test Repo

If you prefer Python:

```
baseline-test-repo/
├── src/
│   └── main.py           # print("Hello")
├── pyproject.toml        # Minimal config
└── .git/
```

```toml
# pyproject.toml
[project]
name = "baseline-test"
version = "0.0.1"
dependencies = ["requests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## Summary

| Phase | Controls Fixed | Cumulative |
|-------|---------------|------------|
| Initial | 0 | 0/61 |
| Phase 1 (Files) | ~15 | ~15/61 |
| Phase 2 (Docs) | ~10 | ~25/62 |
| Phase 3 (CI) | ~10 | ~35/62 |
| Phase 4 (GitHub) | ~10 | ~45/62 |
| Phase 5 (Advanced) | ~10 | ~55/62 |
| Phase 6 (Releases) | ~6 | 62/62 |

This gives you a clear path from 0% to 100% compliance with measurable progress at each step.
