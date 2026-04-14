# Threat Model Report

## Executive Summary

| Field | Value |
|-------|-------|
| Repository | `mlieberman85/darnit` |
| Scan date | 2026-04-13 22:22:10 |
| Languages | python, yaml |
| Total findings | 176 |
| Critical | 0 |
| High | 5 |
| Medium | 78 |
| Low | 93 |

## Top Risks

| Class | STRIDE | Instances | Severity | Mitigation |
|-------|--------|-----------|----------|------------|
| [Potential command injection via subprocess.run](findings/python-sink-dangerous_attr.md) | Tampering | 122 | HIGH | 0/122 |
| [Unauthenticated mcp tool (mcp): (dynamic — registered from registry.tools)](findings/python-entry-mcp_tool_imperative.md) | Spoofing | 2 | MEDIUM | 0/2 |
| [Dynamic import via importlib.import_module(module_path)](findings/python-eop-dynamic_import_attr.md) | Elevation of Privilege | 4 | MEDIUM | 0/4 |
| [File open with variable path: filepath](findings/python-info_disc-open_call.md) | Information Disclosure | 48 | MEDIUM | 0/48 |

## Unmitigated Findings

| Class | Instances | Max Severity | Detail |
|-------|-----------|--------------|--------|
| Potential command injection via subprocess.run | 122 | HIGH | [python-sink-dangerous_attr.md](findings/python-sink-dangerous_attr.md) |
| Unauthenticated mcp tool (mcp): (dynamic — registered from registry.tools) | 2 | MEDIUM | [python-entry-mcp_tool_imperative.md](findings/python-entry-mcp_tool_imperative.md) |
| Dynamic import via importlib.import_module(module_path) | 4 | MEDIUM | [python-eop-dynamic_import_attr.md](findings/python-eop-dynamic_import_attr.md) |
| File open with variable path: filepath | 48 | MEDIUM | [python-info_disc-open_call.md](findings/python-info_disc-open_call.md) |

## Companion Artefacts

- [Data Flow Diagram](data-flow.md)
- [Raw Findings (JSON)](raw-findings.json)

## Recommendations Summary

### Immediate Actions (Critical / High)

1. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/core/adapters.py:231`
2. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/sieve/builtin_handlers.py:137`
3. **Potential command injection via subprocess.run** — `packages/darnit-plugins/src/darnit_plugins/adapters/kusari.py:253`
4. **Potential command injection via subprocess.run** — `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py:131`
5. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/server/tools/git_operations.py:382`

### Short-term Actions (Medium)

1. **Potential command injection via subprocess.run** — `docs/examples/python-framework/example_framework/implementation.py:400`
2. **Potential command injection via subprocess.run** — `docs/examples/python-framework/example_framework/implementation.py:603`
3. **Potential command injection via subprocess.run** — `scripts/create-example-test-repo.py:142`
4. **Potential command injection via subprocess.run** — `scripts/create-example-test-repo.py:308`
5. **Potential command injection via subprocess.run** — `packages/darnit-baseline/src/darnit_baseline/threat_model/opengrep_runner.py:64`
6. **Potential command injection via subprocess.run** — `packages/darnit-baseline/src/darnit_baseline/threat_model/renderers/common.py:116`
7. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/tools/audit_org.py:62`
8. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/tools/audit_org.py:113`
9. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/context/auto_detect.py:518`
10. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/core/utils.py:27`
11. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/core/utils.py:99`
12. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/core/utils.py:161`
13. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/core/utils.py:367`
14. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/core/utils.py:385`
15. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/core/utils.py:396`
16. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/core/adapters.py:354`
17. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/server/tools/test_repository.py:141`
18. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/server/tools/git_operations.py:45`
19. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/server/tools/git_operations.py:53`
20. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/server/tools/git_operations.py:68`
21. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/server/tools/git_operations.py:98`
22. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/server/tools/git_operations.py:209`
23. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/server/tools/git_operations.py:295`
24. **Potential command injection via subprocess.run** — `packages/darnit/src/darnit/remediation/github.py:268`
25. **Unauthenticated mcp tool (mcp): (dynamic — registered from registry.tools)** — `packages/darnit/src/darnit/server/factory.py:149`
26. **Unauthenticated mcp tool (mcp): (dynamic — registered from registry.tools)** — `packages/darnit/src/darnit/server/factory.py:195`
27. **Dynamic import via importlib.import_module(module_path)** — `packages/darnit/src/darnit/core/registry.py:821`
28. **Dynamic import via importlib.import_module(module_path)** — `packages/darnit/src/darnit/core/handlers.py:237`
29. **Dynamic import via importlib.import_module(module_path)** — `packages/darnit/src/darnit/core/adapters.py:666`
30. **Dynamic import via importlib.import_module(module_path)** — `packages/darnit/src/darnit/server/registry.py:151`
31. **File open with variable path: filepath** — `docs/examples/python-framework/example_framework/implementation.py:175`
32. **File open with variable path: filepath** — `docs/examples/python-framework/example_framework/implementation.py:495`
33. **File open with variable path: filepath** — `docs/examples/python-framework/example_framework/implementation.py:540`
34. **File open with variable path: filepath** — `docs/examples/python-framework/example_framework/implementation.py:571`
35. **File open with variable path: TOML_PATH** — `scripts/validate_sync.py:58`
36. **File open with variable path: toml_path** — `packages/darnit-baseline/src/darnit_baseline/implementation.py:103`
37. **File open with variable path: full_path** — `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py:301`
38. **File open with variable path: full_path** — `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py:394`
39. **File open with variable path: data_flow_path** — `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py:401`
40. **File open with variable path: raw_json_path** — `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py:415`
41. **File open with variable path: group_path** — `packages/darnit-baseline/src/darnit_baseline/threat_model/remediation.py:428`
42. **File open with variable path: path** — `packages/darnit-baseline/src/darnit_baseline/threat_model/dependencies.py:192`
43. **File open with variable path: output_path** — `packages/darnit-baseline/src/darnit_baseline/attestation/generator.py:134`
44. **File open with variable path: toml_path** — `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py:132`
45. **File open with variable path: project_yaml** — `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py:510`
46. **File open with variable path: self.project_yaml** — `packages/darnit/src/darnit/context/dot_project.py:348`
47. **File open with variable path: self.maintainers_yaml** — `packages/darnit/src/darnit/context/dot_project.py:389`
48. **File open with variable path: self.project_yaml** — `packages/darnit/src/darnit/context/dot_project.py:849`
49. **File open with variable path: self.project_yaml** — `packages/darnit/src/darnit/context/dot_project.py:862`
50. **File open with variable path: cache_path** — `packages/darnit/src/darnit/core/verification.py:221`
51. **File open with variable path: cache_path** — `packages/darnit/src/darnit/core/verification.py:296`
52. **File open with variable path: filepath** — `packages/darnit/src/darnit/core/utils.py:337`
53. **File open with variable path: filepath** — `packages/darnit/src/darnit/core/utils.py:351`
54. **File open with variable path: cache_path** — `packages/darnit/src/darnit/core/audit_cache.py:170`
55. **File open with variable path: full_path** — `packages/darnit/src/darnit/config/discovery.py:82`
56. **File open with variable path: pkg_path** — `packages/darnit/src/darnit/config/discovery.py:144`
57. **File open with variable path: pyproj_path** — `packages/darnit/src/darnit/config/discovery.py:156`
58. **File open with variable path: cargo_path** — `packages/darnit/src/darnit/config/discovery.py:168`
59. **File open with variable path: go_mod_path** — `packages/darnit/src/darnit/config/discovery.py:179`
60. **File open with variable path: path** — `packages/darnit/src/darnit/config/loader.py:137`
61. **File open with variable path: path** — `packages/darnit/src/darnit/config/loader.py:234`
62. **File open with variable path: path** — `packages/darnit/src/darnit/config/merger.py:425`
63. **File open with variable path: config_path** — `packages/darnit/src/darnit/config/merger.py:447`
64. **File open with variable path: config_path** — `packages/darnit/src/darnit/server/factory.py:122`
65. **File open with variable path: os.path.join(repo_path, "package.json")** — `packages/darnit/src/darnit/server/tools/test_repository.py:58`
66. **File open with variable path: os.path.join(repo_path, "src", "index.js")** — `packages/darnit/src/darnit/server/tools/test_repository.py:70`
67. **File open with variable path: os.path.join(repo_path, ".gitignore")** — `packages/darnit/src/darnit/server/tools/test_repository.py:78`
68. **File open with variable path: fpath** — `packages/darnit/src/darnit/sieve/builtin_handlers.py:395`
69. **File open with variable path: full** — `packages/darnit/src/darnit/sieve/builtin_handlers.py:486`
70. **File open with variable path: full_path** — `packages/darnit/src/darnit/sieve/builtin_handlers.py:565`
71. **File open with variable path: filepath** — `packages/darnit/src/darnit/sieve/builtin_handlers.py:677`
72. **File open with variable path: filepath** — `packages/darnit/src/darnit/sieve/builtin_handlers.py:711`
73. **File open with variable path: filepath** — `packages/darnit/src/darnit/remediation/github.py:53`
74. **File open with variable path: path** — `packages/darnit/src/darnit/remediation/helpers.py:53`
75. **File open with variable path: template_path** — `packages/darnit/src/darnit/remediation/executor.py:364`
76. **File open with variable path: toml_path** — `packages/darnit-example/src/darnit_example/tools.py:89`
77. **File open with variable path: filepath** — `packages/darnit-example/src/darnit_example/handlers.py:35`
78. **File open with variable path: readme_path** — `packages/darnit-example/src/darnit_example/handlers.py:85`

## Verification Prompts

<!-- darnit:verification-prompt-block -->

**For the calling agent (Claude via MCP):** this summary was produced by the darnit tree-sitter discovery pipeline. Before committing, follow these steps:

1. Open each detail file under `findings/` and review the representative code snippets.
2. For each finding class, ask: does the code at these locations plausibly exhibit the described threat? If not, remove the detail file and its entry from this summary.
3. Refine narrative with project-specific details where helpful.
4. Preserve this `darnit:verification-prompt-block` section — it marks the draft as having gone through review.

<!-- /darnit:verification-prompt-block -->

## Limitations

- Scanned **181** in-scope files (python=137, yaml=44).
- Skipped **48** vendor/build directories and **388** files in unsupported languages.
- Opengrep taint analysis: available.

- **156** additional candidate findings were trimmed to fit the finding cap.

*This is a threat-modeling aid, not an exhaustive vulnerability scan. Use Kusari Inspector or an equivalent SAST tool for deeper coverage.*

