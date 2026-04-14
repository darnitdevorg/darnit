# Potential command injection via subprocess.run

**STRIDE category:** Tampering
**Rule ID:** `python.sink.dangerous_attr`
**Max severity:** HIGH

## Mitigation

No specific guidance available.

## Representative Examples

<details>
<summary><code>packages/darnit/src/darnit/core/adapters.py:231</code></summary>

```
     221 |             # Add any extra config
     222 |             for key, value in config.items():
     223 |                 if isinstance(value, bool):
     224 |                     if value:
     225 |                         cmd.append(f"--{key}")
     226 |                 else:
     227 |                     cmd.extend([f"--{key}", str(value)])
     228 | 
     229 |             logger.debug(f"Running command: {' '.join(cmd)}")
     230 | 
>>>  231 |             result = subprocess.run(
     232 |                 cmd,
     233 |                 capture_output=True,
     234 |                 text=True,
     235 |                 timeout=self._timeout,
     236 |             )
     237 | 
     238 |             if self._output_format == "json":
     239 |                 try:
     240 |                     output = json.loads(result.stdout)
     241 |                     return CheckResult(
```

*[subprocess/dynamic] Entire command built dynamically — highest injection risk without taint confirmation. Command argument is populated from configuration/dict lookup within the same function scope. Opengrep taint analysis will lift confirmed cases to high confidence.*

</details>

<details>
<summary><code>packages/darnit/src/darnit/sieve/builtin_handlers.py:137</code></summary>

```
     127 |     for arg in command:
     128 |         for var, val in substitutions.items():
     129 |             arg = arg.replace(var, val)
     130 |         resolved_cmd.append(arg)
     131 | 
     132 |     # Build environment
     133 |     env = os.environ.copy()
     134 |     env.update(env_extra)
     135 | 
     136 |     try:
>>>  137 |         proc = subprocess.run(
     138 |             resolved_cmd,
     139 |             capture_output=True,
     140 |             text=True,
     141 |             timeout=timeout,
     142 |             cwd=cwd,
     143 |             env=env,
     144 |         )
     145 |     except subprocess.TimeoutExpired:
     146 |         return HandlerResult(
     147 |             status=HandlerResultStatus.ERROR,
```

*[subprocess/dynamic] Entire command built dynamically — highest injection risk without taint confirmation. Command argument is populated from configuration/dict lookup within the same function scope. Opengrep taint analysis will lift confirmed cases to high confidence.*

</details>

<details>
<summary><code>packages/darnit-plugins/src/darnit_plugins/adapters/kusari.py:253</code></summary>

```
     243 | 
     244 |         # Add optional URL overrides
     245 |         if config.get("console_url"):
     246 |             cmd.extend(["--console-url", config["console_url"]])
     247 |         if config.get("platform_url"):
     248 |             cmd.extend(["--platform-url", config["platform_url"]])
     249 | 
     250 |         logger.debug(f"Running Kusari command: {' '.join(cmd)}")
     251 | 
     252 |         try:
>>>  253 |             result = subprocess.run(
     254 |                 cmd,
     255 |                 capture_output=True,
     256 |                 text=True,
     257 |                 timeout=self._timeout,
     258 |             )
     259 | 
     260 |             # Parse the output based on format and control type
     261 |             return self._parse_result(
     262 |                 control_id=control_id,
     263 |                 returncode=result.returncode,
```

*[subprocess/dynamic] Entire command built dynamically — highest injection risk without taint confirmation. Command argument is populated from configuration/dict lookup within the same function scope. Opengrep taint analysis will lift confirmed cases to high confidence.*

</details>

## All Instances

