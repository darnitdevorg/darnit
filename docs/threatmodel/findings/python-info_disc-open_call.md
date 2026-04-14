# File open with variable path: filepath

**STRIDE category:** Information Disclosure
**Rule ID:** `python.info_disc.open_call`
**Max severity:** MEDIUM

## Mitigation

No specific guidance available.

## Representative Examples

<details>
<summary><code>docs/examples/python-framework/example_framework/implementation.py:175</code></summary>

```
     165 |         "private_key": r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----",
     166 |         "api_token": r"(api[_-]?key|api[_-]?token|access[_-]?token)\s*[=:]\s*['\"][a-zA-Z0-9]{20,}",
     167 |     }
     168 | 
     169 |     code_extensions = ["*.py", "*.js", "*.ts", "*.go", "*.java"]
     170 |     secrets_found = []
     171 | 
     172 |     for ext in code_extensions:
     173 |         for filepath in glob.glob(os.path.join(local_path, "**", ext), recursive=True):
     174 |             try:
>>>  175 |                 with open(filepath, encoding="utf-8", errors="ignore") as f:
     176 |                     content = f.read()
     177 |                 for pattern_name, pattern in secret_patterns.items():
     178 |                     if re.search(pattern, content):
     179 |                         secrets_found.append({
     180 |                             "file": filepath,
     181 |                             "pattern": pattern_name,
     182 |                         })
     183 |             except OSError:
     184 |                 continue
     185 | 
```

*``open(filepath)`` uses a variable path. If the path originates from user input without validation, this enables path traversal attacks (reading arbitrary files).*

</details>

<details>
<summary><code>docs/examples/python-framework/example_framework/implementation.py:495</code></summary>

```
     485 | """
     486 | 
     487 |     filepath = os.path.join(local_path, "README.md")
     488 | 
     489 |     if dry_run:
     490 |         return f"Would create: {filepath}"
     491 | 
     492 |     if os.path.exists(filepath):
     493 |         return f"File already exists: {filepath}"
     494 | 
>>>  495 |     with open(filepath, "w") as f:
     496 |         f.write(content)
     497 | 
     498 |     return f"Created: {filepath}"
     499 | 
     500 | 
     501 | def create_changelog(
     502 |     local_path: str,
     503 |     dry_run: bool = True,
     504 | ) -> str:
     505 |     """Create CHANGELOG.md file."""
```

*``open(filepath)`` uses a variable path. If the path originates from user input without validation, this enables path traversal attacks (reading arbitrary files).*

</details>

<details>
<summary><code>docs/examples/python-framework/example_framework/implementation.py:540</code></summary>

```
     530 | """
     531 | 
     532 |     filepath = os.path.join(local_path, "CHANGELOG.md")
     533 | 
     534 |     if dry_run:
     535 |         return f"Would create: {filepath}"
     536 | 
     537 |     if os.path.exists(filepath):
     538 |         return f"File already exists: {filepath}"
     539 | 
>>>  540 |     with open(filepath, "w") as f:
     541 |         f.write(content)
     542 | 
     543 |     return f"Created: {filepath}"
     544 | 
     545 | 
     546 | def create_codeowners(
     547 |     local_path: str,
     548 |     owner: str,
     549 |     dry_run: bool = True,
     550 | ) -> str:
```

*``open(filepath)`` uses a variable path. If the path originates from user input without validation, this enables path traversal attacks (reading arbitrary files).*

</details>

## All Instances

