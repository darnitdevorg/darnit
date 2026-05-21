"""Tests for CEL expression evaluator."""

from pathlib import Path

import pytest

from darnit.sieve.cel_evaluator import (
    CELCompilationError,
    CELContext,
    CELEvaluator,
    CELResult,
    compile_cel,
    evaluate_cel,
    validate_cel,
)


class TestCELEvaluator:
    """Tests for CELEvaluator class."""

    def test_compile_simple_expression(self) -> None:
        """Test compiling a simple boolean expression."""
        evaluator = CELEvaluator()
        program = evaluator.compile("true")
        assert program.expression == "true"
        assert program.program is not None

    def test_compile_complex_expression(self) -> None:
        """Test compiling a complex expression."""
        evaluator = CELEvaluator()
        program = evaluator.compile("output.exit_code == 0 && size(output.stdout) > 0")
        assert program.expression == "output.exit_code == 0 && size(output.stdout) > 0"

    def test_compile_invalid_expression(self) -> None:
        """Test that invalid expressions raise CELCompilationError."""
        evaluator = CELEvaluator()
        with pytest.raises(CELCompilationError):
            evaluator.compile("invalid syntax !!!")

    def test_evaluate_true_expression(self) -> None:
        """Test evaluating an expression that returns true."""
        evaluator = CELEvaluator()
        program = evaluator.compile("output.exit_code == 0")
        context = CELContext(output={"exit_code": 0, "stdout": "success"})

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is True
        assert result.error is None

    def test_evaluate_false_expression(self) -> None:
        """Test evaluating an expression that returns false."""
        evaluator = CELEvaluator()
        program = evaluator.compile("output.exit_code == 0")
        context = CELContext(output={"exit_code": 1, "stdout": ""})

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is False

    def test_evaluate_with_dict_context(self) -> None:
        """Test evaluation with dict context instead of CELContext."""
        evaluator = CELEvaluator()
        program = evaluator.compile("output.status == 'ok'")
        context = {"output": {"status": "ok"}}

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is True

    def test_evaluate_string_contains(self) -> None:
        """Test string contains function."""
        evaluator = CELEvaluator()
        program = evaluator.compile("output.stdout.contains('success')")
        context = CELContext(output={"stdout": "Build success!"})

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is True

    def test_evaluate_list_size(self) -> None:
        """Test list size function."""
        evaluator = CELEvaluator()
        program = evaluator.compile("size(files) > 0")
        context = CELContext(files=["SECURITY.md", "README.md"])

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is True

    def test_evaluate_empty_list(self) -> None:
        """Test with empty list."""
        evaluator = CELEvaluator()
        program = evaluator.compile("size(files) == 0")
        context = CELContext(files=[])

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is True

    def test_evaluate_nested_access(self) -> None:
        """Test nested object access."""
        evaluator = CELEvaluator()
        program = evaluator.compile("response.body.status == 'enabled'")
        context = CELContext(
            response={
                "status_code": 200,
                "body": {"status": "enabled"},
                "headers": {},
            }
        )

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is True

    def test_evaluate_comparison_operators(self) -> None:
        """Test various comparison operators."""
        evaluator = CELEvaluator()

        test_cases = [
            ("output.exit_code < 1", {"output": {"exit_code": 0}}, True),
            ("output.exit_code <= 0", {"output": {"exit_code": 0}}, True),
            ("output.exit_code > 0", {"output": {"exit_code": 1}}, True),
            ("output.exit_code >= 1", {"output": {"exit_code": 1}}, True),
            ("output.exit_code != 0", {"output": {"exit_code": 1}}, True),
        ]

        for expr, ctx, expected in test_cases:
            program = evaluator.compile(expr)
            result = evaluator.evaluate(program, ctx)
            assert result.success is True, f"Failed for: {expr}"
            assert result.value is expected, f"Expected {expected} for: {expr}"

    def test_evaluate_logical_operators(self) -> None:
        """Test logical operators."""
        evaluator = CELEvaluator()

        # AND
        program = evaluator.compile("true && true")
        result = evaluator.evaluate(program, {})
        assert result.value is True

        program = evaluator.compile("true && false")
        result = evaluator.evaluate(program, {})
        assert result.value is False

        # OR
        program = evaluator.compile("true || false")
        result = evaluator.evaluate(program, {})
        assert result.value is True

        # NOT
        program = evaluator.compile("!false")
        result = evaluator.evaluate(program, {})
        assert result.value is True

    def test_validate_expression_valid(self) -> None:
        """Test validation of valid expression."""
        evaluator = CELEvaluator()
        is_valid, error = evaluator.validate_expression("output.exit_code == 0")
        assert is_valid is True
        assert error is None

    def test_validate_expression_invalid(self) -> None:
        """Test validation of invalid expression."""
        evaluator = CELEvaluator()
        is_valid, error = evaluator.validate_expression("invalid !!!")
        assert is_valid is False
        assert error is not None


