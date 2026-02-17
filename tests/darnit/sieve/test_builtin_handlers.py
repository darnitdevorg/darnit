"""Unit tests for built-in sieve handlers.

Tests each handler function in builtin_handlers.py directly with real
HandlerContext objects and tmp_path fixtures. These are the handlers
that implementation authors study as examples — they should have solid
unit test coverage.
"""

import pytest

from darnit.sieve.builtin_handlers import (
    api_call_handler,
    exec_handler,
    file_create_handler,
    file_exists_handler,
    llm_eval_handler,
    manual_steps_handler,
    project_update_handler,
    regex_handler,
)
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResultStatus,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture()
def ctx(tmp_path):
    """Create a HandlerContext rooted at tmp_path."""
    return HandlerContext(
        local_path=str(tmp_path),
        owner="testorg",
        repo="testrepo",
        default_branch="main",
        control_id="TEST-01",
    )


# =============================================================================
# file_exists_handler
# =============================================================================


class TestFileExistsHandler:
    """Tests for the file_exists built-in handler."""

    def test_pass_when_file_exists(self, tmp_path, ctx):
        (tmp_path / "README.md").write_text("# Hello")
        result = file_exists_handler({"files": ["README.md"]}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert result.confidence == 1.0
        assert result.evidence["relative_path"] == "README.md"

    def test_pass_with_glob_pattern(self, tmp_path, ctx):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "SECURITY.md").write_text("policy")
        result = file_exists_handler({"files": ["docs/*.md"]}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert "SECURITY.md" in result.evidence["relative_path"]

    def test_fail_when_no_files_found(self, ctx):
        result = file_exists_handler({"files": ["MISSING.md", "ALSO_MISSING.txt"]}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["files_checked"] == ["MISSING.md", "ALSO_MISSING.txt"]

    def test_inconclusive_when_no_files_specified(self, ctx):
        result = file_exists_handler({"files": []}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_inconclusive_when_files_key_missing(self, ctx):
        result = file_exists_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_pass_returns_first_match(self, tmp_path, ctx):
        (tmp_path / "README.md").write_text("# A")
        (tmp_path / "README.rst").write_text("B")
        result = file_exists_handler({"files": ["README.md", "README.rst"]}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["relative_path"] == "README.md"


# =============================================================================
# exec_handler
# =============================================================================


class TestExecHandler:
    """Tests for the exec built-in handler."""

    def test_pass_on_zero_exit(self, ctx):
        result = exec_handler({"command": ["true"]}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["exit_code"] == 0

    def test_fail_on_explicit_fail_exit_code(self, ctx):
        result = exec_handler(
            {"command": ["false"], "fail_exit_codes": [1]},
            ctx,
        )
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["exit_code"] == 1

    def test_inconclusive_on_unexpected_exit_code(self, ctx):
        result = exec_handler(
            {"command": ["sh", "-c", "exit 42"], "pass_exit_codes": [0], "fail_exit_codes": [1]},
            ctx,
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["exit_code"] == 42

    def test_error_on_command_not_found(self, ctx):
        result = exec_handler({"command": ["__nonexistent_cmd_xyz__"]}, ctx)
        assert result.status == HandlerResultStatus.ERROR
        assert "not found" in result.message.lower()

    def test_error_on_timeout(self, ctx):
        result = exec_handler({"command": ["sleep", "10"], "timeout": 1}, ctx)
        assert result.status == HandlerResultStatus.ERROR
        assert "timed out" in result.message.lower()

    def test_error_when_no_command(self, ctx):
        result = exec_handler({}, ctx)
        assert result.status == HandlerResultStatus.ERROR

    def test_variable_substitution(self, ctx):
        result = exec_handler(
            {"command": ["echo", "$OWNER/$REPO/$BRANCH"]},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert "testorg/testrepo/main" in result.evidence["stdout"]

    def test_path_substitution(self, ctx):
        result = exec_handler(
            {"command": ["echo", "$PATH"]},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert ctx.local_path in result.evidence["stdout"]

    def test_json_output_parsing(self, ctx):
        result = exec_handler(
            {"command": ["echo", '{"key": "value"}'], "output_format": "json"},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["json"] == {"key": "value"}

    def test_cel_expression_pass(self, ctx):
        result = exec_handler(
            {
                "command": ["echo", '{"enabled": true}'],
                "output_format": "json",
                "expr": "output.json.enabled == true",
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert "CEL" in result.message

    def test_cel_expression_false_returns_inconclusive(self, ctx):
        result = exec_handler(
            {
                "command": ["echo", '{"enabled": false}'],
                "output_format": "json",
                "expr": "output.json.enabled == true",
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert "false" in result.message.lower()

    def test_stdout_truncated_in_evidence(self, ctx):
        """Long stdout is truncated to 2000 chars in evidence."""
        result = exec_handler(
            {"command": ["python3", "-c", "print('x' * 5000)"]},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert len(result.evidence["stdout"]) <= 2000


# =============================================================================
# regex_handler
# =============================================================================


class TestRegexHandler:
    """Tests for the regex (pattern) built-in handler."""

    # --- Legacy singular file + pattern (backward compat) ---

    def test_pass_when_pattern_matches(self, tmp_path, ctx):
        (tmp_path / "SECURITY.md").write_text("security@example.com")
        result = regex_handler(
            {"file": "SECURITY.md", "pattern": r"[\w.]+@[\w.]+"},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["any_match"] is True

    def test_fail_when_pattern_not_found(self, tmp_path, ctx):
        (tmp_path / "SECURITY.md").write_text("No contact info here")
        result = regex_handler(
            {"file": "SECURITY.md", "pattern": r"[\w.]+@[\w.]+"},
            ctx,
        )
        assert result.status == HandlerResultStatus.FAIL

    def test_fail_when_below_min_matches(self, tmp_path, ctx):
        (tmp_path / "CODE.py").write_text("# Copyright 2024\n# Some code\n")
        result = regex_handler(
            {"file": "CODE.py", "pattern": r"Copyright \d{4}", "min_matches": 3},
            ctx,
        )
        assert result.status == HandlerResultStatus.FAIL

    def test_pass_with_must_not_match_absent(self, tmp_path, ctx):
        (tmp_path / "clean.py").write_text("print('hello')\n")
        result = regex_handler(
            {"file": "clean.py", "pattern": r"TODO|FIXME|HACK", "must_not_match": True},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS

    def test_fail_with_must_not_match_present(self, tmp_path, ctx):
        (tmp_path / "messy.py").write_text("# TODO: fix this\nprint('hello')\n")
        result = regex_handler(
            {"file": "messy.py", "pattern": r"TODO|FIXME|HACK", "must_not_match": True},
            ctx,
        )
        assert result.status == HandlerResultStatus.FAIL

    def test_inconclusive_when_file_not_found(self, ctx):
        result = regex_handler(
            {"file": "NONEXISTENT.md", "pattern": r".*"},
            ctx,
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_inconclusive_when_missing_file_or_pattern(self, ctx):
        result = regex_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_found_file_evidence_resolution(self, tmp_path, ctx):
        """$FOUND_FILE resolves from gathered_evidence."""
        (tmp_path / "SECURITY.md").write_text("Report to security@example.com")
        ctx.gathered_evidence["found_file"] = str(tmp_path / "SECURITY.md")
        result = regex_handler(
            {"file": "$FOUND_FILE", "pattern": r"security@"},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS

    def test_found_file_missing_evidence(self, ctx):
        """$FOUND_FILE with no evidence returns INCONCLUSIVE."""
        result = regex_handler(
            {"file": "$FOUND_FILE", "pattern": r".*"},
            ctx,
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert "$FOUND_FILE" in result.message

    # --- Multi-file with globs ---

    def test_multi_file_glob_expansion(self, tmp_path, ctx):
        """files = ["*.yml"] expands globs and searches content."""
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("runs-on: ubuntu-latest")
        result = regex_handler(
            {
                "files": [".github/workflows/*.yml"],
                "pattern": {"patterns": {"runner": "runs-on"}},
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS

    def test_multi_file_no_matches(self, tmp_path, ctx):
        """FAIL when no files match any glob."""
        result = regex_handler(
            {
                "files": ["nonexistent/*.yml"],
                "pattern": {"patterns": {"x": "y"}},
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_multi_file_multiple_globs(self, tmp_path, ctx):
        """Multiple globs in files list are all expanded."""
        (tmp_path / "a.md").write_text("hello world")
        (tmp_path / "b.txt").write_text("hello again")
        result = regex_handler(
            {
                "files": ["*.md", "*.txt"],
                "pattern": {"patterns": {"greeting": "hello"}},
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["files_checked"] == 2

    # --- Multi-pattern (named patterns) ---

    def test_named_patterns_pass(self, tmp_path, ctx):
        """pattern.patterns dict with named regexes."""
        (tmp_path / "ci.yml").write_text("runs-on: ubuntu\nsteps:\n  - uses: actions/checkout")
        result = regex_handler(
            {
                "files": ["ci.yml"],
                "pattern": {"patterns": {
                    "runner": "runs-on",
                    "checkout": "actions/checkout",
                }},
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS

    def test_named_patterns_fail_when_none_match(self, tmp_path, ctx):
        """FAIL when no named patterns match."""
        (tmp_path / "empty.yml").write_text("key: value")
        result = regex_handler(
            {
                "files": ["empty.yml"],
                "pattern": {"patterns": {"missing": "nonexistent_pattern"}},
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.FAIL

    # --- pass_if_any ---

    def test_pass_if_any_true_default(self, tmp_path, ctx):
        """pass_if_any defaults to True: one match is enough."""
        (tmp_path / "a.md").write_text("match_here")
        (tmp_path / "b.md").write_text("no luck")
        result = regex_handler(
            {
                "files": ["a.md", "b.md"],
                "pattern": {"patterns": {"target": "match_here"}},
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS

    def test_pass_if_any_false_requires_all(self, tmp_path, ctx):
        """pass_if_any=False requires ALL file×pattern combos to match."""
        (tmp_path / "a.md").write_text("match_here")
        (tmp_path / "b.md").write_text("no luck")
        result = regex_handler(
            {
                "files": ["a.md", "b.md"],
                "pattern": {"patterns": {"target": "match_here"}},
                "pass_if_any": False,
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.FAIL

    def test_pass_if_any_false_all_match(self, tmp_path, ctx):
        """pass_if_any=False passes when all match."""
        (tmp_path / "a.md").write_text("keyword present")
        (tmp_path / "b.md").write_text("keyword also present")
        result = regex_handler(
            {
                "files": ["a.md", "b.md"],
                "pattern": {"patterns": {"kw": "keyword"}},
                "pass_if_any": False,
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS

    # --- exclude_must_not_exist mode ---

    def test_exclude_pass_when_no_files(self, ctx):
        """exclude_must_not_exist: PASS when no excluded files found."""
        result = regex_handler(
            {
                "exclude_files": ["**/*.exe", "**/*.dll"],
                "mode": "exclude_must_not_exist",
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["found_count"] == 0

    def test_exclude_fail_when_files_found(self, tmp_path, ctx):
        """exclude_must_not_exist: FAIL when excluded files exist."""
        (tmp_path / "binary.exe").write_bytes(b"\x00\x01")
        result = regex_handler(
            {
                "exclude_files": ["**/*.exe"],
                "mode": "exclude_must_not_exist",
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["found_count"] >= 1

    # --- Recursive glob support ---

    def test_recursive_glob(self, tmp_path, ctx):
        """** recursive globs find files in subdirectories."""
        deep = tmp_path / "src" / "pkg"
        deep.mkdir(parents=True)
        (deep / "mod.py").write_text("def main(): pass")
        result = regex_handler(
            {
                "files": ["**/*.py"],
                "pattern": {"patterns": {"func": "def main"}},
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS


# =============================================================================
# llm_eval_handler
# =============================================================================


class TestLlmEvalHandler:
    """Tests for the llm_eval built-in handler."""

    def test_returns_inconclusive_with_consultation(self, ctx):
        result = llm_eval_handler(
            {"prompt": "Does this project follow best practices?", "confidence_threshold": 0.9},
            ctx,
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert "consultation_request" in result.details
        assert result.details["consultation_request"]["prompt"] == "Does this project follow best practices?"
        assert result.details["consultation_request"]["confidence_threshold"] == 0.9

    def test_inconclusive_when_no_prompt(self, ctx):
        result = llm_eval_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE


# =============================================================================
# manual_steps_handler
# =============================================================================


class TestManualStepsHandler:
    """Tests for the manual_steps built-in handler."""

    def test_returns_inconclusive_with_steps(self, ctx):
        steps = ["Check the config", "Verify the output"]
        result = manual_steps_handler({"steps": steps}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["verification_steps"] == steps
        assert result.details["verification_steps"] == steps

    def test_default_steps_when_none_provided(self, ctx):
        result = manual_steps_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert len(result.evidence["verification_steps"]) > 0


# =============================================================================
# file_create_handler (remediation)
# =============================================================================


class TestFileCreateHandler:
    """Tests for the file_create remediation handler."""

    def test_creates_file_with_content(self, tmp_path, ctx):
        result = file_create_handler(
            {"path": "NEW_FILE.md", "content": "# Created"},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert (tmp_path / "NEW_FILE.md").read_text() == "# Created"
        assert result.evidence["action"] == "created"

    def test_skips_existing_file(self, tmp_path, ctx):
        (tmp_path / "EXISTS.md").write_text("original")
        result = file_create_handler(
            {"path": "EXISTS.md", "content": "overwritten"},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["action"] == "skipped"
        assert (tmp_path / "EXISTS.md").read_text() == "original"

    def test_overwrites_when_flag_set(self, tmp_path, ctx):
        (tmp_path / "EXISTS.md").write_text("original")
        result = file_create_handler(
            {"path": "EXISTS.md", "content": "new content", "overwrite": True},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert (tmp_path / "EXISTS.md").read_text() == "new content"

    def test_creates_parent_directories(self, tmp_path, ctx):
        result = file_create_handler(
            {"path": "deep/nested/FILE.md", "content": "nested"},
            ctx,
        )
        assert result.status == HandlerResultStatus.PASS
        assert (tmp_path / "deep" / "nested" / "FILE.md").read_text() == "nested"

    def test_error_when_no_path(self, ctx):
        result = file_create_handler({}, ctx)
        assert result.status == HandlerResultStatus.ERROR

    def test_error_when_no_content(self, ctx):
        result = file_create_handler({"path": "FILE.md"}, ctx)
        assert result.status == HandlerResultStatus.ERROR


# =============================================================================
# api_call_handler (remediation)
# =============================================================================


class TestApiCallHandler:
    """Tests for the api_call remediation handler."""

    def test_returns_inconclusive_with_url(self, ctx):
        result = api_call_handler(
            {"url": "https://api.github.com/repos/$OWNER/$REPO", "method": "PUT"},
            ctx,
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert "testorg" in result.evidence["url"]
        assert "testrepo" in result.evidence["url"]
        assert result.evidence["method"] == "PUT"

    def test_error_when_no_url(self, ctx):
        result = api_call_handler({}, ctx)
        assert result.status == HandlerResultStatus.ERROR

    def test_variable_substitution_in_url(self, ctx):
        result = api_call_handler(
            {"url": "https://api.example.com/$OWNER/$REPO/$BRANCH"},
            ctx,
        )
        assert "testorg/testrepo/main" in result.evidence["url"]


# =============================================================================
# project_update_handler (remediation)
# =============================================================================


class TestProjectUpdateHandler:
    """Tests for the project_update remediation handler."""

    def test_returns_pass_with_updates(self, ctx):
        updates = {"security.policy.path": "SECURITY.md"}
        result = project_update_handler({"updates": updates}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["updates"] == updates
        assert result.details["project_updates"] == updates

    def test_inconclusive_when_no_updates(self, ctx):
        result = project_update_handler({"updates": {}}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_inconclusive_when_updates_missing(self, ctx):
        result = project_update_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE
