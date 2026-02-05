"""CEL expression evaluator for pass logic.

This module provides a sandboxed CEL (Common Expression Language) evaluator
for evaluating pass/fail conditions in control definitions. CEL is a non-Turing
complete language designed for safe evaluation of user-provided expressions.

Example:
    from darnit.sieve.cel_evaluator import CELEvaluator

    evaluator = CELEvaluator()

    # Compile once, evaluate many times
    program = evaluator.compile("output.exit_code == 0")

    # Evaluate with context
    result = evaluator.evaluate(program, {
        "output": {"exit_code": 0, "stdout": "success"}
    })
    # result.success == True, result.value == True

Security:
    - CEL is inherently sandboxed (no I/O, no imports, bounded execution)
    - Evaluation timeout enforced (default 1 second)
    - Only whitelisted custom functions available
    - No direct filesystem or network access
    - Memory limiting: CEL's non-Turing complete nature prevents unbounded
      memory allocation. Combined with timeout, this provides adequate protection.

Custom Functions:
    - file_exists(path): Check if a file exists relative to repo root
    - json_path(obj, path): Extract value using JMESPath expression
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from darnit.core.logging import get_logger

if TYPE_CHECKING:
    from celpy import celtypes

logger = get_logger("sieve.cel_evaluator")

# Default evaluation timeout in seconds
DEFAULT_TIMEOUT_SECONDS = 1.0


class CELTimeoutError(Exception):
    """Raised when CEL expression evaluation times out."""

    pass


class CELEvaluationError(Exception):
    """Raised when CEL expression evaluation fails."""

    pass


class CELCompilationError(Exception):
    """Raised when CEL expression compilation fails."""

    pass


@dataclass
class CELResult:
    """Result of CEL expression evaluation.

    Attributes:
        success: Whether evaluation completed without error
        value: The result value (typically bool for pass expressions)
        error: Error message if evaluation failed
    """

    success: bool
    value: Any = None
    error: str | None = None


@dataclass
class CELProgram:
    """A compiled CEL program ready for evaluation.

    Attributes:
        expression: The original CEL expression string
        ast: The compiled AST (celpy.Ast)
        program: The executable program (celpy.Runner)
    """

    expression: str
    ast: Any = None
    program: Any = None


@dataclass
class CELContext:
    """Context variables available during CEL evaluation.

    Attributes:
        output: Output from exec pass (stdout, stderr, exit_code, json)
        response: Response from API check (status_code, body, headers)
        files: List of matched file paths from pattern pass
        matches: List of match objects from pattern pass
        project: Project context from .project/ integration
        context: User-collected context values
        repo: Repository information (path, owner, name)
    """

    output: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    matches: list[dict[str, Any]] = field(default_factory=list)
    project: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    repo: dict[str, Any] = field(default_factory=dict)

    def to_cel_context(self) -> dict[str, Any]:
        """Convert to CEL-compatible context dictionary."""
        return {
            "output": self.output,
            "response": self.response,
            "files": self.files,
            "matches": self.matches,
            "project": self.project,
            "context": self.context,
            "repo": self.repo,
        }


class CELEvaluator:
    """Sandboxed CEL expression evaluator.

    This class provides compilation and evaluation of CEL expressions with:
    - Timeout protection (configurable, default 1 second)
    - Custom functions for file and JSON operations
    - Standard CEL context variables

    Example:
        evaluator = CELEvaluator(timeout_seconds=2.0)

        # Check exit code
        prog = evaluator.compile("output.exit_code == 0")
        ctx = CELContext(output={"exit_code": 0, "stdout": "ok"})
        result = evaluator.evaluate(prog, ctx)

        # Complex expression with custom function
        prog = evaluator.compile('file_exists("SECURITY.md")')
        result = evaluator.evaluate(prog, ctx, repo_path=Path("/repo"))
    """

    def __init__(
        self,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        repo_path: Path | None = None,
    ):
        """Initialize the CEL evaluator.

        Args:
            timeout_seconds: Maximum evaluation time before timeout
            repo_path: Repository path for file_exists function
        """
        self.timeout_seconds = timeout_seconds
        self.repo_path = repo_path
        self._env = None
        self._custom_functions: dict[str, Any] = {}

    def _get_environment(self) -> Any:
        """Get or create the CEL environment with declarations."""
        if self._env is not None:
            return self._env

        try:
            import celpy
            from celpy.c7nlib import C7N_Interpreted_Runner
        except ImportError as e:
            raise CELCompilationError(
                "cel-python not installed. Install with: pip install cel-python"
            ) from e

        # Create environment with C7N runner that supports custom functions
        self._env = celpy.Environment(runner_class=C7N_Interpreted_Runner)

        # Build custom functions dict (for passing to runner)
        self._build_custom_functions()

        return self._env

    def _build_custom_functions(self) -> None:
        """Build custom CEL functions following cel-python's pattern.

        Custom functions receive CEL types and must return CEL types.
        They are passed to the runner via the activation dict.
        """
        try:
            from celpy import celtypes
            from celpy.c7nlib import json_to_cel
        except ImportError:
            return

        # file_exists(path: string) -> bool
        # Checks if a file exists relative to repo root
        def file_exists_cel(path: celtypes.StringType) -> celtypes.BoolType:
            if self.repo_path is None:
                return celtypes.BoolType(False)
            file_path = self.repo_path / str(path)
            return celtypes.BoolType(file_path.exists())

        self._custom_functions["file_exists"] = file_exists_cel

        # json_path(obj: any, path: string) -> any
        # Extract value from object using JMESPath expression
        def json_path_cel(
            obj: celtypes.Value, path: celtypes.StringType
        ) -> celtypes.Value:
            try:
                import jmespath

                # Convert CEL value to Python for JMESPath
                py_obj = self._cel_to_python(obj)
                expression = jmespath.compile(str(path))
                result = expression.search(py_obj)
                # Convert back to CEL types
                return json_to_cel(result)
            except Exception:
                return None

        self._custom_functions["json_path"] = json_path_cel

    def _cel_to_python(self, value: Any) -> Any:
        """Convert CEL types to Python types for use with external libraries."""
        try:
            from celpy import celtypes
        except ImportError:
            return value

        if isinstance(value, celtypes.BoolType):
            return bool(value)
        if isinstance(value, (celtypes.IntType, celtypes.UintType)):
            return int(value)
        if isinstance(value, celtypes.DoubleType):
            return float(value)
        if isinstance(value, celtypes.StringType):
            return str(value)
        if isinstance(value, celtypes.BytesType):
            return bytes(value)
        if isinstance(value, celtypes.ListType):
            return [self._cel_to_python(v) for v in value]
        if isinstance(value, celtypes.MapType):
            return {
                self._cel_to_python(k): self._cel_to_python(v)
                for k, v in value.items()
            }
        if hasattr(value, "value"):
            return value.value
        return value

    def compile(self, expression: str) -> CELProgram:
        """Compile a CEL expression for later evaluation.

        Args:
            expression: The CEL expression string

        Returns:
            A compiled CELProgram ready for evaluation

        Raises:
            CELCompilationError: If the expression has syntax errors
        """
        try:
            import celpy
        except ImportError as e:
            raise CELCompilationError(
                "cel-python not installed. Install with: pip install cel-python"
            ) from e

        env = self._get_environment()

        try:
            ast = env.compile(expression)
            # Pass custom functions to the program for C7N runner
            program = env.program(ast, functions=self._custom_functions)

            return CELProgram(
                expression=expression,
                ast=ast,
                program=program,
            )
        except celpy.CELParseError as e:
            raise CELCompilationError(f"CEL syntax error: {e}") from e
        except celpy.CELSyntaxError as e:
            raise CELCompilationError(f"CEL syntax error: {e}") from e
        except Exception as e:
            raise CELCompilationError(f"CEL compilation failed: {e}") from e

    def evaluate(
        self,
        program: CELProgram,
        context: CELContext | dict[str, Any],
        repo_path: Path | None = None,
    ) -> CELResult:
        """Evaluate a compiled CEL program with context.

        Args:
            program: A compiled CELProgram
            context: CELContext or dict with evaluation context
            repo_path: Optional repository path (overrides instance default)

        Returns:
            CELResult with success status and value or error
        """
        if repo_path is not None:
            self.repo_path = repo_path

        # Convert context to dict if needed
        if isinstance(context, CELContext):
            ctx_dict = context.to_cel_context()
        else:
            ctx_dict = context

        # Evaluate with timeout
        try:
            result = self._evaluate_with_timeout(program, ctx_dict)
            return CELResult(success=True, value=result)
        except CELTimeoutError as e:
            return CELResult(success=False, error=str(e))
        except CELEvaluationError as e:
            return CELResult(success=False, error=str(e))
        except Exception as e:
            return CELResult(success=False, error=f"Evaluation error: {e}")

    def _evaluate_with_timeout(
        self, program: CELProgram, ctx_dict: dict[str, Any]
    ) -> Any:
        """Evaluate program with timeout protection.

        Uses threading-based timeout for cross-platform compatibility.
        """
        try:
            import celpy
        except ImportError as e:
            raise CELEvaluationError(
                "cel-python not installed. Install with: pip install cel-python"
            ) from e

        result_container: list[Any] = []
        error_container: list[Exception] = []

        def evaluate_thread() -> None:
            try:
                # Convert Python dict to CEL types
                activation = self._convert_to_cel_types(ctx_dict, celpy)

                # Evaluate (custom functions already registered with program)
                result = program.program.evaluate(activation)

                # Convert CEL types back to Python
                result_container.append(self._convert_from_cel_types(result))
            except Exception as e:
                error_container.append(e)

        thread = threading.Thread(target=evaluate_thread)
        thread.start()
        thread.join(timeout=self.timeout_seconds)

        if thread.is_alive():
            raise CELTimeoutError(
                f"CEL evaluation timed out after {self.timeout_seconds}s"
            )

        if error_container:
            raise CELEvaluationError(f"CEL evaluation failed: {error_container[0]}")

        if not result_container:
            raise CELEvaluationError("CEL evaluation returned no result")

        return result_container[0]

    def _convert_to_cel_types(
        self, data: dict[str, Any], celpy: Any
    ) -> dict[str, Any]:
        """Convert Python types to CEL types."""
        return celpy.json_to_cel(data)

    def _convert_from_cel_types(self, value: Any) -> Any:
        """Convert CEL types back to Python types."""
        try:
            from celpy import celtypes
        except ImportError:
            return value

        # Handle CEL BoolType, IntType, etc.
        if isinstance(value, celtypes.BoolType):
            return bool(value)
        if isinstance(value, celtypes.IntType):
            return int(value)
        if isinstance(value, celtypes.UintType):
            return int(value)
        if isinstance(value, celtypes.DoubleType):
            return float(value)
        if isinstance(value, celtypes.StringType):
            return str(value)
        if isinstance(value, celtypes.BytesType):
            return bytes(value)

        # Handle CEL ListType
        if isinstance(value, celtypes.ListType):
            return [self._convert_from_cel_types(v) for v in value]

        # Handle CEL MapType
        if isinstance(value, celtypes.MapType):
            return {
                self._convert_from_cel_types(k): self._convert_from_cel_types(v)
                for k, v in value.items()
            }

        # Fallback for other types
        if hasattr(value, "value"):
            return value.value

        return value

    def validate_expression(self, expression: str) -> tuple[bool, str | None]:
        """Validate a CEL expression without evaluating it.

        Args:
            expression: The CEL expression to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            self.compile(expression)
            return True, None
        except CELCompilationError as e:
            return False, str(e)