class TestCELContext:
    """Tests for CELContext dataclass."""

    def test_default_context(self) -> None:
        """Test default context has empty values."""
        ctx = CELContext()
        assert ctx.output == {}
        assert ctx.response == {}
        assert ctx.files == []
        assert ctx.matches == []
        assert ctx.project == {}
        assert ctx.context == {}
        assert ctx.repo == {}

    def test_to_cel_context(self) -> None:
        """Test conversion to CEL-compatible dict."""
        ctx = CELContext(
            output={"exit_code": 0},
            files=["test.md"],
        )
        cel_ctx = ctx.to_cel_context()

        assert cel_ctx["output"] == {"exit_code": 0}
        assert cel_ctx["files"] == ["test.md"]
        assert "response" in cel_ctx
        assert "project" in cel_ctx


class TestCELResult:
    """Tests for CELResult dataclass."""

    def test_success_result(self) -> None:
        """Test successful result."""
        result = CELResult(success=True, value=True)
        assert result.success is True
        assert result.value is True
        assert result.error is None

    def test_error_result(self) -> None:
        """Test error result."""
        result = CELResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.value is None
        assert result.error == "Something went wrong"


class TestFileExistsFunction:
    """Tests for file_exists custom function."""

    def test_file_exists_true(self, tmp_path: Path) -> None:
        """Test file_exists returns true for existing file."""
        # Create a test file
        test_file = tmp_path / "SECURITY.md"
        test_file.write_text("# Security Policy")

        evaluator = CELEvaluator(repo_path=tmp_path)
        program = evaluator.compile('file_exists("SECURITY.md")')
        result = evaluator.evaluate(program, {})

        assert result.success is True
        assert result.value is True

    def test_file_exists_false(self, tmp_path: Path) -> None:
        """Test file_exists returns false for missing file."""
        evaluator = CELEvaluator(repo_path=tmp_path)
        program = evaluator.compile('file_exists("NONEXISTENT.md")')
        result = evaluator.evaluate(program, {})

        assert result.success is True
        assert result.value is False

    def test_file_exists_no_repo_path(self) -> None:
        """Test file_exists returns false when no repo_path set."""
        evaluator = CELEvaluator()  # No repo_path
        program = evaluator.compile('file_exists("SECURITY.md")')
        result = evaluator.evaluate(program, {})

        assert result.success is True
        assert result.value is False


class TestJsonPathFunction:
    """Tests for json_path custom function."""

    def test_json_path_simple(self) -> None:
        """Test json_path extracts simple value."""
        evaluator = CELEvaluator()
        program = evaluator.compile('json_path(output.json, "status") == "ok"')
        context = {"output": {"json": {"status": "ok", "code": 200}}}

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is True

    def test_json_path_nested(self) -> None:
        """Test json_path extracts nested value."""
        evaluator = CELEvaluator()
        program = evaluator.compile('json_path(output.json, "data.items[0].name") == "first"')
        context = {
            "output": {
                "json": {"data": {"items": [{"name": "first"}, {"name": "second"}]}}
            }
        }

        result = evaluator.evaluate(program, context)

        assert result.success is True
        assert result.value is True


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_compile_cel(self) -> None:
        """Test compile_cel function."""
        program = compile_cel("true")
        assert program.expression == "true"

    def test_evaluate_cel(self) -> None:
        """Test evaluate_cel function."""
        result = evaluate_cel("output.code == 0", {"output": {"code": 0}})
        assert result.success is True
        assert result.value is True

    def test_validate_cel_valid(self) -> None:
        """Test validate_cel with valid expression."""
        is_valid, error = validate_cel("output.exit_code == 0")
        assert is_valid is True
        assert error is None

    def test_validate_cel_invalid(self) -> None:
        """Test validate_cel with invalid expression."""
        is_valid, error = validate_cel("invalid !!!")
        assert is_valid is False
        assert error is not None


class TestTimeout:
    """Tests for evaluation timeout."""

    def test_timeout_short(self) -> None:
        """Test that very short timeout causes timeout error."""
        # This test is tricky because we need an expression that takes time
        # For now, just test that timeout parameter is respected
        evaluator = CELEvaluator(timeout_seconds=0.001)
        program = evaluator.compile("true")
        # Simple expression should still complete
        result = evaluator.evaluate(program, {})
        # Either succeeds (fast enough) or times out
        assert result.success is True or "timeout" in (result.error or "").lower()


