# Potential command injection via subprocess.run

**STRIDE category:** Tampering
**Rule ID:** `python.sink.dangerous_attr`
**Max severity:** HIGH

## Mitigation

### Strategy 1 (3 instances)

> TOML-config-driven command execution using list-form subprocess. The base command and binary path come from trusted TOML configuration shipped with the package. Config options are type-checked and formatted as --key value pairs. Running external audit binaries (kusari, custom adapters) is a core design requirement of this compliance framework.

**Examples:** `packages/darnit/src/darnit/core/adapters.py:231`, `packages/darnit-plugins/src/darnit_plugins/adapters/kusari.py:253`, `packages/darnit/src/darnit/core/adapters.py:354`

### Strategy 2 (1 instances)

> Sieve exec handler — commands loaded from TOML control definitions (a trusted, admin-controlled source). Variable substitution uses an allowlisted set of placeholders ($OWNER, $REPO, $BRANCH, $PATH) with values from MCP CheckContext. List-form subprocess prevents shell metacharacter injection.

**Examples:** `packages/darnit/src/darnit/sieve/builtin_handlers.py:137`

### Strategy 3 (2 instances)

> Opengrep/Semgrep binary invocation with fully static argv. Binary path is detected via shutil.which() (safe). All flags are hardcoded; only the target directory (validated repository path) varies. No user-controlled arguments reach the command.

**Examples:** `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py:131`, `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py:64`

### Strategy 4 (61 instances)

> Git/gh CLI invocation with fixed binary name and list-form arguments. No shell=True, no user-controlled command names. Variable arguments (branch names, paths) come from validated MCP context or repository state. The gh CLI validates arguments before execution.

**Examples:** `packages/darnit/src/darnit/server/tools/git_operations.py:382`, `packages/darnit/src/darnit/context/auto_detect.py:518`, `packages/darnit/src/darnit/server/tools/git_operations.py:45`
  ...and 58 more.

### Strategy 5 (17 instances)

> Test fixture, example, or build script — not production code. Commands are hardcoded for documentation or repository setup purposes. Risk is accepted because these scripts run in trusted developer environments.

**Examples:** `docs/examples/python-framework/example_framework/implementation.py:400`, `docs/examples/python-framework/example_framework/implementation.py:603`, `scripts/create-example-test-repo.py:142`
  ...and 14 more.

### Strategy 6 (1 instances)

> Single git-remote-get-url invocation to derive repository display name. Fixed command, no user input, 5-second timeout, failure gracefully falls back to directory basename.

**Examples:** `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/common.py:116`

### Strategy 7 (7 instances)

> GitHub CLI (gh) invocation with list-form arguments for PR/repo operations. Command structure is fixed; variable parts (owner, repo, branch) come from validated MCP tool parameters. gh CLI validates all arguments internally.

**Examples:** `packages/darnit/src/darnit/tools/audit_org.py:62`, `packages/darnit/src/darnit/tools/audit_org.py:113`, `packages/darnit/src/darnit/remediation/github.py:268`
  ...and 4 more.

### Strategy 8 (8 instances)

> Utility functions wrapping git/gh CLI with fixed command structures and list-form arguments. Used internally for repository metadata queries (remote URL, branch info, commit log). No external input reaches command arguments — all values are derived from the local repository state.

**Examples:** `packages/darnit/src/darnit/core/utils.py:27`, `packages/darnit/src/darnit/core/utils.py:99`, `packages/darnit/src/darnit/core/utils.py:161`
  ...and 5 more.

### Strategy 9 (14 instances)

> Test repository creation tool — runs git commands to set up ephemeral test repos. Commands are hardcoded (git init, git add, git commit). Only runs in controlled testing/demo contexts with trusted input.

**Examples:** `packages/darnit/src/darnit/server/tools/test_repository.py:141`, `packages/darnit/src/darnit/server/tools/test_repository.py:83`, `packages/darnit/src/darnit/server/tools/test_repository.py:89`
  ...and 11 more.

