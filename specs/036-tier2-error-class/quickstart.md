# Quickstart: Telling "couldn't verify" apart from "verified and failed"

**Feature**: 036-tier2-error-class

Three walkthroughs an operator can run to see the difference this feature makes.

## Example 1: Expired auth token

The most common real-world case. Your `GH_TOKEN` expired; controls that hit the GitHub API can't complete.

**Before this feature**:

```bash
$ darnit audit ~/src/my-project -t level=1
[...]
--- Failures ---
  x OSPS-LE-02.02: FAIL - Command failed (exit 1)
  x OSPS-BR-03.01: FAIL - Command failed (exit 1)
  x OSPS-QA-04.01: FAIL - Pattern not found in any file
```

Three failures that look identical. You start editing the repo. Two of them were never about the repo.

**After this feature**:

```bash
$ darnit audit ~/src/my-project -t level=1
WARNING  exec handler failed for OSPS-LE-02.02: error_class=auth
WARNING  exec handler failed for OSPS-BR-03.01: error_class=auth
[...]
--- Failures ---
  x OSPS-LE-02.02: FAIL [auth] - Command failed (exit 1)
  x OSPS-BR-03.01: FAIL [auth] - Command failed (exit 1)
  x OSPS-QA-04.01: FAIL - Pattern not found in any file
```

The `[auth]` annotation and the WARN lines say: fix your token, not your repo. `OSPS-QA-04.01` has no annotation -- that one is a real finding.

**Reproduce it**:

```bash
$ GH_TOKEN=invalid_token_value darnit audit ~/src/my-project -t level=1
```

## Example 2: Rate limit

Running darnit across a fleet, or repeatedly during development, exhausts the GitHub API budget (5000 req/hr authenticated, 60 unauthenticated, plus a separate secondary limit on burst).

```bash
$ for repo in ~/src/*/; do darnit audit "$repo" -t level=1; done
[... first several repos audit cleanly ...]
WARNING  exec handler failed for OSPS-LE-02.02: error_class=rate_limit
WARNING  exec handler failed for OSPS-BR-03.01: error_class=rate_limit
```

`rate_limit` is distinguished from `auth` even though GitHub returns 403 for both -- the classifier checks rate-limit stderr patterns first, so the more specific signal wins.

**Operator action**: wait for the window to reset, or authenticate with a token that has a higher budget. Not: edit fifteen repos.

## Example 3: Machine consumption in CI

Parse the JSON output and split "environment problems" from "repo problems" so your CI summary doesn't blame the repo for a network outage.

```bash
$ darnit audit . -t level=1 -o json > audit.json
```

```python
import json

results = json.load(open("audit.json"))["results"]

repo_problems = [r for r in results
                 if r["status"] in ("FAIL", "WARN") and "error_class" not in r]
env_problems  = [r for r in results if "error_class" in r]

print(f"Repo findings: {len(repo_problems)}")
for r in repo_problems:
    print(f"  {r['id']}: {r['details']}")

if env_problems:
    by_class: dict[str, list[str]] = {}
    for r in env_problems:
        by_class.setdefault(r["error_class"], []).append(r["id"])
    print(f"\nEnvironment problems ({len(env_problems)} controls could not be verified):")
    for cls, ids in sorted(by_class.items()):
        print(f"  {cls}: {', '.join(ids)}")
```

Output on a run with an expired token:

```text
Repo findings: 1
  OSPS-QA-04.01: Pattern not found in any file

Environment problems (2 controls could not be verified):
  auth: OSPS-LE-02.02, OSPS-BR-03.01
```

A CI job can now fail loudly on `env_problems` with a "fix your runner config" message, distinct from the "fix your repo" message for `repo_problems`.

## SARIF and attestation

The same field flows into the other two surfaces:

**SARIF** -- for code-scanning integrations:

```json
{
  "ruleId": "OSPS-LE-02.02",
  "level": "error",
  "properties": {
    "resolvingPassHandler": "exec",
    "resolvingPassIndex": 0,
    "errorClass": "auth"
  }
}
```

**Attestation predicate** -- so a later verifier can see the audit ran under degraded conditions:

```json
{
  "id": "OSPS-LE-02.02",
  "level": 1,
  "category": "LE",
  "status": "FAIL",
  "message": "Command failed (exit 1)",
  "source": "builtin",
  "authority": "dispositive",
  "error_class": "auth"
}
```

This is the case that matters most for compliance. A signed attestation claiming `FAIL` without recording that the check never actually reached GitHub is a misleading claim -- exactly what Constitution Principle II forbids.

## Happy-path check

Confirm the feature is silent when nothing goes wrong:

```bash
$ darnit audit ~/src/my-project -t level=1 -o json > with-feature.json
# Compare against a pre-feature run of the same commit
$ diff pre-feature.json with-feature.json
# (no output -- byte-for-byte identical)
```

No `error_class` keys appear anywhere when every check ran to completion. That invariance is what FR-014 / SC-002 lock via golden-file regression.