class TestOldStyleVsCELComparison:
    """Integration tests comparing old-style pass fields vs CEL expressions."""

    def test_json_path_equivalence(self) -> None:
        """Test that CEL json_path produces same result as old-style pass_if_json_path."""
        # Simulate old-style: pass_if_json_path = "status", pass_if_json_value = "enabled"
        output_json = {"status": "enabled", "code": 200}

        # CEL equivalent
        evaluator = CELEvaluator()
        program = evaluator.compile('json_path(output.json, "status") == "enabled"')
        result = evaluator.evaluate(program, {"output": {"json": output_json}})

        assert result.success is True
        assert result.value is True

    def test_json_path_nested_equivalence(self) -> None:
        """Test nested json_path matches old-style nested path behavior."""
        # Simulate old-style: pass_if_json_path = "data.items[0].name"
        output_json = {"data": {"items": [{"name": "test"}, {"name": "other"}]}}

        # CEL equivalent
        evaluator = CELEvaluator()
        program = evaluator.compile('json_path(output.json, "data.items[0].name") == "test"')
        result = evaluator.evaluate(program, {"output": {"json": output_json}})

        assert result.success is True
        assert result.value is True

    def test_output_matches_equivalence(self) -> None:
        """Test that CEL startsWith matches old-style pass_if_output_matches for anchored patterns."""
        # Simulate old-style: pass_if_output_matches = "^https://"
        stdout = "https://github.com/example/repo"

        # CEL equivalent (for ^ anchored patterns)
        evaluator = CELEvaluator()
        program = evaluator.compile('output.stdout.startsWith("https://")')
        result = evaluator.evaluate(program, {"output": {"stdout": stdout}})

        assert result.success is True
        assert result.value is True

    def test_exit_code_equivalence(self) -> None:
        """Test that CEL exit_code check matches old-style pass_if_exit_zero."""
        # Simulate old-style: pass_if_exit_zero = true
        output = {"exit_code": 0, "stdout": "success"}

        # CEL equivalent
        evaluator = CELEvaluator()
        program = evaluator.compile("output.exit_code == 0")
        result = evaluator.evaluate(program, {"output": output})

        assert result.success is True
        assert result.value is True

        # Test failure case
        output_fail = {"exit_code": 1, "stdout": "error"}
        result_fail = evaluator.evaluate(program, {"output": output_fail})

        assert result_fail.success is True
        assert result_fail.value is False

    def test_file_exists_for_pattern_pass(self, tmp_path: Path) -> None:
        """Test file_exists as CEL alternative to pattern pass file checking."""
        # Create test files
        (tmp_path / "SECURITY.md").write_text("# Security")
        (tmp_path / "README.md").write_text("# Readme")

        evaluator = CELEvaluator(repo_path=tmp_path)

        # Check single file exists
        program = evaluator.compile('file_exists("SECURITY.md")')
        result = evaluator.evaluate(program, {})
        assert result.success is True
        assert result.value is True

        # Check file doesn't exist
        program2 = evaluator.compile('file_exists("MISSING.md")')
        result2 = evaluator.evaluate(program2, {})
        assert result2.success is True
        assert result2.value is False

    def test_complex_expression_combining_checks(self) -> None:
        """Test complex CEL expression combining multiple old-style checks."""
        # This would require multiple old-style fields, but CEL can do it in one expression
        output = {
            "exit_code": 0,
            "stdout": "Build successful",
            "json": {"status": "pass", "coverage": 85},
        }

        evaluator = CELEvaluator()
        # Complex check: exit 0 AND status is pass AND coverage >= 80
        program = evaluator.compile(
            'output.exit_code == 0 && '
            'json_path(output.json, "status") == "pass" && '
            'json_path(output.json, "coverage") >= 80'
        )
        result = evaluator.evaluate(program, {"output": output})

        assert result.success is True
        assert result.value is True


