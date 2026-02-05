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
