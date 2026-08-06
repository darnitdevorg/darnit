# Quickstart: `darnit-harness`

**Feature**: 026-darnit-harness
**Audience**: fleet operators evaluating the harness locally + maintainers reviewing the PR

---

## Prereqs

- `uv sync --dev` succeeds on this branch (Stage 1 already installed `pydantic-ai-slim[anthropic]`).
- Feature 025 tests pass (2486 pass on the branch that landed Slice A-D).
- An `ANTHROPIC_API_KEY` in the environment if you want to exercise the LLM dispatch against Claude for real. Otherwise, the pytest suite covers the dispatch path via `MockLLMStep` without a key.

---

## Run the shipping test suite

```bash
uv run pytest tests/darnit/harness/ -v
```

Expected: all tests pass in under 30 s. Includes SC-001 (end-to-end with mocked LLM), SC-004 (LLM-required fixture with mock), SC-005 (four exit-code classes), SC-006 (authority on every result), SC-008 (mocked LLM can't manufacture PASS).

---

## Run the harness against a real repo (no API key needed, deterministic-only)

```bash
uv run darnit harness /path/to/some/repo
```

Against a repo whose baseline controls are mostly deterministic (file_exists, exec, api_call), the harness reaches every control and either concludes or leaves an LLM-required control WARN with a pending_feedback entry.

Exit code convention:
- `0` = all pass, `1` = at least one FAIL, `2` = setup error (missing key, bad path), `3` = internal error.

STDERR shows progress lines and the exit-summary; STDOUT shows the Markdown report.

---

## Run the harness with LLM dispatch against Anthropic (requires key)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run darnit harness /path/to/some/repo
```

Same command; now LLM-backed steps actually run against Claude. Look for `dispatching_llm` progress lines in stderr. Any control whose result includes an LLM contribution appears in the report with an `llm_calls.total > 0` line.

Startup cost: <2s to fail-fast if the key is missing (SC-002). Real runs are bounded by `--per-call-timeout` (60s default per call) and `--total-run-timeout` (900s = 15 minutes default total).

---

## Run with a config-declared answer file

```bash
cat > /tmp/answers.yaml <<'EOF'
security_contact: security@example.com
governance_model: bdfl
EOF

uv run darnit harness /path/to/some/repo --answers /tmp/answers.yaml
```

Answers from `/tmp/answers.yaml` OVERRIDE any values in `.project/project.yaml` in the target repo. Values are treated as `asserted` authority; no interactive prompt appears.

---

## Get JSON output for pipelines

```bash
uv run darnit harness /path/to/some/repo --format=json > report.json
jq '.summary' report.json
jq '.controls[] | select(.status == "FAIL")' report.json
```

The JSON schema is stable at `1.0` (contract RF-2). `.summary.pass` uses the string `"pass"` so `jq` doesn't trip on the Python-alias.

---

## Add a custom AnswerSource adapter (future work)

The `AnswerSource` Protocol lets you plug in a source without touching the harness core. Example skeleton for a GitHub-issue-comment adapter:

```python
from darnit.harness.answer_sources import AnswerSource

class GitHubIssueAnswerSource:
    name = "github_issues"

    def __init__(self, owner: str, repo: str, label: str = "darnit-answer"):
        # Fetch matching issues at construction time.
        self._answers = self._fetch(owner, repo, label)

    def get_answer(self, context_key: str) -> str | None:
        return self._answers.get(context_key)

    def known_keys(self) -> set[str]:
        return set(self._answers.keys())

    def _fetch(self, owner, repo, label):
        # Placeholder: query gh api for issues matching the label
        return {}
```

Wire it in from an operator-controlled script:

```python
from darnit.harness.driver import HarnessRun
from darnit.harness.answer_sources import ProjectYamlAnswerSource, AnswerResolver

run = HarnessRun(local_path="/repo/path")
run.answer_resolver.add(ProjectYamlAnswerSource("/repo/path"))
run.answer_resolver.add(GitHubIssueAnswerSource("acme", "widget"))
report = asyncio.run(run.run())
```

MVP ships only the two file adapters + the Protocol; this adapter is illustrative.

---

## Contract-change procedure

If a change lands that affects `contracts/cli.md`, `contracts/answer-source-protocol.md`, or `contracts/report-format.md`:

1. Update the contract file in the same PR.
2. Update the matching test.
3. Note `Contract change:` in the PR description.

Same procedure as features 024/025.

---

## Troubleshooting

**`SetupError: missing ANTHROPIC_API_KEY`** -- the harness fail-fasts before the audit runs. Set the env var and retry.

**Progress lines silent for minutes** -- probably a stuck LLM call. Kill and re-run with a shorter `--per-call-timeout=30`.

**JSON report missing `authority` on a control** -- that control's result was produced by pre-Stage-1 code that didn't emit authority. Should not happen on the current branch; if it does, it's a bug in whatever emitted the result.

**Exit code 2 when the audit clearly ran** -- something in setup failed AFTER argv parsing but BEFORE the audit body. Check the stderr summary line for the reason.

**Report says "0 LLM calls" but I set a key** -- the framework's controls resolved without needing an LLM step. Normal for deterministic-heavy control sets.