| # | File | Line | Severity | Confidence | Status |
|---|------|------|----------|------------|--------|
| 1 | `packages/darnit/src/darnit/core/adapters.py` | 231 | HIGH | 0.90 | Unmitigated |
| 2 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 137 | HIGH | 0.90 | Unmitigated |
| 3 | `packages/darnit-plugins/src/darnit_plugins/adapters/kusari.py` | 253 | HIGH | 0.90 | Unmitigated |
| 4 | `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py` | 131 | HIGH | 0.80 | Unmitigated |
| 5 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 382 | HIGH | 0.80 | Unmitigated |
| 6 | `docs/examples/python-framework/example_framework/implementation.py` | 400 | MEDIUM | 0.60 | Unmitigated |
| 7 | `docs/examples/python-framework/example_framework/implementation.py` | 603 | MEDIUM | 0.60 | Unmitigated |
| 8 | `scripts/create-example-test-repo.py` | 142 | MEDIUM | 0.60 | Unmitigated |
| 9 | `scripts/create-example-test-repo.py` | 308 | MEDIUM | 0.60 | Unmitigated |
| 10 | `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py` | 64 | MEDIUM | 0.60 | Unmitigated |
| 11 | `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/common.py` | 116 | MEDIUM | 0.60 | Unmitigated |
| 12 | `packages/darnit/src/darnit/tools/audit_org.py` | 62 | MEDIUM | 0.60 | Unmitigated |
| 13 | `packages/darnit/src/darnit/tools/audit_org.py` | 113 | MEDIUM | 0.60 | Unmitigated |
| 14 | `packages/darnit/src/darnit/context/auto_detect.py` | 518 | MEDIUM | 0.60 | Unmitigated |
| 15 | `packages/darnit/src/darnit/core/utils.py` | 27 | MEDIUM | 0.60 | Unmitigated |
| 16 | `packages/darnit/src/darnit/core/utils.py` | 99 | MEDIUM | 0.60 | Unmitigated |
| 17 | `packages/darnit/src/darnit/core/utils.py` | 161 | MEDIUM | 0.60 | Unmitigated |
| 18 | `packages/darnit/src/darnit/core/utils.py` | 367 | MEDIUM | 0.60 | Unmitigated |
| 19 | `packages/darnit/src/darnit/core/utils.py` | 385 | MEDIUM | 0.60 | Unmitigated |
| 20 | `packages/darnit/src/darnit/core/utils.py` | 396 | MEDIUM | 0.60 | Unmitigated |
| 21 | `scripts/create-example-test-repo.py` | 136 | LOW | 0.60 | Unmitigated |
| 22 | `scripts/create-example-test-repo.py` | 139 | LOW | 0.60 | Unmitigated |
| 23 | `scripts/create-example-test-repo.py` | 142 | LOW | 0.60 | Unmitigated |
| 24 | `scripts/create-example-test-repo.py` | 280 | LOW | 0.60 | Unmitigated |
| 25 | `packages/darnit/src/darnit/core/adapters.py` | 354 | MEDIUM | 0.60 | Unmitigated |
| 26 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 141 | MEDIUM | 0.60 | Unmitigated |
| 27 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 45 | MEDIUM | 0.60 | Unmitigated |
| 28 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 53 | MEDIUM | 0.60 | Unmitigated |
| 29 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 68 | MEDIUM | 0.60 | Unmitigated |
| 30 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 98 | MEDIUM | 0.60 | Unmitigated |
| 31 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 209 | MEDIUM | 0.60 | Unmitigated |
| 32 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 295 | MEDIUM | 0.60 | Unmitigated |
| 33 | `packages/darnit/src/darnit/remediation/github.py` | 268 | MEDIUM | 0.60 | Unmitigated |
| 34 | `scripts/create-example-test-repo.py` | 297 | LOW | 0.60 | Unmitigated |
| 35 | `scripts/create-example-test-repo.py` | 308 | LOW | 0.60 | Unmitigated |
| 36 | `scripts/create-example-test-repo.py` | 329 | LOW | 0.60 | Unmitigated |
| 37 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 24 | LOW | 0.60 | Unmitigated |
| 38 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 48 | LOW | 0.60 | Unmitigated |
| 39 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 60 | LOW | 0.60 | Unmitigated |
| 40 | `packages/darnit/src/darnit/core/utils.py` | 27 | LOW | 0.60 | Unmitigated |
| 41 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 83 | LOW | 0.60 | Unmitigated |
| 42 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 89 | LOW | 0.60 | Unmitigated |
| 43 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 95 | LOW | 0.60 | Unmitigated |
| 44 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 123 | LOW | 0.60 | Unmitigated |
| 45 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 133 | LOW | 0.60 | Unmitigated |
| 46 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 141 | LOW | 0.60 | Unmitigated |
| 47 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 157 | LOW | 0.60 | Unmitigated |
| 48 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 34 | LOW | 0.60 | Unmitigated |
| 49 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 45 | LOW | 0.60 | Unmitigated |
| 50 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 53 | LOW | 0.60 | Unmitigated |
| 51 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 61 | LOW | 0.60 | Unmitigated |
| 52 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 68 | LOW | 0.60 | Unmitigated |
| 53 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 73 | LOW | 0.60 | Unmitigated |
| 54 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 77 | LOW | 0.60 | Unmitigated |
| 55 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 82 | LOW | 0.60 | Unmitigated |
| 56 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 84 | LOW | 0.60 | Unmitigated |
| 57 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 98 | LOW | 0.60 | Unmitigated |
| 58 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 144 | LOW | 0.60 | Unmitigated |
| 59 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 168 | LOW | 0.60 | Unmitigated |
| 60 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 209 | LOW | 0.60 | Unmitigated |
| 61 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 222 | LOW | 0.60 | Unmitigated |
| 62 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 277 | LOW | 0.60 | Unmitigated |
| 63 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 295 | LOW | 0.60 | Unmitigated |
| 64 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 308 | LOW | 0.60 | Unmitigated |
| 65 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 318 | LOW | 0.60 | Unmitigated |
| 66 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 382 | LOW | 0.60 | Unmitigated |
| 67 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 393 | LOW | 0.60 | Unmitigated |
| 68 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 442 | LOW | 0.60 | Unmitigated |
| 69 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 453 | LOW | 0.60 | Unmitigated |
| 70 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 464 | LOW | 0.60 | Unmitigated |
| 71 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 475 | LOW | 0.60 | Unmitigated |
| 72 | `packages/darnit/src/darnit/remediation/helpers.py` | 93 | LOW | 0.60 | Unmitigated |
| 73 | `docs/examples/python-framework/example_framework/implementation.py` | 317 | LOW | 0.20 | Unmitigated |
| 74 | `scripts/create-example-test-repo.py` | 136 | LOW | 0.20 | Unmitigated |
| 75 | `scripts/create-example-test-repo.py` | 139 | LOW | 0.20 | Unmitigated |
| 76 | `scripts/create-example-test-repo.py` | 280 | LOW | 0.20 | Unmitigated |
| 77 | `scripts/create-example-test-repo.py` | 297 | LOW | 0.20 | Unmitigated |
| 78 | `scripts/create-example-test-repo.py` | 329 | LOW | 0.20 | Unmitigated |
| 79 | `packages/darnit-baseline/src/darnit_baseline/tools.py` | 1331 | LOW | 0.20 | Unmitigated |
| 80 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 24 | LOW | 0.20 | Unmitigated |
| 81 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 48 | LOW | 0.20 | Unmitigated |
| 82 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 60 | LOW | 0.20 | Unmitigated |
| 83 | `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py` | 481 | LOW | 0.20 | Unmitigated |
| 84 | `packages/darnit/src/darnit/cli.py` | 652 | LOW | 0.20 | Unmitigated |
| 85 | `packages/darnit/src/darnit/tools/audit_org.py` | 47 | LOW | 0.20 | Unmitigated |
| 86 | `packages/darnit/src/darnit/tools/audit_org.py` | 416 | LOW | 0.20 | Unmitigated |
| 87 | `packages/darnit/src/darnit/context/dot_project_org.py` | 82 | LOW | 0.20 | Unmitigated |
| 88 | `packages/darnit/src/darnit/context/dot_project_org.py` | 99 | LOW | 0.20 | Unmitigated |
| 89 | `packages/darnit/src/darnit/context/dot_project_org.py` | 120 | LOW | 0.20 | Unmitigated |
| 90 | `packages/darnit/src/darnit/context/sieve.py` | 394 | LOW | 0.20 | Unmitigated |
| 91 | `packages/darnit/src/darnit/context/sieve.py` | 637 | LOW | 0.20 | Unmitigated |
| 92 | `packages/darnit/src/darnit/context/detectors.py` | 11 | LOW | 0.20 | Unmitigated |
| 93 | `packages/darnit/src/darnit/core/utils.py` | 272 | LOW | 0.20 | Unmitigated |
| 94 | `packages/darnit/src/darnit/core/audit_cache.py` | 62 | LOW | 0.20 | Unmitigated |
| 95 | `packages/darnit/src/darnit/core/audit_cache.py` | 79 | LOW | 0.20 | Unmitigated |
| 96 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 83 | LOW | 0.20 | Unmitigated |
| 97 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 89 | LOW | 0.20 | Unmitigated |
| 98 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 95 | LOW | 0.20 | Unmitigated |
| 99 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 123 | LOW | 0.20 | Unmitigated |
| 100 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 133 | LOW | 0.20 | Unmitigated |
| 101 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 157 | LOW | 0.20 | Unmitigated |
| 102 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 34 | LOW | 0.20 | Unmitigated |
| 103 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 61 | LOW | 0.20 | Unmitigated |
| 104 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 73 | LOW | 0.20 | Unmitigated |
| 105 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 77 | LOW | 0.20 | Unmitigated |
| 106 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 82 | LOW | 0.20 | Unmitigated |
| 107 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 84 | LOW | 0.20 | Unmitigated |
| 108 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 144 | LOW | 0.20 | Unmitigated |
| 109 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 168 | LOW | 0.20 | Unmitigated |
| 110 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 222 | LOW | 0.20 | Unmitigated |
| 111 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 277 | LOW | 0.20 | Unmitigated |
| 112 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 308 | LOW | 0.20 | Unmitigated |
| 113 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 318 | LOW | 0.20 | Unmitigated |
| 114 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 393 | LOW | 0.20 | Unmitigated |
| 115 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 442 | LOW | 0.20 | Unmitigated |
| 116 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 453 | LOW | 0.20 | Unmitigated |
| 117 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 464 | LOW | 0.20 | Unmitigated |
| 118 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 475 | LOW | 0.20 | Unmitigated |
| 119 | `packages/darnit/src/darnit/remediation/helpers.py` | 93 | LOW | 0.20 | Unmitigated |
| 120 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 28 | LOW | 0.20 | Unmitigated |
| 121 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 90 | LOW | 0.20 | Unmitigated |
| 122 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 102 | LOW | 0.20 | Unmitigated |

*122 instances total.*

