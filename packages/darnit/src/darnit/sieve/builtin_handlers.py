"""Built-in sieve handlers for the confidence gradient pipeline.

These handlers implement the core verification logic dispatched
from TOML HandlerInvocation configs via the SieveHandlerRegistry.

Built-in verification handlers:
    - file_exists: Check file existence from a list of paths
    - exec: Run external command, evaluate exit code / CEL expr
    - regex: Match regex patterns in file content
    - llm_eval: AI evaluation with confidence threshold
    - manual_steps: Human verification checklist

Built-in remediation handlers:
    - file_create: Create a file from a template
    - api_call: Make an HTTP API call
    - project_update: Update .project/project.yaml values
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

from .handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Verification Handlers
# =============================================================================


def file_exists_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Check if any file from a list of paths exists.

    Config fields:
        files: list[str] - File paths/patterns to check (any match = pass)
        use_locator: bool - If true, files are populated from locator.discover at load time
    """
    files = config.get("files", [])
    if not files:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No files specified for existence check",
        )

    for pattern in files:
        if "*" in pattern:
            import glob

            matches = glob.glob(os.path.join(context.local_path, pattern))
            if matches:
                found = matches[0]
                rel_path = os.path.relpath(found, context.local_path)
                return HandlerResult(
                    status=HandlerResultStatus.PASS,
                    message=f"Required file found: {rel_path}",
                    confidence=1.0,
                    evidence={"found_file": found, "relative_path": rel_path, "files_checked": files},
                )
        else:
            path = os.path.join(context.local_path, pattern)
            if os.path.isfile(path):
                return HandlerResult(
                    status=HandlerResultStatus.PASS,
                    message=f"Required file found: {pattern}",
                    confidence=1.0,
                    evidence={"found_file": path, "relative_path": pattern, "files_checked": files},
                )

    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message=f"None of the required files found: {files}",
        confidence=1.0,
        evidence={"files_checked": files},
    )


