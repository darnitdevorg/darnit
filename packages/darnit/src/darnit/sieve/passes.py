"""Verification pass implementations for the sieve system."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import re
import os

from darnit.core.logging import get_logger

from .models import (
    CheckContext,
    PassResult,
    PassOutcome,
    VerificationPhase,
    LLMConsultationRequest,
)

logger = get_logger("sieve.passes")


def _file_exists(local_path: str, *patterns: str) -> Optional[str]:
    """Check if any file matching patterns exists. Returns first match or None."""
    for pattern in patterns:
        # Handle simple glob-like patterns
        if "*" in pattern:
            import glob

            matches = glob.glob(os.path.join(local_path, pattern))
            if matches:
                return matches[0]
        else:
            path = os.path.join(local_path, pattern)
            if os.path.isfile(path):
                return path
    return None


def _read_file(local_path: str, filename: str) -> Optional[str]:
    """Read file contents, return None if not found."""
    # Try multiple locations
    candidates = [
        os.path.join(local_path, filename),
        os.path.join(local_path, ".github", filename),
        os.path.join(local_path, "docs", filename),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except (IOError, OSError):
                pass
    return None


def _file_contains(
    local_path: str, file_patterns: List[str], content_pattern: str
) -> bool:
    """Check if any matching file contains the content pattern."""
    for file_pattern in file_patterns:
        content = _read_file(local_path, file_pattern)
        if content and re.search(content_pattern, content, re.IGNORECASE):
            return True
    return False


@dataclass
class DeterministicPass:
    """Pass 1: Deterministic checks (file existence, API booleans, config)."""

    phase: VerificationPhase = field(
        default=VerificationPhase.DETERMINISTIC, init=False
    )

    # Configurable checks
    file_must_exist: Optional[List[str]] = None  # Any of these patterns
    file_must_not_exist: Optional[List[str]] = None
    api_check: Optional[Callable[[str, str], PassResult]] = None
    config_check: Optional[Callable[[CheckContext], PassResult]] = None

    def _locate_file_with_locator(self, context: CheckContext) -> tuple[Optional[str], str, bool]:
        """Try to locate file using UnifiedLocator if available.

        Returns:
            Tuple of (found_path, source, should_sync)
            - found_path: Path to file if found, None otherwise
            - source: "config", "discovered", "fallback", or "none"
            - should_sync: Whether to sync the discovery to .project/
        """
        # If locator is available and configured, use it
        if context.locator and context.locator_config:
            result = context.locator.locate(context.control_id, context.locator_config)

            if result.success and result.found and result.found.path:
                # Store locate result in gathered_evidence for later passes
                context.gathered_evidence["locate_result"] = {
                    "path": result.found.path,
                    "source": result.source,
                    "searched": result.searched_locations,
                }

                # Auto-sync if recommended
                if result.needs_sync:
                    try:
                        context.locator.sync_to_project(
                            context.control_id,
                            result.found,
                            context.locator_config,
                        )
                        logger.debug(f"Auto-synced {result.found.path} to .project/")
                    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, IOError, OSError) as e:
                        logger.warning(f"Failed to sync to .project/: {e}")

                return os.path.join(context.local_path, result.found.path), result.source, result.needs_sync

            # Locator didn't find it, store that info
            context.gathered_evidence["locate_result"] = {
                "path": None,
                "source": "none",
                "searched": result.searched_locations,
            }

            return None, "none", False

        # No locator, return indicator to use fallback
        return None, "fallback", False

    def execute(self, context: CheckContext) -> PassResult:
        checks_performed = []

        # File existence checks
        if self.file_must_exist:
            checks_performed.append(f"file_exists({self.file_must_exist})")

            # Try locator first
            located_path, source, _ = self._locate_file_with_locator(context)

            if source not in ("fallback", "none") and located_path:
                # Found via locator
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.PASS,
                    message=f"Required file found via {source}: {os.path.basename(located_path)}",
                    evidence={
                        "file_found": located_path,
                        "locate_source": source,
                        "files_checked": self.file_must_exist,
                    },
                )

            # Fall back to direct pattern search
            found = _file_exists(context.local_path, *self.file_must_exist)
            if found:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.PASS,
                    message=f"Required file found: {os.path.basename(found)}",
                    evidence={"file_found": found, "files_checked": self.file_must_exist},
                )
            else:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.FAIL,
                    message=f"Required file not found: {self.file_must_exist}",
                    evidence={"files_checked": self.file_must_exist},
                )

        if self.file_must_not_exist:
            checks_performed.append(f"file_not_exists({self.file_must_not_exist})")
            found = _file_exists(context.local_path, *self.file_must_not_exist)
            if found:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.FAIL,
                    message=f"Prohibited file found: {os.path.basename(found)}",
                    evidence={"file_found": found},
                )

        # API check
        if self.api_check:
            checks_performed.append("api_check()")
            try:
                return self.api_check(context.owner, context.repo)
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, IOError, OSError) as e:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.ERROR,
                    message=f"API check failed: {str(e)}",
                    evidence={"error": str(e)},
                )

        # Config check
        if self.config_check:
            checks_performed.append("config_check()")
            try:
                return self.config_check(context)
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, IOError, OSError) as e:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.ERROR,
                    message=f"Config check failed: {str(e)}",
                    evidence={"error": str(e)},
                )

        # No deterministic check configured - inconclusive
        return PassResult(
            phase=self.phase,
            outcome=PassOutcome.INCONCLUSIVE,
            message="No deterministic check available",
            details={"checks_performed": checks_performed},
        )

    def describe(self) -> str:
        parts = []
        if self.file_must_exist:
            parts.append(f"Check file exists: {self.file_must_exist}")
        if self.file_must_not_exist:
            parts.append(f"Check file absent: {self.file_must_not_exist}")
        if self.api_check:
            parts.append("GitHub API check")
        if self.config_check:
            parts.append("Configuration check")
        return "; ".join(parts) or "No deterministic checks"


@dataclass
class PatternPass:
    """Pass 2: Pattern/heuristic checks (regex, content analysis)."""

    phase: VerificationPhase = field(default=VerificationPhase.PATTERN, init=False)

    # Configurable pattern checks
    file_patterns: Optional[List[str]] = None  # Files to search
    content_patterns: Optional[Dict[str, str]] = None  # name -> regex
    pass_if_any_match: bool = True  # vs pass_if_all_match
    fail_if_no_match: bool = False  # Return FAIL instead of INCONCLUSIVE
    custom_analyzer: Optional[Callable[[CheckContext], PassResult]] = None

    def execute(self, context: CheckContext) -> PassResult:
        checks_performed = []
        matches_found = []

        # Content pattern matching
        if self.file_patterns and self.content_patterns:
            for pattern_name, regex in self.content_patterns.items():
                checks_performed.append(f"pattern({pattern_name})")
                if _file_contains(context.local_path, self.file_patterns, regex):
                    matches_found.append(pattern_name)

            if self.pass_if_any_match and matches_found:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.PASS,
                    message=f"Pattern matches found: {matches_found}",
                    evidence={"patterns_matched": matches_found},
                )
            elif not self.pass_if_any_match and len(matches_found) == len(
                self.content_patterns
            ):
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.PASS,
                    message="All required patterns matched",
                    evidence={"patterns_matched": matches_found},
                )
            elif matches_found:
                # Some but not all - inconclusive, let next pass decide
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message=f"Partial pattern matches: {matches_found}",
                    evidence={
                        "patterns_matched": matches_found,
                        "patterns_missing": list(
                            set(self.content_patterns.keys()) - set(matches_found)
                        ),
                    },
                )
            else:
                # No matches
                if self.fail_if_no_match:
                    return PassResult(
                        phase=self.phase,
                        outcome=PassOutcome.FAIL,
                        message="No pattern matches found",
                        evidence={"patterns_checked": list(self.content_patterns.keys())},
                    )
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message="No pattern matches found",
                    evidence={"patterns_checked": list(self.content_patterns.keys())},
                )

        # Custom analyzer
        if self.custom_analyzer:
            checks_performed.append("custom_analyzer()")
            try:
                return self.custom_analyzer(context)
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, IOError, OSError) as e:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.ERROR,
                    message=f"Custom analyzer failed: {str(e)}",
                    evidence={"error": str(e)},
                )

        return PassResult(
            phase=self.phase,
            outcome=PassOutcome.INCONCLUSIVE,
            message="No pattern checks available",
            details={"checks_performed": checks_performed},
        )

    def describe(self) -> str:
        parts = []
        if self.content_patterns:
            parts.append(
                f"Pattern match in {self.file_patterns}: {list(self.content_patterns.keys())}"
            )
        if self.custom_analyzer:
            parts.append("Custom content analyzer")
        return "; ".join(parts) or "No pattern checks"


@dataclass
class LLMPass:
    """Pass 3: LLM-assisted verification via consultation protocol."""

    phase: VerificationPhase = field(default=VerificationPhase.LLM, init=False)

    # Consultation configuration
    prompt_template: str = ""
    files_to_include: Optional[List[str]] = None  # Include file contents in context
    analysis_hints: List[str] = field(default_factory=list)
    confidence_threshold: float = 0.8
    max_file_content_length: int = 5000  # Truncate long files

    def execute(self, context: CheckContext) -> PassResult:
        # Gather context for LLM
        gathered_context = dict(context.gathered_evidence)

        if self.files_to_include:
            for pattern in self.files_to_include:
                content = _read_file(context.local_path, pattern)
                if content:
                    # Truncate long content
                    if len(content) > self.max_file_content_length:
                        content = (
                            content[: self.max_file_content_length]
                            + f"\n... [truncated, {len(content)} total chars]"
                        )
                    gathered_context[f"file:{pattern}"] = content

        # Format prompt template with context
        try:
            formatted_prompt = self.prompt_template.format(
                control_id=context.control_id,
                owner=context.owner,
                repo=context.repo,
                local_path=context.local_path,
                **context.control_metadata,
            )
        except KeyError:
            # If template has unfilled placeholders, use as-is
            formatted_prompt = self.prompt_template

        # Create consultation request
        request = LLMConsultationRequest(
            control_id=context.control_id,
            control_name=context.control_metadata.get("name", context.control_id),
            control_description=context.control_metadata.get("full", ""),
            prompt=formatted_prompt,
            context=gathered_context,
            analysis_hints=self.analysis_hints,
            expected_response='{"status": "PASS|FAIL|INCONCLUSIVE", "confidence": 0.0-1.0, "reasoning": "...", "evidence": [...]}',
        )

        # Return result that signals consultation needed
        return PassResult(
            phase=self.phase,
            outcome=PassOutcome.INCONCLUSIVE,
            message="LLM consultation required",
            details={
                "consultation_request": request,
                "confidence_threshold": self.confidence_threshold,
            },
        )

    def describe(self) -> str:
        preview = self.prompt_template[:80] + "..." if len(self.prompt_template) > 80 else self.prompt_template
        return f"LLM analysis: {preview}"


@dataclass
class ManualPass:
    """Pass 4: Manual verification (always returns WARN with steps)."""

    phase: VerificationPhase = field(default=VerificationPhase.MANUAL, init=False)

    verification_steps: List[str] = field(default_factory=list)
    verification_docs_url: Optional[str] = None

    def execute(self, context: CheckContext) -> PassResult:
        steps = self.verification_steps or [
            f"Review {context.control_id} requirements in OSPS specification",
            "Manually verify compliance based on project context",
            "Document verification results",
        ]

        return PassResult(
            phase=self.phase,
            outcome=PassOutcome.INCONCLUSIVE,  # Manual always inconclusive (returns WARN)
            message="Manual verification required",
            details={"verification_steps": steps, "docs_url": self.verification_docs_url},
        )

    def describe(self) -> str:
        return f"Manual verification: {len(self.verification_steps)} steps"


@dataclass
class ExecPass:
    """Execute external command for verification.

    Runs an external command (like trivy, kusari, scorecard) and evaluates
    the result based on exit code and/or output patterns.

    Security:
        - Commands are executed as a list (no shell interpolation)
        - Variable substitution ($PATH, $OWNER, $REPO) replaces whole list elements only
        - No string interpolation that could enable injection

    Example:
        exec_pass = ExecPass(
            command=["kusari", "repo", "scan", "$PATH", "HEAD"],
            pass_exit_codes=[0],
            fail_if_output_matches=r"Flagged Issues Detected",
        )
        result = exec_pass.execute(context)
    """

    phase: VerificationPhase = field(default=VerificationPhase.DETERMINISTIC, init=False)

    # Command as list - supports $PATH, $OWNER, $REPO substitution
    command: List[str] = field(default_factory=list)

    # Exit codes that indicate pass
    pass_exit_codes: List[int] = field(default_factory=lambda: [0])

    # Exit codes that indicate fail (others = inconclusive)
    fail_exit_codes: Optional[List[int]] = None

    # Output format for parsing
    output_format: str = "text"

    # Output pattern matching
    pass_if_output_matches: Optional[str] = None
    fail_if_output_matches: Optional[str] = None

    # JSON output evaluation
    pass_if_json_path: Optional[str] = None
    pass_if_json_value: Optional[str] = None

    # Execution settings
    timeout: int = 300
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)

    def _substitute_variables(self, context: CheckContext) -> List[str]:
        """Substitute variables in command list.

        Security: Since we use shell=False and values come from trusted
        CheckContext (owner/repo from git remote), string substitution is safe.
        The subprocess module will pass arguments directly without shell parsing.

        Supports both whole-element substitution ($OWNER) and partial
        substitution within strings (/repos/$OWNER/$REPO).
        """
        substitutions = {
            "$PATH": context.local_path,
            "$OWNER": context.owner,
            "$REPO": context.repo,
            "$BRANCH": context.default_branch,
            "$CONTROL": context.control_id,
        }

        result = []
        for arg in self.command:
            if arg in substitutions:
                # Whole-element substitution
                result.append(substitutions[arg])
            else:
                # Check for partial substitution within the string
                modified = arg
                for var, value in substitutions.items():
                    if var in modified and value is not None:
                        modified = modified.replace(var, str(value))
                result.append(modified)
        return result

    def execute(self, context: CheckContext) -> PassResult:
        import subprocess
        import json as json_lib

        if not self.command:
            return PassResult(
                phase=self.phase,
                outcome=PassOutcome.ERROR,
                message="No command specified for ExecPass",
            )

        # Substitute variables
        cmd = self._substitute_variables(context)

        # Prepare environment
        exec_env = dict(os.environ)
        exec_env.update(self.env)

        # Determine working directory
        working_dir = self.cwd or context.local_path

        logger.debug(f"ExecPass executing: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=working_dir,
                env=exec_env,
                shell=False,  # Security: never use shell
            )

            stdout = result.stdout
            stderr = result.stderr
            exit_code = result.returncode

            # First check output patterns (take precedence over exit codes)
            if self.fail_if_output_matches:
                if re.search(self.fail_if_output_matches, stdout, re.IGNORECASE):
                    return PassResult(
                        phase=self.phase,
                        outcome=PassOutcome.FAIL,
                        message=f"Command output matched fail pattern",
                        evidence={
                            "command": cmd[0],
                            "exit_code": exit_code,
                            "pattern_matched": self.fail_if_output_matches,
                        },
                        details={"stdout": stdout[:1000], "stderr": stderr[:500]},
                    )

            if self.pass_if_output_matches:
                if re.search(self.pass_if_output_matches, stdout, re.IGNORECASE):
                    return PassResult(
                        phase=self.phase,
                        outcome=PassOutcome.PASS,
                        message=f"Command output matched pass pattern",
                        evidence={
                            "command": cmd[0],
                            "exit_code": exit_code,
                            "pattern_matched": self.pass_if_output_matches,
                        },
                    )

            # Check JSON output if configured
            if self.output_format == "json" and self.pass_if_json_path:
                try:
                    data = json_lib.loads(stdout)
                    # Simple dot-notation path evaluation
                    value = self._extract_json_path(data, self.pass_if_json_path)
                    if str(value) == self.pass_if_json_value:
                        return PassResult(
                            phase=self.phase,
                            outcome=PassOutcome.PASS,
                            message=f"JSON path {self.pass_if_json_path} == {self.pass_if_json_value}",
                            evidence={"command": cmd[0], "json_value": value},
                        )
                except json_lib.JSONDecodeError:
                    logger.warning(f"ExecPass: Could not parse JSON output from {cmd[0]}")

            # Fall back to exit code evaluation
            if exit_code in self.pass_exit_codes:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.PASS,
                    message=f"Command {cmd[0]} exited with {exit_code}",
                    evidence={"command": cmd[0], "exit_code": exit_code},
                )
            elif self.fail_exit_codes and exit_code in self.fail_exit_codes:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.FAIL,
                    message=f"Command {cmd[0]} exited with {exit_code}",
                    evidence={"command": cmd[0], "exit_code": exit_code},
                    details={"stderr": stderr[:500]},
                )
            else:
                return PassResult(
                    phase=self.phase,
                    outcome=PassOutcome.INCONCLUSIVE,
                    message=f"Command {cmd[0]} exited with {exit_code} (not in pass/fail lists)",
                    evidence={"command": cmd[0], "exit_code": exit_code},
                )

        except subprocess.TimeoutExpired:
            return PassResult(
                phase=self.phase,
                outcome=PassOutcome.ERROR,
                message=f"Command {cmd[0]} timed out after {self.timeout}s",
                evidence={"command": cmd[0], "timeout": self.timeout},
            )
        except FileNotFoundError:
            return PassResult(
                phase=self.phase,
                outcome=PassOutcome.ERROR,
                message=f"Command not found: {cmd[0]}",
                evidence={"command": cmd[0]},
            )
        except (OSError, subprocess.SubprocessError) as e:
            return PassResult(
                phase=self.phase,
                outcome=PassOutcome.ERROR,
                message=f"Command execution failed: {e}",
                evidence={"command": cmd[0], "error": str(e)},
            )

    def _extract_json_path(self, data: Any, path: str) -> Any:
        """Extract value from JSON using simple dot notation.

        Args:
            data: JSON data (dict/list)
            path: Dot-separated path like "checks.BranchProtection.score"

        Returns:
            Extracted value or None if not found

        # TODO: Policy Language Support (Future Enhancement)
        # =================================================
        # The current JSON evaluation is intentionally simple. Future versions
        # should support more expressive policy languages for complex conditions.
        #
        # Candidates to evaluate:
        #
        # 1. CEL (Common Expression Language) - Google's expression language
        #    - Used by Kubernetes, Firebase, GCP IAM
        #    - Good for boolean expressions with type safety
        #    - Example: `data.score >= 7.0 && data.checks.BranchProtection.pass`
        #    - Python: cel-python or py-cel
        #
        # 2. CUE - Configuration language with validation
        #    - Strong typing and constraints
        #    - Example: `score: >=7.0, checks: BranchProtection: pass: true`
        #    - Python: cuelang bindings (limited)
        #
        # 3. Rego (OPA) - Open Policy Agent's policy language
        #    - Widely used for policy-as-code
        #    - Example: `allow { input.score >= 7; input.checks.BranchProtection.pass }`
        #    - Python: opa-python or subprocess to opa
        #
        # 4. JSONPath with extensions
        #    - Familiar syntax, widely supported
        #    - Example: `$.checks[?(@.score >= 7)]`
        #    - Python: jsonpath-ng
        #
        # Recommended approach:
        # - Add `policy` field to ExecPassConfig for CEL/Rego expressions
        # - Keep simple pass_if_json_path/pass_if_json_value for basic cases
        # - Evaluate CEL first (most portable, good tooling)
        # - Consider OPA/Rego for complex policy scenarios
        #
        # See: docs/declarative-configuration.md "Future Enhancements" section
        """
        parts = path.lstrip("$.").split(".")
        current = data

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx]
                except (ValueError, IndexError):
                    return None
            else:
                return None

            if current is None:
                return None

        return current

    def describe(self) -> str:
        cmd_preview = " ".join(self.command[:3])
        if len(self.command) > 3:
            cmd_preview += "..."
        return f"Execute: {cmd_preview}"