# Module-level convenience functions


def compile_cel(expression: str) -> CELProgram:
    """Compile a CEL expression.

    Args:
        expression: The CEL expression string

    Returns:
        A compiled CELProgram
    """
    evaluator = CELEvaluator()
    return evaluator.compile(expression)


def evaluate_cel(
    expression: str,
    context: dict[str, Any] | CELContext,
    repo_path: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> CELResult:
    """Compile and evaluate a CEL expression in one step.

    For repeated evaluations, prefer compiling once with compile_cel()
    and then using CELEvaluator.evaluate().

    Args:
        expression: The CEL expression string
        context: Evaluation context
        repo_path: Repository path for file_exists function
        timeout_seconds: Evaluation timeout

    Returns:
        CELResult with evaluation result
    """
    evaluator = CELEvaluator(timeout_seconds=timeout_seconds, repo_path=repo_path)
    program = evaluator.compile(expression)
    return evaluator.evaluate(program, context)


def validate_cel(expression: str) -> tuple[bool, str | None]:
    """Validate a CEL expression.

    Args:
        expression: The CEL expression to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    evaluator = CELEvaluator()
    return evaluator.validate_expression(expression)


__all__ = [
    # Classes
    "CELEvaluator",
    "CELProgram",
    "CELContext",
    "CELResult",
    # Exceptions
    "CELCompilationError",
    "CELEvaluationError",
    "CELTimeoutError",
    # Functions
    "compile_cel",
    "evaluate_cel",
    "validate_cel",
    # Constants
    "DEFAULT_TIMEOUT_SECONDS",
]