class TestWarnControlCELExpressions:
    """Tests for improved CEL expressions used in WARN control checks.

    These validate the strengthened expressions from the openssf-baseline.toml
    that replace weak "existence-only" checks with meaningful validation.
    """

    # -- OSPS-LE-02.02 / LE-03.02: GH license endpoint (primary pass) --

    def test_gh_license_endpoint_pass_with_spdx(self) -> None:
        """GitHub returns a recognized SPDX id → PASS."""
        evaluator = CELEvaluator()
        expr = (
            'has(output.json.license) && output.json.license.spdx_id != ""'
            ' && output.json.license.spdx_id != "NOASSERTION"'
        )
        program = evaluator.compile(expr)
        context = {
            "output": {
                "json": {
                    "name": "LICENSE",
                    "path": "LICENSE",
                    "license": {"spdx_id": "Apache-2.0", "key": "apache-2.0"},
                }
            }
        }
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is True

    def test_gh_license_endpoint_fail_noassertion(self) -> None:
        """GitHub found a LICENSE file but couldn't classify it → not a PASS."""
        evaluator = CELEvaluator()
        expr = (
            'has(output.json.license) && output.json.license.spdx_id != ""'
            ' && output.json.license.spdx_id != "NOASSERTION"'
        )
        program = evaluator.compile(expr)
        context = {
            "output": {
                "json": {
                    "name": "LICENSE",
                    "license": {"spdx_id": "NOASSERTION", "key": "other"},
                }
            }
        }
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is False

    def test_gh_license_endpoint_fail_no_license_field(self) -> None:
        """Response missing the license field → not a PASS (handled by has() guard)."""
        evaluator = CELEvaluator()
        expr = (
            'has(output.json.license) && output.json.license.spdx_id != ""'
            ' && output.json.license.spdx_id != "NOASSERTION"'
        )
        program = evaluator.compile(expr)
        context = {"output": {"json": {"name": "LICENSE"}}}
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is False

    # -- OSPS-LE-02.02: ReleaseLicense --

    def test_release_license_pass_body_keyword(self) -> None:
        """Release body containing 'MIT License' should pass."""
        evaluator = CELEvaluator()
        expr = (
            'output.json.body.matches("(?i)(licen[cs]e|apache|mit\\\\s|bsd|gpl|mpl|isc|unlicense)")'
            ' || output.json.assets.exists(a, a.name.matches("(?i)^(license|copying|notice)"))'
        )
        program = evaluator.compile(expr)
        context = {
            "output": {
                "json": {
                    "body": "## Changes\n- Bug fixes\n\nReleased under MIT License",
                    "assets": [],
                }
            }
        }
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is True

    def test_release_license_pass_asset_name(self) -> None:
        """Release with LICENSE asset but no license in body should pass."""
        evaluator = CELEvaluator()
        expr = (
            'output.json.body.matches("(?i)(licen[cs]e|apache|mit\\\\s|bsd|gpl|mpl|isc|unlicense)")'
            ' || output.json.assets.exists(a, a.name.matches("(?i)^(license|copying|notice)"))'
        )
        program = evaluator.compile(expr)
        context = {
            "output": {
                "json": {
                    "body": "Bug fixes only",
                    "assets": [{"name": "LICENSE"}, {"name": "app.tar.gz"}],
                }
            }
        }
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is True

    def test_release_license_fail_no_mention(self) -> None:
        """Release with no license mention in body or assets should fail."""
        evaluator = CELEvaluator()
        expr = (
            'output.json.body.matches("(?i)(licen[cs]e|apache|mit\\\\s|bsd|gpl|mpl|isc|unlicense)")'
            ' || output.json.assets.exists(a, a.name.matches("(?i)^(license|copying|notice)"))'
        )
        program = evaluator.compile(expr)
        context = {
            "output": {
                "json": {
                    "body": "Bug fixes and performance improvements",
                    "assets": [{"name": "app.tar.gz"}],
                }
            }
        }
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is False

    # -- OSPS-BR-02.01: UniqueVersionIdentifiers --

    def test_unique_version_pass_semver_tag(self) -> None:
        """Release with semver tag should pass."""
        evaluator = CELEvaluator()
        expr = 'size(output.json) > 0 && output.json[0].tagName.matches("^v?[0-9]")'
        program = evaluator.compile(expr)
        context = {"output": {"json": [{"tagName": "v1.2.3"}]}}
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is True

    def test_unique_version_pass_no_v_prefix(self) -> None:
        """Release with numeric tag (no v prefix) should pass."""
        evaluator = CELEvaluator()
        expr = 'size(output.json) > 0 && output.json[0].tagName.matches("^v?[0-9]")'
        program = evaluator.compile(expr)
        context = {"output": {"json": [{"tagName": "1.0.0"}]}}
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is True

    def test_unique_version_fail_no_releases(self) -> None:
        """No releases should fail."""
        evaluator = CELEvaluator()
        expr = 'size(output.json) > 0 && output.json[0].tagName.matches("^v?[0-9]")'
        program = evaluator.compile(expr)
        context = {"output": {"json": []}}
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is False

    def test_unique_version_fail_non_semver(self) -> None:
        """Release with non-version tag like 'latest' should fail."""
        evaluator = CELEvaluator()
        expr = 'size(output.json) > 0 && output.json[0].tagName.matches("^v?[0-9]")'
        program = evaluator.compile(expr)
        context = {"output": {"json": [{"tagName": "latest"}]}}
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is False

    # -- OSPS-BR-02.02: ClearAssetAssociation --

    def test_clear_asset_any_release_has_assets(self) -> None:
        """If any release has assets (not just first), should pass."""
        evaluator = CELEvaluator()
        expr = "output.json.exists(r, size(r.assets) > 0)"
        program = evaluator.compile(expr)
        context = {
            "output": {
                "json": [
                    {"tagName": "v2.0.0", "assets": []},
                    {"tagName": "v1.0.0", "assets": [{"name": "app.tar.gz"}]},
                ]
            }
        }
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is True

    def test_clear_asset_no_releases_have_assets(self) -> None:
        """If no release has assets, should fail."""
        evaluator = CELEvaluator()
        expr = "output.json.exists(r, size(r.assets) > 0)"
        program = evaluator.compile(expr)
        context = {
            "output": {
                "json": [
                    {"tagName": "v2.0.0", "assets": []},
                    {"tagName": "v1.0.0", "assets": []},
                ]
            }
        }
        result = evaluator.evaluate(program, context)
        assert result.success is True
        assert result.value is False