def exec_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Run an external command and evaluate the result.

    Config fields:
        command: list[str] - Command to execute (supports $OWNER, $REPO, $BRANCH, $PATH)
        pass_exit_codes: list[int] - Exit codes that indicate pass (default: [0])
        fail_exit_codes: list[int] | None - Exit codes that indicate fail
        output_format: str - How to parse output ("text", "json")
        expr: str | None - CEL expression for evaluation
        timeout: int - Timeout in seconds (default: 300)
        env: dict[str, str] - Extra environment variables
        cwd: str | None - Working directory
    """
    command = config.get("command", [])
    if not command:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="No command specified for exec handler",
        )

    pass_exit_codes = config.get("pass_exit_codes", [0])
    fail_exit_codes = config.get("fail_exit_codes")
    timeout = config.get("timeout", 300)
    env_extra = config.get("env", {})
    cwd = config.get("cwd", context.local_path)

    # Substitute variables in command
    substitutions = {
        "$OWNER": context.owner,
        "$REPO": context.repo,
        "$BRANCH": context.default_branch,
        "$PATH": context.local_path,
    }
    resolved_cmd = []
    for arg in command:
        for var, val in substitutions.items():
            arg = arg.replace(var, val)
        resolved_cmd.append(arg)

    # Build environment
    env = os.environ.copy()
    env.update(env_extra)

    try:
        proc = subprocess.run(
            resolved_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Command timed out after {timeout}s: {resolved_cmd[0]}",
            evidence={"command": resolved_cmd, "timeout": timeout},
        )
    except FileNotFoundError:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Command not found: {resolved_cmd[0]}",
            evidence={"command": resolved_cmd},
        )

    evidence: dict[str, Any] = {
        "command": resolved_cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[:2000] if proc.stdout else "",
        "stderr": proc.stderr[:2000] if proc.stderr else "",
    }

    # Parse JSON output if requested
    output_format = config.get("output_format", "text")
    if output_format == "json" and proc.stdout:
        try:
            import json

            evidence["json"] = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Failed to parse JSON output from command")

    # CEL expression evaluation — takes precedence over exit code when present
    expr = config.get("expr")
    if expr:
        evidence["expr"] = expr
        try:
            from .cel_evaluator import evaluate_cel

            cel_context = {
                "output": {
                    "stdout": proc.stdout or "",
                    "stderr": proc.stderr or "",
                    "exit_code": proc.returncode,
                    "json": evidence.get("json"),
                },
            }
            cel_result = evaluate_cel(expr, cel_context)
            if cel_result.success:
                if cel_result.value:
                    return HandlerResult(
                        status=HandlerResultStatus.PASS,
                        message="CEL expression passed",
                        confidence=1.0,
                        evidence=evidence,
                    )
                else:
                    # CEL evaluated to false — return INCONCLUSIVE so the
                    # next pass in the pipeline can try (e.g., file_exists)
                    return HandlerResult(
                        status=HandlerResultStatus.INCONCLUSIVE,
                        message="CEL expression evaluated to false",
                        evidence=evidence,
                    )
            else:
                logger.debug(f"CEL evaluation failed: {cel_result.error}")
                # Fall through to exit code evaluation
        except Exception as e:
            logger.debug(f"CEL evaluator unavailable: {e}")
            # Fall through to exit code evaluation

    # Exit code evaluation (fallback when no expr or CEL fails)
    if proc.returncode in pass_exit_codes:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Command passed (exit code {proc.returncode})",
            confidence=1.0,
            evidence=evidence,
        )
    elif fail_exit_codes and proc.returncode in fail_exit_codes:
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"Command failed (exit code {proc.returncode})",
            confidence=1.0,
            evidence=evidence,
        )
    else:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"Command exited with unexpected code {proc.returncode}",
            evidence=evidence,
        )


def regex_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Match regex patterns in file content.

    Supports two config formats:

    **Legacy (singular)**::

        file: str - Single file path (supports $FOUND_FILE from evidence)
        pattern: str - Single regex pattern

    **TOML multi-file/multi-pattern**::

        files: list[str] - File paths/globs to search
        pattern: dict - With nested ``patterns`` dict of named regexes
        pass_if_any: bool - True = PASS if ANY file×pattern matches (default: true)

    **Exclude mode** (for negative checks like binary detection)::

        exclude_files: list[str] - Globs that must NOT match any files
        mode: "exclude_must_not_exist" - PASS if no files match the globs

    Common fields:
        min_matches: int - Minimum matches per pattern per file (default: 1)
        must_not_match: bool - Invert: fail if pattern matches (default: false)
    """
    # --- Exclude mode: PASS if no files match the globs ---
    mode = config.get("mode", "")
    exclude_files = config.get("exclude_files", [])
    if mode == "exclude_must_not_exist" and exclude_files:
        return _regex_exclude_mode(exclude_files, context)

    # --- Resolve file list ---
    file_paths = _resolve_regex_files(config, context)
    if file_paths is None:
        # Error result already determined
        return _regex_no_files_result(config, context)

    # --- Resolve patterns ---
    patterns = _resolve_regex_patterns(config)
    if not patterns:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="Missing pattern for regex handler",
        )

    # --- Match patterns across files ---
    min_matches = config.get("min_matches", 1)
    must_not_match = config.get("must_not_match", False)
    pass_if_any = config.get("pass_if_any", True)

    return _regex_match_files(
        file_paths, patterns, min_matches, must_not_match, pass_if_any,
    )


def _regex_exclude_mode(
    exclude_globs: list[str], context: HandlerContext,
) -> HandlerResult:
    """Handle exclude_must_not_exist mode: PASS if no files match globs."""
    import glob as globmod

    found: list[str] = []
    for pattern in exclude_globs:
        matches = globmod.glob(
            os.path.join(context.local_path, pattern), recursive=True,
        )
        found.extend(matches)

    if not found:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message="No excluded files found",
            confidence=1.0,
            evidence={"exclude_globs": exclude_globs, "found_count": 0},
        )

    rel_paths = [os.path.relpath(f, context.local_path) for f in found[:10]]
    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message=f"Found {len(found)} excluded file(s): {', '.join(rel_paths[:5])}",
        confidence=1.0,
        evidence={
            "exclude_globs": exclude_globs,
            "found_count": len(found),
            "found_files": rel_paths,
        },
    )


def _resolve_regex_files(
    config: dict[str, Any], context: HandlerContext,
) -> list[str] | None:
    """Resolve the list of absolute file paths to search.

    Returns a list of absolute paths, or None if no files could be resolved.
    """
    import glob as globmod

    # Multi-file format: files = ["README.md", "*.yml"]
    files_list = config.get("files", [])
    if files_list:
        resolved: list[str] = []
        for file_pattern in files_list:
            if "*" in file_pattern or "?" in file_pattern:
                matches = globmod.glob(
                    os.path.join(context.local_path, file_pattern),
                    recursive=True,
                )
                resolved.extend(m for m in matches if os.path.isfile(m))
            else:
                full = os.path.join(context.local_path, file_pattern)
                if os.path.isfile(full):
                    resolved.append(full)
        return resolved if resolved else None

    # Legacy singular format: file = "README.md" or file = "$FOUND_FILE"
    file_path = config.get("file", "")
    if not file_path:
        return None

    if file_path == "$FOUND_FILE":
        file_path = context.gathered_evidence.get("found_file", "")
        if not file_path:
            return None

    if not os.path.isabs(file_path):
        file_path = os.path.join(context.local_path, file_path)

    if os.path.isfile(file_path):
        return [file_path]
    return None


def _regex_no_files_result(
    config: dict[str, Any], context: HandlerContext,
) -> HandlerResult:
    """Return the appropriate result when no files could be resolved."""
    file_path = config.get("file", "")
    if file_path == "$FOUND_FILE" and not context.gathered_evidence.get("found_file"):
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="$FOUND_FILE referenced but no file found in evidence",
        )

    files_list = config.get("files", [])
    if files_list:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"No files found matching: {files_list}",
            evidence={"files_checked": files_list},
        )

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="Missing file or pattern for regex handler",
    )


def _resolve_regex_patterns(config: dict[str, Any]) -> dict[str, str]:
    """Resolve patterns from config into a name→regex dict.

    Supports:
    - pattern: str → {"pattern": str}
    - pattern: {patterns: {name: regex, ...}} → {name: regex, ...}
    """
    raw = config.get("pattern", "")

    if isinstance(raw, str) and raw:
        return {"pattern": raw}

    if isinstance(raw, dict):
        nested = raw.get("patterns", {})
        if isinstance(nested, dict) and nested:
            return dict(nested)

    return {}


def _regex_match_files(
    file_paths: list[str],
    patterns: dict[str, str],
    min_matches: int,
    must_not_match: bool,
    pass_if_any: bool,
) -> HandlerResult:
    """Match patterns across files and return a result."""
    all_results: list[dict[str, Any]] = []
    any_match = False

    for fpath in file_paths:
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue

        for pname, pregex in patterns.items():
            matches = re.findall(pregex, content, re.MULTILINE | re.IGNORECASE)
            match_count = len(matches)
            matched = match_count >= min_matches

            all_results.append({
                "file": fpath,
                "pattern_name": pname,
                "pattern": pregex,
                "match_count": match_count,
                "matched": matched,
                "matches_preview": matches[:3],
            })

            if matched:
                any_match = True

    evidence: dict[str, Any] = {
        "files_checked": len(file_paths),
        "patterns_checked": list(patterns.keys()),
        "results": all_results[:20],
        "any_match": any_match,
    }

    if must_not_match:
        if not any_match:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="Pattern not found in any file (as expected)",
                confidence=0.8,
                evidence=evidence,
            )
        matched_files = [r["file"] for r in all_results if r["matched"]]
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"Pattern found in {len(matched_files)} file(s) (should not match)",
            confidence=0.8,
            evidence=evidence,
        )

    if pass_if_any:
        if any_match:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message=f"Pattern matched in {sum(1 for r in all_results if r['matched'])} result(s)",
                confidence=0.8,
                evidence=evidence,
            )
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message="Pattern not found in any file",
            confidence=0.7,
            evidence=evidence,
        )

    # pass_if_any=False: ALL pattern×file combos must match
    all_matched = all(r["matched"] for r in all_results) if all_results else False
    if all_matched:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"All {len(all_results)} pattern checks matched",
            confidence=0.8,
            evidence=evidence,
        )
    failed = [r for r in all_results if not r["matched"]]
    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message=f"{len(failed)} of {len(all_results)} pattern checks failed",
        confidence=0.7,
        evidence=evidence,
    )


