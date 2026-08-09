# Quickstart: Interactive Question Resolvers

**Feature**: 027-interactive-resolvers | **For**: fleet operators running `darnit harness` interactively, third-party resolver authors adding a custom answer source.

## Operator: run interactively against a repo

```bash
# From the darnit workspace
uv run darnit harness /path/to/repo --level 3 --interactive
```

What you should see:

1. Ordinary audit progress lines on stderr (`[N/M] control_id <phase-verb>`) for each control, exactly as they appear in a non-interactive run.
2. When the audit finishes, if there are pending feedback questions, exactly ONE line on stderr:

   ```
   harness: starting interactive collection (3 pending questions)
   ```

3. A prompt on your terminal (via /dev/tty, physically separate from stderr):

   ```
   [1 of 3]
   OSPS-GV-01.01
   Who is the security contact for this project?
     Help: A person or team that receives vulnerability reports.
   > _
   ```

4. Type an answer and hit Enter. The prompt moves to `[2 of 3]`.
5. Hit Enter without typing to skip. That question stays pending in the report.
6. Ctrl+C at any point stops further prompting but keeps everything you've already answered.
7. One closing line on stderr:

   ```
   harness: finished interactive collection: 2 answered, 1 skipped
   ```

8. The report is written per the `--output` and `--format` flags. Each pending question that was offered to the resolver chain shows its `resolution_trail` in the report (JSON always; Markdown when non-empty).

## Operator: combine `--answers` file and `--interactive`

`--answers` runs first (values you already know from the yaml file), then interactive fills in the rest:

```bash
uv run darnit harness /path/to/repo --level 3 --answers ~/known-values.yaml --interactive
```

The report's `answer_sources_used` lists both sources; each answer records which source produced it in its `origin` field.

## Fail-fast behavior

Piped stdin under `--interactive`:

```bash
echo "foo" | uv run darnit harness /path/to/repo --interactive
```

Expected: exit code 2 within 2 seconds. Stderr summary:

```
harness: setup_error: interactive channel unavailable (stdin is not a TTY), exit 2
```

No control runs. This is deliberate -- if a CI runner accidentally sets `--interactive`, we want a loud failure, not a silent skip-everything.

## Third-party resolver author: write a custom resolver

Ship a package with a `QuestionResolver`:

```python
# my_pkg/resolvers.py
from darnit.harness.question_resolvers import Answer, QuestionResolver

class GHIssueCommentResolver:
    name = "gh_issue_comment"

    async def resolve(self, question) -> Answer | None:
        # Look up the question's control_id in a GitHub issue,
        # scrape the latest maintainer comment, etc.
        answer_text = await self._fetch_from_gh(question)
        if not answer_text:
            return None  # nothing found; harness will try the next resolver
        return Answer(
            value=answer_text,
            origin=f"gh_issue_comment:{question.control_id}",
        )

def build() -> QuestionResolver:
    return GHIssueCommentResolver()
```

Declare the entry point in your `pyproject.toml`:

```toml
[project.entry-points."darnit.question_resolvers"]
gh_issue_comment = "my_pkg.resolvers:build"
```

Install your package into the same venv as darnit; the harness will discover the resolver automatically at CLI startup.

Verify:

```bash
uv pip install /path/to/my_pkg
uv run darnit harness /path/to/repo --interactive --level 3
```

The `harness: starting interactive collection` line will be preceded by an INFO log naming the resolvers configured for this run, including `gh_issue_comment`. The report's `resolvers_used` will list both.

## Library consumer: inject a resolver directly

For tests or embedded uses:

```python
from darnit.harness.driver import HarnessRun
from darnit.harness.question_resolvers import Answer

class AlwaysAnswerResolver:
    name = "always"
    async def resolve(self, question):
        return Answer(value="constant", origin="always")

run = HarnessRun(
    local_path="/path/to/repo",
    level=3,
    question_resolvers=[AlwaysAnswerResolver()],
)
report = await run.run()
```

No entry-point discovery happens; only the explicitly passed resolvers run. Useful for reproducible test fixtures.

## Verifying the resolution trail

For any pending question in the report, the `resolution_trail` shows which resolvers were offered the question and how each responded:

```json
{
  "pending_feedback": [
    {
      "control_id": "OSPS-GV-01.01",
      "context_key": "security_contact",
      "question": "Who is the security contact for this project?",
      "answered": true,
      "answer": "security@example.com",
      "resolution_trail": [
        {"resolver_name": "gh_issue_comment", "outcome": "skipped", "error_summary": null},
        {"resolver_name": "interactive_terminal", "outcome": "answered", "error_summary": null}
      ]
    }
  ]
}
```

An auditor reads this and knows: GitHub had no comment for this question, and the operator typed the answer at the terminal.

## Common gotchas

- **`--interactive` in a CI job**: will fail with exit code 2. Use `--answers <file>` for non-interactive answer collection.
- **Container with no `/dev/tty` node**: same failure, different underlying cause (stdin might be a TTY but `/dev/tty` open fails). Stderr summary distinguishes.
- **Multiple entry points with the same name**: last-write wins in `importlib.metadata` discovery. Don't ship two packages that both register `interactive_terminal`.
- **A resolver hangs indefinitely**: the MVP has no per-resolver timeout for non-interactive resolvers. Third-party resolver authors are responsible for their own timeouts; the harness's total-run timeout (`--total-run-timeout-s`, from feature 026) is the ultimate backstop.
- **The report shows an empty `resolution_trail`**: means the AnswerSource chain (project.yaml + `--answers`) answered the question before it reached the resolver chain. Normal, not a bug.

## Running the tests

```bash
uv run pytest tests/darnit/harness/ -q
```

Feature-027-specific tests live in:

- `tests/darnit/harness/test_question_resolvers.py`
- `tests/darnit/harness/test_interactive_resolver.py`
- `tests/darnit/harness/test_resolver_discovery.py`
- `tests/darnit/harness/test_resolution_trail.py`

Plus additions to `test_driver.py`, `test_cli.py`, `test_report.py`.

External-fixture package for SC-002 enforcement:

```
tests/darnit/harness/fixtures/mock_resolver_pkg/
```

This lives OUTSIDE `packages/darnit/src/darnit/harness/` and registers a resolver via entry point. If a test asserts it is discoverable via `importlib.metadata.entry_points(group="darnit.question_resolvers")` and invoked without any changes under `packages/darnit/src/darnit/harness/`, SC-002 is mechanically enforced.