### Strategy 10 (5 instances)

> List-form subprocess invocation with no shell=True. Command structure is fixed or derived from trusted configuration sources.

**Examples:** `packages/darnit-baseline/src/darnit_baseline/tools.py:1330`, `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py:481`, `packages/darnit/src/darnit/cli.py:652`
  ...and 2 more.

### Strategy 11 (3 instances)

> Gittuf CLI invocation with fixed binary name and static flags. Only the repository path (validated by the framework) varies. List-form subprocess with no shell interpretation.

**Examples:** `packages/darnit-gittuf/src/darnit_gittuf/handlers.py:28`, `packages/darnit-gittuf/src/darnit_gittuf/handlers.py:90`, `packages/darnit-gittuf/src/darnit_gittuf/handlers.py:102`

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
| 1 | `packages/darnit/src/darnit/core/adapters.py` | 231 | HIGH | 0.90 | Mitigated |
| 2 | `packages/darnit/src/darnit/sieve/builtin_handlers.py` | 137 | HIGH | 0.90 | Mitigated |
| 3 | `packages/darnit-plugins/src/darnit_plugins/adapters/kusari.py` | 253 | HIGH | 0.90 | Mitigated |
| 4 | `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py` | 131 | HIGH | 0.80 | Mitigated |
| 5 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 382 | HIGH | 0.80 | Mitigated |
| 6 | `docs/examples/python-framework/example_framework/implementation.py` | 400 | MEDIUM | 0.60 | Accepted |
| 7 | `docs/examples/python-framework/example_framework/implementation.py` | 603 | MEDIUM | 0.60 | Accepted |
| 8 | `scripts/create-example-test-repo.py` | 142 | MEDIUM | 0.60 | Accepted |
| 9 | `scripts/create-example-test-repo.py` | 308 | MEDIUM | 0.60 | Accepted |
| 10 | `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py` | 64 | MEDIUM | 0.60 | Mitigated |
| 11 | `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/common.py` | 116 | MEDIUM | 0.60 | Mitigated |
| 12 | `packages/darnit/src/darnit/tools/audit_org.py` | 62 | MEDIUM | 0.60 | Mitigated |
| 13 | `packages/darnit/src/darnit/tools/audit_org.py` | 113 | MEDIUM | 0.60 | Mitigated |
| 14 | `packages/darnit/src/darnit/context/auto_detect.py` | 518 | MEDIUM | 0.60 | Mitigated |
| 15 | `packages/darnit/src/darnit/core/utils.py` | 27 | MEDIUM | 0.60 | Mitigated |
| 16 | `packages/darnit/src/darnit/core/utils.py` | 99 | MEDIUM | 0.60 | Mitigated |
| 17 | `packages/darnit/src/darnit/core/utils.py` | 161 | MEDIUM | 0.60 | Mitigated |
| 18 | `packages/darnit/src/darnit/core/utils.py` | 367 | MEDIUM | 0.60 | Mitigated |
| 19 | `packages/darnit/src/darnit/core/utils.py` | 385 | MEDIUM | 0.60 | Mitigated |
| 20 | `packages/darnit/src/darnit/core/utils.py` | 396 | MEDIUM | 0.60 | Mitigated |
| 21 | `scripts/create-example-test-repo.py` | 136 | LOW | 0.60 | Accepted |
| 22 | `scripts/create-example-test-repo.py` | 139 | LOW | 0.60 | Accepted |
| 23 | `scripts/create-example-test-repo.py` | 142 | LOW | 0.60 | Accepted |
| 24 | `scripts/create-example-test-repo.py` | 280 | LOW | 0.60 | Accepted |
| 25 | `packages/darnit/src/darnit/core/adapters.py` | 354 | MEDIUM | 0.60 | Mitigated |
| 26 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 141 | MEDIUM | 0.60 | Accepted |
| 27 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 45 | MEDIUM | 0.60 | Mitigated |
| 28 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 53 | MEDIUM | 0.60 | Mitigated |
| 29 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 68 | MEDIUM | 0.60 | Mitigated |
| 30 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 98 | MEDIUM | 0.60 | Mitigated |
| 31 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 209 | MEDIUM | 0.60 | Mitigated |
| 32 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 295 | MEDIUM | 0.60 | Mitigated |
| 33 | `packages/darnit/src/darnit/remediation/github.py` | 268 | MEDIUM | 0.60 | Mitigated |
| 34 | `scripts/create-example-test-repo.py` | 297 | LOW | 0.60 | Accepted |
| 35 | `scripts/create-example-test-repo.py` | 308 | LOW | 0.60 | Accepted |
| 36 | `scripts/create-example-test-repo.py` | 329 | LOW | 0.60 | Accepted |
| 37 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 24 | LOW | 0.60 | Mitigated |
| 38 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 48 | LOW | 0.60 | Mitigated |
| 39 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 60 | LOW | 0.60 | Mitigated |
| 40 | `packages/darnit/src/darnit/core/utils.py` | 27 | LOW | 0.60 | Mitigated |
| 41 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 83 | LOW | 0.60 | Accepted |
| 42 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 89 | LOW | 0.60 | Accepted |
| 43 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 95 | LOW | 0.60 | Accepted |
| 44 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 123 | LOW | 0.60 | Accepted |
| 45 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 133 | LOW | 0.60 | Accepted |
| 46 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 141 | LOW | 0.60 | Accepted |
| 47 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 157 | LOW | 0.60 | Accepted |
| 48 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 34 | LOW | 0.60 | Mitigated |
| 49 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 45 | LOW | 0.60 | Mitigated |
| 50 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 53 | LOW | 0.60 | Mitigated |
| 51 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 61 | LOW | 0.60 | Mitigated |
| 52 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 68 | LOW | 0.60 | Mitigated |
| 53 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 73 | LOW | 0.60 | Mitigated |
| 54 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 77 | LOW | 0.60 | Mitigated |
| 55 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 82 | LOW | 0.60 | Mitigated |
| 56 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 84 | LOW | 0.60 | Mitigated |
| 57 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 98 | LOW | 0.60 | Mitigated |
| 58 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 144 | LOW | 0.60 | Mitigated |
| 59 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 168 | LOW | 0.60 | Mitigated |
| 60 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 209 | LOW | 0.60 | Mitigated |
| 61 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 222 | LOW | 0.60 | Mitigated |
| 62 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 277 | LOW | 0.60 | Mitigated |
| 63 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 295 | LOW | 0.60 | Mitigated |
| 64 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 308 | LOW | 0.60 | Mitigated |
| 65 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 318 | LOW | 0.60 | Mitigated |
| 66 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 382 | LOW | 0.60 | Mitigated |
| 67 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 393 | LOW | 0.60 | Mitigated |
| 68 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 442 | LOW | 0.60 | Mitigated |
| 69 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 453 | LOW | 0.60 | Mitigated |
| 70 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 464 | LOW | 0.60 | Mitigated |
| 71 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 475 | LOW | 0.60 | Mitigated |
| 72 | `packages/darnit/src/darnit/remediation/helpers.py` | 93 | LOW | 0.60 | Mitigated |
| 73 | `docs/examples/python-framework/example_framework/implementation.py` | 317 | LOW | 0.20 | Accepted |
| 74 | `scripts/create-example-test-repo.py` | 136 | LOW | 0.20 | Accepted |
| 75 | `scripts/create-example-test-repo.py` | 139 | LOW | 0.20 | Accepted |
| 76 | `scripts/create-example-test-repo.py` | 280 | LOW | 0.20 | Accepted |
| 77 | `scripts/create-example-test-repo.py` | 297 | LOW | 0.20 | Accepted |
| 78 | `scripts/create-example-test-repo.py` | 329 | LOW | 0.20 | Accepted |
| 79 | `packages/darnit-baseline/src/darnit_baseline/tools.py` | 1330 | LOW | 0.20 | Mitigated |
| 80 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 24 | LOW | 0.20 | Mitigated |
| 81 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 48 | LOW | 0.20 | Mitigated |
| 82 | `packages/darnit-baseline/src/darnit_baseline/attestation/git.py` | 60 | LOW | 0.20 | Mitigated |
| 83 | `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py` | 481 | LOW | 0.20 | Mitigated |
| 84 | `packages/darnit/src/darnit/cli.py` | 652 | LOW | 0.20 | Mitigated |
| 85 | `packages/darnit/src/darnit/tools/audit_org.py` | 47 | LOW | 0.20 | Mitigated |
| 86 | `packages/darnit/src/darnit/tools/audit_org.py` | 416 | LOW | 0.20 | Mitigated |
| 87 | `packages/darnit/src/darnit/context/dot_project_org.py` | 82 | LOW | 0.20 | Mitigated |
| 88 | `packages/darnit/src/darnit/context/dot_project_org.py` | 99 | LOW | 0.20 | Mitigated |
| 89 | `packages/darnit/src/darnit/context/dot_project_org.py` | 120 | LOW | 0.20 | Mitigated |
| 90 | `packages/darnit/src/darnit/context/sieve.py` | 394 | LOW | 0.20 | Mitigated |
| 91 | `packages/darnit/src/darnit/context/sieve.py` | 637 | LOW | 0.20 | Mitigated |
| 92 | `packages/darnit/src/darnit/context/detectors.py` | 11 | LOW | 0.20 | Mitigated |
| 93 | `packages/darnit/src/darnit/core/utils.py` | 272 | LOW | 0.20 | Mitigated |
| 94 | `packages/darnit/src/darnit/core/audit_cache.py` | 62 | LOW | 0.20 | Mitigated |
| 95 | `packages/darnit/src/darnit/core/audit_cache.py` | 79 | LOW | 0.20 | Mitigated |
| 96 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 83 | LOW | 0.20 | Accepted |
| 97 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 89 | LOW | 0.20 | Accepted |
| 98 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 95 | LOW | 0.20 | Accepted |
| 99 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 123 | LOW | 0.20 | Accepted |
| 100 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 133 | LOW | 0.20 | Accepted |
| 101 | `packages/darnit/src/darnit/server/tools/test_repository.py` | 157 | LOW | 0.20 | Accepted |
| 102 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 34 | LOW | 0.20 | Mitigated |
| 103 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 61 | LOW | 0.20 | Mitigated |
| 104 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 73 | LOW | 0.20 | Mitigated |
| 105 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 77 | LOW | 0.20 | Mitigated |
| 106 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 82 | LOW | 0.20 | Mitigated |
| 107 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 84 | LOW | 0.20 | Mitigated |
| 108 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 144 | LOW | 0.20 | Mitigated |
| 109 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 168 | LOW | 0.20 | Mitigated |
| 110 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 222 | LOW | 0.20 | Mitigated |
| 111 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 277 | LOW | 0.20 | Mitigated |
| 112 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 308 | LOW | 0.20 | Mitigated |
| 113 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 318 | LOW | 0.20 | Mitigated |
| 114 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 393 | LOW | 0.20 | Mitigated |
| 115 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 442 | LOW | 0.20 | Mitigated |
| 116 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 453 | LOW | 0.20 | Mitigated |
| 117 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 464 | LOW | 0.20 | Mitigated |
| 118 | `packages/darnit/src/darnit/server/tools/git_operations.py` | 475 | LOW | 0.20 | Mitigated |
| 119 | `packages/darnit/src/darnit/remediation/helpers.py` | 93 | LOW | 0.20 | Mitigated |
| 120 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 28 | LOW | 0.20 | Mitigated |
| 121 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 90 | LOW | 0.20 | Mitigated |
| 122 | `packages/darnit-gittuf/src/darnit_gittuf/handlers.py` | 102 | LOW | 0.20 | Mitigated |

*122 instances total.*