def llm_eval_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Request LLM evaluation with confidence threshold.

    Config fields:
        prompt: str - Prompt for LLM evaluation
        confidence_threshold: float - Minimum confidence to accept (default: 0.8)
        analysis_hints: list[str] - Hints for the LLM

    Note: This handler returns INCONCLUSIVE with a consultation request in the details,
    since actual LLM invocation happens at the MCP server level.
    """
    prompt = config.get("prompt", "")
    if not prompt:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No prompt specified for LLM evaluation",
        )

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="LLM consultation requested",
        details={
            "consultation_request": {
                "prompt": prompt,
                "control_id": context.control_id,
                "confidence_threshold": config.get("confidence_threshold", 0.8),
                "analysis_hints": config.get("analysis_hints", []),
                "gathered_evidence": context.gathered_evidence,
            },
        },
    )


def manual_steps_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Provide manual verification steps for human review.

    Config fields:
        steps: list[str] - Human-readable verification steps
    """
    steps = config.get("steps", ["Verify this control manually"])

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="Manual verification required",
        evidence={"verification_steps": steps},
        details={"verification_steps": steps},
    )


# =============================================================================
# Remediation Handlers
# =============================================================================


def file_create_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Create a file from a template or content.

    Config fields:
        path: str - Destination file path (relative to repo)
        template: str - Template name to use (looked up from framework templates)
        content: str - Direct content (used if template not specified)
        overwrite: bool - Whether to overwrite existing files (default: false)
    """
    path = config.get("path", "")
    if not path:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="No path specified for file creation",
        )

    full_path = os.path.join(context.local_path, path)

    if os.path.exists(full_path) and not config.get("overwrite", False):
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"File already exists: {path}",
            evidence={"path": path, "action": "skipped"},
        )

    content = config.get("content", "")
    if not content:
        # Template resolution would happen at a higher level
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"No content or template for file creation: {path}",
            evidence={"path": path},
        )

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Failed to create file: {e}",
            evidence={"path": path, "error": str(e)},
        )

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"Created file: {path}",
        confidence=1.0,
        evidence={"path": path, "action": "created"},
    )


def api_call_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Make an HTTP API call for remediation.

    Config fields:
        method: str - HTTP method (default: "PUT")
        url: str - URL to call (supports $OWNER, $REPO, $BRANCH)
        payload: dict | str - Request body
        headers: dict[str, str] - Request headers
    """
    url = config.get("url", "")
    if not url:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="No URL specified for API call",
        )

    # Substitute variables
    substitutions = {
        "$OWNER": context.owner,
        "$REPO": context.repo,
        "$BRANCH": context.default_branch,
    }
    for var, val in substitutions.items():
        url = url.replace(var, val)

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message=f"API call to {url} requires execution context",
        evidence={"url": url, "method": config.get("method", "PUT")},
        details={"requires_execution": True},
    )


def project_update_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Update .project/project.yaml values.

    Config fields:
        updates: dict[str, Any] - Dotted path → value pairs to set
    """
    updates = config.get("updates", {})
    if not updates:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No updates specified for project_update handler",
        )

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"Project update queued: {list(updates.keys())}",
        evidence={"updates": updates},
        details={"project_updates": updates},
    )


# =============================================================================
# Registration
# =============================================================================


def register_builtin_handlers() -> None:
    """Register all built-in sieve handlers with the global registry."""
    registry = get_sieve_handler_registry()

    # Verification handlers
    registry.register("file_exists", phase="deterministic", handler_fn=file_exists_handler,
                       description="Check file existence from a list of paths")
    registry.register("exec", phase="deterministic", handler_fn=exec_handler,
                       description="Run external command, evaluate exit code / CEL expr")
    registry.register("regex", phase="pattern", handler_fn=regex_handler,
                       description="Match regex patterns in file content")
    registry.register("pattern", phase="pattern", handler_fn=regex_handler,
                       description="Alias for regex handler (match regex patterns in file content)")
    registry.register("llm_eval", phase="llm", handler_fn=llm_eval_handler,
                       description="AI evaluation with confidence threshold")
    registry.register("manual_steps", phase="manual", handler_fn=manual_steps_handler,
                       description="Human verification checklist")
    registry.register("manual", phase="manual", handler_fn=manual_steps_handler,
                       description="Alias for manual_steps handler (human verification checklist)")

    # Remediation handlers
    registry.register("file_create", phase="deterministic", handler_fn=file_create_handler,
                       description="Create a file from a template or content")
    registry.register("api_call", phase="deterministic", handler_fn=api_call_handler,
                       description="Make an HTTP API call")
    registry.register("project_update", phase="deterministic", handler_fn=project_update_handler,
                       description="Update .project/project.yaml values")