| # | File | Line | Severity | Confidence | Status |
|---|------|------|----------|------------|--------|
| 1 | `docs/examples/python-framework/example_framework/implementation.py` | 175 | MEDIUM | 0.40 | Unmitigated |
| 2 | `docs/examples/python-framework/example_framework/implementation.py` | 495 | MEDIUM | 0.40 | Unmitigated |
| 3 | `docs/examples/python-framework/example_framework/implementation.py` | 540 | MEDIUM | 0.40 | Unmitigated |
| 4 | `docs/examples/python-framework/example_framework/implementation.py` | 571 | MEDIUM | 0.40 | Unmitigated |
| 5 | `scripts/validate_sync.py` | 58 | MEDIUM | 0.40 | Unmitigated |
| 6 | `packages/darnit-baseline/src/darnit_baseline/implementation.py` | 103 | MEDIUM | 0.40 | Unmitigated |
| 7 | `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` | 301 | MEDIUM | 0.40 | Unmitigated |
| 8 | `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` | 394 | MEDIUM | 0.40 | Unmitigated |
| 9 | `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` | 401 | MEDIUM | 0.40 | Unmitigated |
| 10 | `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` | 415 | MEDIUM | 0.40 | Unmitigated |
| 11 | `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py` | 428 | MEDIUM | 0.40 | Unmitigated |
| 12 | `packages/darnit-baseline/src/darnit_baseline/threat_model/dependencies.py` | 192 | MEDIUM | 0.40 | Unmitigated |
| 13 | `packages/darnit-baseline/src/darnit_baseline/attestation/generator.py` | 134 | MEDIUM | 0.40 | Unmitigated |
| 14 | `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py` | 132 | MEDIUM | 0.40 | Unmitigated |
| 15 | `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py` | 510 | MEDIUM | 0.40 | Unmitigated |
| 16 | `packages/darnit/src/darnit/context/dot_project.py` | 348 | MEDIUM | 0.40 | Unmitigated |
| 17 | `packages/darnit/src/darnit/context/dot_project.py` | 389 | MEDIUM | 0.40 | Unmitigated |
| 18 | `packages/darnit/src/darnit/context/dot_project.py` | 849 | MEDIUM | 0.40 | Unmitigated |
| 19 | `packages/darnit/src/darnit/context/dot_project.py` | 862 | MEDIUM | 0.40 | Unmitigated |
| 20 | `packages/darnit/src/darnit/core/verification.py` | 221 | MEDIUM | 0.40 | Unmitigated |
| 21 | `packages/darnit/src/darnit/core/verification.py` | 296 | MEDIUM | 0.40 | Unmitigated |
| 22 | `packages/darnit/src/darnit/core/utils.py` | 337 | MEDIUM | 0.40 | Unmitigated |
| 23 | `packages/darnit/src/darnit/core/utils.py` | 351 | MEDIUM | 0.40 | Unmitigated |
| 24 | `packages/darnit/src/darnit/core/audit_cache.py` | 170 | MEDIUM | 0.40 | Unmitigated |
| 25 | `packages/darnit/src/darnit/config/discovery.py` | 82 | MEDIUM | 0.40 | Unmitigated |
| 26 | `packages/darnit/src/darnit/config/discovery.py` | 144 | MEDIUM | 0.40 | Unmitigated |
| 27 | `packages/darnit/src/darnit/config/discovery.py` | 156 | MEDIUM | 0.40 | Unmitigated |
| 28 | `packages/darnit/src/darnit/config/discovery.py` | 168 | MEDIUM | 0.40 | Unmitigated |
| 29 | `packages/darnit/src/darnit/config/discovery.py` | 179 | MEDIUM | 0.40 | Unmitigated |
| 30 | `packages/darnit/src/darnit/config/loader.py` | 137 | MEDIUM | 0.40 | Unmitigated |
| 31 | `packages/darnit/src/darnit/config/loader.py` | 234 | MEDIUM | 0.40 | Unmitigated |
| 32 | `packages/darnit/src/darnit/config/merger.py` | 425 | MEDIUM | 0.40 | Unmitigated |
| 33 | `packages/darnit/src/darnit/config/merger.py` | 447 | MEDIUM | 0.40 | Unmitigated |
| 34 | `packages/darnit/src/darnit/server/factory.py` | 122 | MEDIUM | 0.40 | Unmitigated |
| 35 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 58 | MEDIUM | 0.40 | Unmitigated |
| 36 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 70 | MEDIUM | 0.40 | Unmitigated |
| 37 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 78 | MEDIUM | 0.40 | Unmitigated |
| 38 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 395 | MEDIUM | 0.40 | Unmitigated |
| 39 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 486 | MEDIUM | 0.40 | Unmitigated |
| 40 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 565 | MEDIUM | 0.40 | Unmitigated |
| 41 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 677 | MEDIUM | 0.40 | Unmitigated |
| 42 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 711 | MEDIUM | 0.40 | Unmitigated |
| 43 | `packages/darnit/src/darnit/remediation/github.py` | 53 | MEDIUM | 0.40 | Unmitigated |
| 44 | `packages/darnit/src/darnit/remediation/helpers.py` | 53 | MEDIUM | 0.40 | Unmitigated |
| 45 | `packages/darnit/src/darnit/remediation/executor.py` | 364 | MEDIUM | 0.40 | Unmitigated |
| 46 | `packages/darnit-example/src/darnit_example/tools.py` | 89 | MEDIUM | 0.40 | Unmitigated |
| 47 | `packages/darnit-example/src/darnit_example/handlers.py` | 35 | MEDIUM | 0.40 | Unmitigated |
| 48 | `packages/darnit-example/src/darnit_example/handlers.py` | 85 | MEDIUM | 0.40 | Unmitigated |

*48 instances total.*

