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
| 1 | `packages/darnit/src/darnit/core/adapters.py` | 231 | HIGH | 0.90 | Mitigationstatus.mitigated |
| 2 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 137 | HIGH | 0.90 | Mitigationstatus.mitigated |
| 3 | `packages/darnit-plugins/src/darnit_plugins/adapters/kusari.py` | 253 | HIGH | 0.90 | Mitigationstatus.mitigated |
| 4 | `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py` | 131 | HIGH | 0.80 | Mitigationstatus.mitigated |
| 5 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 382 | HIGH | 0.80 | Mitigationstatus.mitigated |
| 6 | `docs/examples/python-framework/example_framework/implementation.py` | 400 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 7 | `docs/examples/python-framework/example_framework/implementation.py` | 603 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 8 | `scripts/create-example-test-repo.py` | 142 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 9 | `scripts/create-example-test-repo.py` | 308 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 10 | `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py` | 64 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 11 | `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/common.py` | 116 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 12 | `packages/darnit/src/darnit/tools/audit_org.py` | 62 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 13 | `packages/darnit/src/darnit/tools/audit_org.py` | 113 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 14 | `packages/darnit/src/darnit/context/auto_detect.py` | 518 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 15 | `packages/darnit/src/darnit/core/utils.py` | 27 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 16 | `packages/darnit/src/darnit/core/utils.py` | 99 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 17 | `packages/darnit/src/darnit/core/utils.py` | 161 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 18 | `packages/darnit/src/darnit/core/utils.py` | 367 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 19 | `packages/darnit/src/darnit/core/utils.py` | 385 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 20 | `packages/darnit/src/darnit/core/utils.py` | 396 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 21 | `scripts/create-example-test-repo.py` | 136 | LOW | 0.60 | Mitigationstatus.mitigated |
| 22 | `scripts/create-example-test-repo.py` | 139 | LOW | 0.60 | Mitigationstatus.mitigated |
| 23 | `scripts/create-example-test-repo.py` | 142 | LOW | 0.60 | Mitigationstatus.mitigated |
| 24 | `scripts/create-example-test-repo.py` | 280 | LOW | 0.60 | Mitigationstatus.mitigated |
| 25 | `packages/darnit/src/darnit/core/adapters.py` | 354 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 26 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 141 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 27 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 45 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 28 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 53 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 29 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 68 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 30 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 98 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 31 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 209 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 32 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 295 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 33 | `packages/darnit/src/darnit/remediation/github.py` | 268 | MEDIUM | 0.60 | Mitigationstatus.mitigated |
| 34 | `scripts/create-example-test-repo.py` | 297 | LOW | 0.60 | Mitigationstatus.mitigated |
| 35 | `scripts/create-example-test-repo.py` | 308 | LOW | 0.60 | Mitigationstatus.mitigated |
| 36 | `scripts/create-example-test-repo.py` | 329 | LOW | 0.60 | Mitigationstatus.mitigated |
| 37 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 24 | LOW | 0.60 | Mitigationstatus.mitigated |
| 38 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 48 | LOW | 0.60 | Mitigationstatus.mitigated |
| 39 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 60 | LOW | 0.60 | Mitigationstatus.mitigated |
| 40 | `packages/darnit/src/darnit/core/utils.py` | 27 | LOW | 0.60 | Mitigationstatus.mitigated |
| 41 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 83 | LOW | 0.60 | Mitigationstatus.mitigated |
| 42 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 89 | LOW | 0.60 | Mitigationstatus.mitigated |
| 43 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 95 | LOW | 0.60 | Mitigationstatus.mitigated |
| 44 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 123 | LOW | 0.60 | Mitigationstatus.mitigated |
| 45 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 133 | LOW | 0.60 | Mitigationstatus.mitigated |
| 46 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 141 | LOW | 0.60 | Mitigationstatus.mitigated |
| 47 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 157 | LOW | 0.60 | Mitigationstatus.mitigated |
| 48 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 34 | LOW | 0.60 | Mitigationstatus.mitigated |
| 49 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 45 | LOW | 0.60 | Mitigationstatus.mitigated |
| 50 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 53 | LOW | 0.60 | Mitigationstatus.mitigated |
| 51 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 61 | LOW | 0.60 | Mitigationstatus.mitigated |
| 52 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 68 | LOW | 0.60 | Mitigationstatus.mitigated |
| 53 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 73 | LOW | 0.60 | Mitigationstatus.mitigated |
| 54 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 77 | LOW | 0.60 | Mitigationstatus.mitigated |
| 55 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 82 | LOW | 0.60 | Mitigationstatus.mitigated |
| 56 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 84 | LOW | 0.60 | Mitigationstatus.mitigated |
| 57 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 98 | LOW | 0.60 | Mitigationstatus.mitigated |
| 58 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 144 | LOW | 0.60 | Mitigationstatus.mitigated |
| 59 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 168 | LOW | 0.60 | Mitigationstatus.mitigated |
| 60 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 209 | LOW | 0.60 | Mitigationstatus.mitigated |
| 61 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 222 | LOW | 0.60 | Mitigationstatus.mitigated |
| 62 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 277 | LOW | 0.60 | Mitigationstatus.mitigated |
| 63 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 295 | LOW | 0.60 | Mitigationstatus.mitigated |
| 64 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 308 | LOW | 0.60 | Mitigationstatus.mitigated |
| 65 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 318 | LOW | 0.60 | Mitigationstatus.mitigated |
| 66 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 382 | LOW | 0.60 | Mitigationstatus.mitigated |
| 67 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 393 | LOW | 0.60 | Mitigationstatus.mitigated |
| 68 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 442 | LOW | 0.60 | Mitigationstatus.mitigated |
| 69 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 453 | LOW | 0.60 | Mitigationstatus.mitigated |
| 70 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 464 | LOW | 0.60 | Mitigationstatus.mitigated |
| 71 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 475 | LOW | 0.60 | Mitigationstatus.mitigated |
| 72 | `packages/darnit/src/darnit/remediation/helpers.py` | 93 | LOW | 0.60 | Mitigationstatus.mitigated |
| 73 | `docs/examples/python-framework/example_framework/implementation.py` | 317 | LOW | 0.20 | Mitigationstatus.mitigated |
| 74 | `scripts/create-example-test-repo.py` | 136 | LOW | 0.20 | Mitigationstatus.mitigated |
| 75 | `scripts/create-example-test-repo.py` | 139 | LOW | 0.20 | Mitigationstatus.mitigated |
| 76 | `scripts/create-example-test-repo.py` | 280 | LOW | 0.20 | Mitigationstatus.mitigated |
| 77 | `scripts/create-example-test-repo.py` | 297 | LOW | 0.20 | Mitigationstatus.mitigated |
| 78 | `scripts/create-example-test-repo.py` | 329 | LOW | 0.20 | Mitigationstatus.mitigated |
| 79 | `packages/darnit-baseline/src/darnit_baseline/tools.py` | 1330 | LOW | 0.20 | Mitigationstatus.mitigated |
| 80 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 24 | LOW | 0.20 | Mitigationstatus.mitigated |
| 81 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 48 | LOW | 0.20 | Mitigationstatus.mitigated |
| 82 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 60 | LOW | 0.20 | Mitigationstatus.mitigated |
| 83 | `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py` | 481 | LOW | 0.20 | Mitigationstatus.mitigated |
| 84 | `packages/darnit/src/darnit/cli.py` | 652 | LOW | 0.20 | Mitigationstatus.mitigated |
| 85 | `packages/darnit/src/darnit/tools/audit_org.py` | 47 | LOW | 0.20 | Mitigationstatus.mitigated |
| 86 | `packages/darnit/src/darnit/tools/audit_org.py` | 416 | LOW | 0.20 | Mitigationstatus.mitigated |
| 87 | `packages/darnit/src/darnit/context/dot_project_org.py` | 82 | LOW | 0.20 | Mitigationstatus.mitigated |
| 88 | `packages/darnit/src/darnit/context/dot_project_org.py` | 99 | LOW | 0.20 | Mitigationstatus.mitigated |
| 89 | `packages/darnit/src/darnit/context/dot_project_org.py` | 120 | LOW | 0.20 | Mitigationstatus.mitigated |
| 90 | `packages/darnit/src/darnit/context/sieve.py` | 394 | LOW | 0.20 | Mitigationstatus.mitigated |
| 91 | `packages/darnit/src/darnit/context/sieve.py` | 637 | LOW | 0.20 | Mitigationstatus.mitigated |
| 92 | `packages/darnit/src/darnit/context/detectors.py` | 11 | LOW | 0.20 | Mitigationstatus.mitigated |
| 93 | `packages/darnit/src/darnit/core/utils.py` | 272 | LOW | 0.20 | Mitigationstatus.mitigated |
| 94 | `packages/darnit/src/darnit/core/audit_cache.py` | 62 | LOW | 0.20 | Mitigationstatus.mitigated |
| 95 | `packages/darnit/src/darnit/core/audit_cache.py` | 79 | LOW | 0.20 | Mitigationstatus.mitigated |
| 96 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 83 | LOW | 0.20 | Mitigationstatus.mitigated |
| 97 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 89 | LOW | 0.20 | Mitigationstatus.mitigated |
| 98 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 95 | LOW | 0.20 | Mitigationstatus.mitigated |
| 99 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 123 | LOW | 0.20 | Mitigationstatus.mitigated |
| 100 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 133 | LOW | 0.20 | Mitigationstatus.mitigated |
| 101 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 157 | LOW | 0.20 | Mitigationstatus.mitigated |
| 102 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 34 | LOW | 0.20 | Mitigationstatus.mitigated |
| 103 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 61 | LOW | 0.20 | Mitigationstatus.mitigated |
| 104 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 73 | LOW | 0.20 | Mitigationstatus.mitigated |
| 105 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 77 | LOW | 0.20 | Mitigationstatus.mitigated |
| 106 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 82 | LOW | 0.20 | Mitigationstatus.mitigated |
| 107 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 84 | LOW | 0.20 | Mitigationstatus.mitigated |
| 108 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 144 | LOW | 0.20 | Mitigationstatus.mitigated |
| 109 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 168 | LOW | 0.20 | Mitigationstatus.mitigated |
| 110 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 222 | LOW | 0.20 | Mitigationstatus.mitigated |
| 111 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 277 | LOW | 0.20 | Mitigationstatus.mitigated |
| 112 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 308 | LOW | 0.20 | Mitigationstatus.mitigated |
| 113 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 318 | LOW | 0.20 | Mitigationstatus.mitigated |
| 114 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 393 | LOW | 0.20 | Mitigationstatus.mitigated |
| 115 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 442 | LOW | 0.20 | Mitigationstatus.mitigated |
| 116 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 453 | LOW | 0.20 | Mitigationstatus.mitigated |
| 117 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 464 | LOW | 0.20 | Mitigationstatus.mitigated |
| 118 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 475 | LOW | 0.20 | Mitigationstatus.mitigated |
| 119 | `packages/darnit/src/darnit/remediation/helpers.py` | 93 | LOW | 0.20 | Mitigationstatus.mitigated |
| 120 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 28 | LOW | 0.20 | Mitigationstatus.mitigated |
| 121 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 90 | LOW | 0.20 | Mitigationstatus.mitigated |
| 122 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 102 | LOW | 0.20 | Mitigationstatus.mitigated |

*122 instances total.*