class TestIssue220HasGuards:
    """Regression tests for issue #220.

    The openssf-baseline.toml CEL expressions for
    ``two_factor_requirement_enabled`` (OSPS-AC-01.01) and
    ``allow_deletions.enabled`` (OSPS-AC-03.02) used to crash with KeyError
    whenever the ``gh api`` response omitted those fields — which happens
    routinely for non-admin tokens or orgs that hide 2FA settings. The fix
    wraps each access with ``has()`` so missing fields cleanly evaluate
    to ``false`` (INCONCLUSIVE → fall through to the next pass) rather than
    raising.
    """

    # OSPS-AC-01.01 — two_factor_requirement_enabled
    OSPS_AC_01_01_EXPR = (
        "has(output.json.two_factor_requirement_enabled) && "
        "output.json.two_factor_requirement_enabled == true"
    )

    # OSPS-AC-03.02 — allow_deletions.enabled. Chained has() because the
    # outer key (`allow_deletions`) may itself be missing.
    OSPS_AC_03_02_EXPR = (
        "has(output.json.allow_deletions) && "
        "has(output.json.allow_deletions.enabled) && "
        "output.json.allow_deletions.enabled == false"
    )

    def _eval(self, expr: str, context: dict) -> object:
        evaluator = CELEvaluator()
        result = evaluator.evaluate(evaluator.compile(expr), context)
        assert result.success is True, f"CEL failed: {result.error}"
        return result.value

    def test_ac_01_01_2fa_enabled_passes(self) -> None:
        ctx = {"output": {"json": {"two_factor_requirement_enabled": True}}}
        assert self._eval(self.OSPS_AC_01_01_EXPR, ctx) is True

    def test_ac_01_01_2fa_disabled_fails(self) -> None:
        ctx = {"output": {"json": {"two_factor_requirement_enabled": False}}}
        assert self._eval(self.OSPS_AC_01_01_EXPR, ctx) is False

    def test_ac_01_01_2fa_missing_does_not_crash(self) -> None:
        """The original bug: missing key used to raise KeyError. Now → false."""
        ctx = {"output": {"json": {}}}
        assert self._eval(self.OSPS_AC_01_01_EXPR, ctx) is False

    def test_ac_03_02_deletions_locked_passes(self) -> None:
        ctx = {"output": {"json": {"allow_deletions": {"enabled": False}}}}
        assert self._eval(self.OSPS_AC_03_02_EXPR, ctx) is True

    def test_ac_03_02_deletions_allowed_fails(self) -> None:
        ctx = {"output": {"json": {"allow_deletions": {"enabled": True}}}}
        assert self._eval(self.OSPS_AC_03_02_EXPR, ctx) is False

    def test_ac_03_02_outer_key_missing_does_not_crash(self) -> None:
        """The original bug, outer key form: API omits `allow_deletions`."""
        ctx = {"output": {"json": {}}}
        assert self._eval(self.OSPS_AC_03_02_EXPR, ctx) is False

    def test_ac_03_02_inner_key_missing_does_not_crash(self) -> None:
        """The chained-has() case: outer present, leaf missing."""
        ctx = {"output": {"json": {"allow_deletions": {}}}}
        assert self._eval(self.OSPS_AC_03_02_EXPR, ctx) is False
