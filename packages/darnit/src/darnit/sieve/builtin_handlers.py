"""Built-in sieve handlers for the confidence gradient pipeline.

These handlers implement the core verification logic dispatched
from TOML HandlerInvocation configs via the SieveHandlerRegistry.

Built-in verification handlers:
    - file_exists: Check file existence from a list of paths
    - exec: Run external command, evaluate exit code / CEL expr
    - gh_api: Platform API call decided by HTTP status and CEL over the response
    - regex: Match regex patterns in file content
    - llm_eval: AI evaluation with confidence threshold
    - manual_steps: Human verification checklist

Built-in remediation handlers (feature 043: they return FileChanges and
never write; the remediation executor is the single writer):
    - file_create: Create a file from a template
    - platform_setting: Change a hosting-platform setting through the platform engine
    - project_update: Update .project/project.yaml values
    - yaml_inject: Add a top-level key to YAML files that lack it
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

from darnit.core.error_class import ErrorClass

from .handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Feature 031: mcp handler constants
# =============================================================================

MCP_DEFAULT_TIMEOUT_SECONDS: float = 60.0
"""Per-call timeout for `handler = "mcp"` passes when the pass omits `timeout`.

Spec FR-002 (clarified 2026-08-16). Individual passes MAY override via
``timeout = <seconds>``. Kept as a module constant so tests can monkeypatch
it without stubbing the whole handler.
"""

# =============================================================================
# Feature 036: environmental-failure classification
# =============================================================================

# GitHub-only stderr patterns for v0 (clarify Q4). The `exec` handler sees
# only stdout/stderr/exit-code -- it has no access to response headers -- so
# classification is substring matching against `gh` CLI stderr shape. Other
# exec targets (git, curl, syft, cosign) fall through to `network`; per-target
# pattern packs are a follow-up if real audits show they are needed.
#
# Rate-limit is checked BEFORE auth: GitHub answers 403 for both rate limits
# and permission failures, and the rate-limit body is the more specific signal.
_GH_RATE_LIMIT_PATTERNS: tuple[str, ...] = (
    "api rate limit exceeded",
    "secondary rate limit",
    "abuse detection mechanism",
)

_GH_AUTH_PATTERNS: tuple[str, ...] = (
    "http 401",
    "bad credentials",
    "requires authentication",
    "gh auth login",
    "authentication token",
)


def _classify_exec_failure(stderr: str) -> ErrorClass:
    """Classify a non-zero-exit subprocess failure from its stderr.

    Only called on paths where the command did not complete as expected.
    Callers must NOT invoke this for a declared ``fail_exit_codes`` hit --
    that is a check that ran and concluded, not an environmental failure.
    """
    haystack = (stderr or "").lower()
    if any(p in haystack for p in _GH_RATE_LIMIT_PATTERNS):
        return "rate_limit"
    if any(p in haystack for p in _GH_AUTH_PATTERNS):
        return "auth"
    return "network"


def _log_environmental_failure(
    control_id: str, handler: str, error_class: ErrorClass, message: str
) -> None:
    """Emit the contract-section-7 WARN line for an environmental failure.

    WARN rather than DEBUG so a degraded audit is visible at the default log
    level -- an operator should not have to know to raise verbosity to
    discover that half their checks never reached the network.
    """
    logger.warning(
        "%s: %s handler could not complete (error_class=%s): %s",
        control_id,
        handler,
        error_class,
        message,
    )


# =============================================================================
# Verification Handlers
# =============================================================================


_FILE_DISCOVERY_PRUNE_DIRS = frozenset(
    {
        # VCS
        ".git",
        ".hg",
        ".svn",
        # Python
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "site-packages",
        # JS/TS
        "node_modules",
        # Rust / Go / Java build outputs
        "target",
        "build",
        "dist",
        "out",
        # IDE / OS
        ".idea",
        ".vscode",
        ".DS_Store",
    }
)


def _walk_depth_limited(root: str, max_depth: int):
    """Yield directories under ``root`` up to ``max_depth`` levels deep.

    Skips well-known noise directories (``.git``, ``node_modules``,
    ``__pycache__``, build outputs, etc.) so performance stays sane on
    real monorepos. ``max_depth=0`` yields only ``root`` itself; ``=1``
    yields root + its immediate subdirs; etc.
    """
    root_abs = os.path.abspath(root)
    yield root_abs, 0
    if max_depth <= 0:
        return
    for dirpath, dirnames, _files in os.walk(root_abs):
        depth = dirpath[len(root_abs) :].count(os.sep)
        # Prune in-place so os.walk skips them (matches os.walk's contract).
        # Sort so os.walk visits subdirs deterministically -- "first match
        # wins" semantics downstream depend on this. Determinism Tier 1 (#418).
        dirnames[:] = sorted(d for d in dirnames if d not in _FILE_DISCOVERY_PRUNE_DIRS)
        if depth >= max_depth:
            # Don't descend further; stop yielding deeper dirs
            dirnames.clear()
            continue
        for d in dirnames:
            yield os.path.join(dirpath, d), depth + 1


def file_exists_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Check if any file from a list of paths exists.

    Config fields:
        files: list[str] - File paths/patterns to check (any match = pass)
        use_locator: bool - If true, files are populated from locator.discover at load time
        max_depth: int - When > 0, search subdirectories up to this many levels
            deep for any non-glob pattern in ``files``. Default 0 (root only,
            backward-compatible). Glob patterns containing ``*`` are NOT
            depth-walked — they're still evaluated by ``glob.glob`` exactly as
            before. Well-known noise directories (``.git``, ``node_modules``,
            ``__pycache__``, build outputs, etc.) are pruned during the walk
            so monorepo performance stays bounded. Resolves issue #221.
    """
    files = config.get("files", [])
    if not files:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No files specified for existence check",
        )

    max_depth = int(config.get("max_depth", 0) or 0)

    for pattern in files:
        if "*" in pattern:
            import glob

            # sorted() so "first match wins" is stable across filesystems.
            # Determinism Tier 1 (#418).
            matches = sorted(glob.glob(os.path.join(context.local_path, pattern)))
            if matches:
                found = matches[0]
                rel_path = os.path.relpath(found, context.local_path)
                return HandlerResult(
                    status=HandlerResultStatus.PASS,
                    message=f"Required file found: {rel_path}",
                    confidence=1.0,
                    evidence={"found_file": found, "relative_path": rel_path, "files_checked": files},
                )
        elif max_depth > 0:
            # Depth-limited search for nested manifests (issue #221). Walks up
            # to `max_depth` levels under `context.local_path`, pruning noise
            # directories. First hit wins; we report its relative path so
            # downstream consumers (and audit reviewers) can see where it
            # actually lives.
            for dirpath, _depth in _walk_depth_limited(context.local_path, max_depth):
                candidate = os.path.join(dirpath, pattern)
                if os.path.exists(candidate):
                    rel_path = os.path.relpath(candidate, context.local_path)
                    return HandlerResult(
                        status=HandlerResultStatus.PASS,
                        message=f"Required file found: {rel_path}",
                        confidence=1.0,
                        evidence={
                            "found_file": candidate,
                            "relative_path": rel_path,
                            "files_checked": files,
                            "max_depth": max_depth,
                        },
                    )
        else:
            path = os.path.join(context.local_path, pattern)
            if os.path.exists(path):
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
        evidence={"files_checked": files, "max_depth": max_depth},
    )


def exec_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Run an external command and evaluate the result.

    Config fields:
        command: list[str] - Command to execute (supports $OWNER, $REPO, $BRANCH, $PATH)
        pass_exit_codes: list[int] - Exit codes that indicate pass (default: [0])
        fail_exit_codes: list[int] | None - Exit codes that indicate fail
        output_format: str - How to parse output ("text", "json")
        timeout: int - Timeout in seconds (default: 300)
        env: dict[str, str] - Extra environment variables
        cwd: str | None - Working directory

    Evidence shape (available in orchestrator ``expr`` as ``output.*``):
        exit_code: int
        stdout: str (truncated to 2000 chars)
        stderr: str (truncated to 500 chars)
        json: parsed JSON if output is valid JSON, else None

    As a remediation step in plan mode (feature 043, framework-design 4.4)
    the command runs only in a scratch copy, and only when the step declares
    ``effects = "working_tree"`` and ``offline = true``; see
    :func:`exec_previewable`.
    """
    if context.mode == "plan":
        return _exec_preview(config, context)

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
        message = f"Command timed out after {timeout}s: {resolved_cmd[0]}"
        _log_environmental_failure(context.control_id, "exec", "timeout", message)
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=message,
            evidence={"command": resolved_cmd, "timeout": timeout},
            error_class="timeout",
        )
    except FileNotFoundError:
        message = f"Command not found: {resolved_cmd[0]}"
        _log_environmental_failure(context.control_id, "exec", "missing_tool", message)
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=message,
            evidence={"command": resolved_cmd},
            error_class="missing_tool",
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

    # Exit code evaluation
    if proc.returncode in pass_exit_codes:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Command passed (exit code {proc.returncode})",
            confidence=1.0,
            evidence=evidence,
        )
    elif fail_exit_codes and proc.returncode in fail_exit_codes:
        # Declared failure code: the check RAN and concluded non-compliance.
        # No error_class -- this is a real finding, not an environment problem.
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"Command failed (exit code {proc.returncode})",
            confidence=1.0,
            evidence=evidence,
        )
    else:
        # Undeclared exit code: we cannot tell whether the check concluded.
        # Classify from stderr so the operator can distinguish a rate limit
        # or expired token from a genuine non-compliance signal.
        error_class = _classify_exec_failure(evidence["stderr"])
        message = f"Command exited with unexpected code {proc.returncode}"
        _log_environmental_failure(context.control_id, "exec", error_class, message)
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=message,
            evidence=evidence,
            error_class=error_class,
        )


def exec_previewable(config: dict[str, Any]) -> bool:
    """An exec remediation step can be previewed exactly in a scratch copy (framework-design 4.4)."""
    return config.get("effects") == "working_tree" and config.get("offline") is True and "cwd" not in config


def _exec_preview(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Run the command in a scratch copy of the visible working tree and return the difference as FileChanges.

    The checkout is never touched. Files the command creates that the
    checkout's ignore rules exclude are left out, as an apply never records
    them either.
    """
    import dataclasses
    import tempfile

    from darnit.remediation import git_state, working_tree

    command = [str(arg) for arg in config.get("command") or []]
    if not exec_previewable(config):
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message='Cannot be previewed exactly: exec needs effects = "working_tree" and offline = true',
            evidence={"command": command, "previewable": False},
        )
    def leaving(escaping: list[str]) -> HandlerResult:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=(
                f"Cannot be previewed exactly: symbolic link(s) {escaping} point outside the repository, "
                "so the command could write through them; it was not run"
            ),
            evidence={"command": command, "previewable": False},
        )

    try:
        paths = working_tree.visible_files(context.local_path)
        if escaping := working_tree.escaping_symlinks(context.local_path, paths):
            return leaving(escaping)
        with tempfile.TemporaryDirectory(prefix="darnit-preview-") as scratch:
            working_tree.copy_files(context.local_path, scratch, paths)
            if escaping := working_tree.escaping_symlinks(scratch, paths):
                return leaving(escaping)
            before = working_tree.digests(scratch, paths)
            ran = exec_handler(config, dataclasses.replace(context, local_path=scratch, mode="apply"))
            if ran.status != HandlerResultStatus.PASS:
                return HandlerResult(
                    status=HandlerResultStatus.ERROR,
                    message=f"Preview run did not succeed: {ran.message}",
                    evidence={"command": command, "exit_code": ran.evidence.get("exit_code")},
                    error_class=ran.error_class,
                )
            after = working_tree.all_files(scratch)
            hidden = working_tree.ignored(context.local_path, [p for p in after if p not in before])
            found = working_tree.diff(scratch, before, [p for p in after if p not in hidden])
    except (git_state.GitStateError, OSError) as e:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Cannot preview exec step: {e}",
            evidence={"command": command},
            error_class="crashed",
        )
    if not found.representable:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=(
                "Cannot be previewed exactly: the command "
                + "; ".join(
                    part
                    for part in (
                        f"deletes {found.deleted}" if found.deleted else "",
                        f"writes non-text files {found.not_text}" if found.not_text else "",
                    )
                    if part
                )
            ),
            evidence={"command": command},
        )
    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"Command would change {len(found.changes)} file(s)",
        confidence=1.0,
        evidence=_file_changes_evidence(found.changes, command=command, previewable=True),
    )


def gh_api_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Call the platform API through ``gh api`` and decide from the HTTP status.

    Feature 041. ``gh api`` exits 1 for 401, 403, 404, and 429 alike, so an
    ``exec`` step cannot tell "does not exist" from "not permitted to see".
    Only statuses the step declares in ``fail_on_status`` prove failure;
    every other non-2xx answer is a broken measurement (ERROR).

    Config fields:
        endpoint: str - API path (supports $OWNER, $REPO, $BRANCH)
        expr: str - CEL over ``response.status_code`` and ``response.body``
            on a 2xx answer: true -> PASS, false -> FAIL (no expr: PASS)
        fail_on_status: list[int] - Step field. Statuses that prove failure.
        evidence_fields: list[str] - Feature 044. Top-level ``response.body``
            keys kept in evidence; every other key is dropped (``expr``
            still sees the full response). Required on personal records.

    Evidence: ``endpoint`` (after substitution) and ``response``
    (``status_code``, ``body``). See framework-design.md section 3.8.
    """
    from darnit.core.utils import gh_api_error_class, gh_api_with_status

    endpoint = config.get("endpoint", "")
    if not endpoint:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="No endpoint specified for gh_api handler",
            error_class="evaluation",
        )
    for var, val in (("$OWNER", context.owner), ("$REPO", context.repo), ("$BRANCH", context.default_branch)):
        endpoint = endpoint.replace(var, val or "")

    body, status, error = gh_api_with_status(endpoint)
    response: dict[str, Any] = {"status_code": status, "body": body}
    evidence: dict[str, Any] = {
        "endpoint": endpoint,
        "response": {"status_code": status, "body": _evidence_body(body, config.get("evidence_fields"))},
    }

    if 200 <= status < 300:
        expr = config.get("expr")
        if not expr:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message=f"Platform API answered HTTP {status} for {endpoint}",
                confidence=1.0,
                evidence=evidence,
            )
        from .cel_evaluator import evaluate_cel

        evidence["expr"] = expr
        cel_result = evaluate_cel(expr, {"response": response})
        if not cel_result.success:
            message = f"Could not evaluate expr over the response from {endpoint}: {cel_result.error}"
            _log_environmental_failure(context.control_id, "gh_api", "evaluation", message)
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=message,
                evidence=evidence,
                error_class="evaluation",
            )
        if cel_result.value:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message=f"Platform API response for {endpoint} satisfies expr",
                confidence=1.0,
                evidence=evidence,
            )
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"Platform API response for {endpoint} does not satisfy expr",
            confidence=1.0,
            evidence=evidence,
        )

    error_class = gh_api_error_class(status, error)
    if error:
        evidence["error"] = error[:500]
    fail_on_status = config.get("fail_on_status") or []
    if status > 0 and status in fail_on_status and error_class != "rate_limit":
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"Platform API answered HTTP {status} for {endpoint}, which proves failure for this control",
            confidence=1.0,
            evidence=evidence,
        )

    detail = f"HTTP {status}" if status else (error or "no response")
    message = f"Platform API call {endpoint} could not be measured ({error_class}): {detail}"
    _log_environmental_failure(context.control_id, "gh_api", error_class, message)
    return HandlerResult(
        status=HandlerResultStatus.ERROR,
        message=message,
        evidence=evidence,
        error_class=error_class,
    )


def _evidence_body(body: Any, fields: list[str] | None) -> Any:
    """``body`` limited to the top-level ``fields`` (each item's, for a list); unchanged when ``fields`` is None."""
    if fields is None:
        return body
    if isinstance(body, dict):
        return {key: body[key] for key in fields if key in body}
    if isinstance(body, list):
        return [_evidence_body(item, fields) for item in body]
    return body


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
        fail_on_miss: bool - A miss proves failure: FAIL instead of
            INCONCLUSIVE when the patterns do not match (default: false).
            Declared on the step (feature 041); requires ``fail`` in the
            step's effective set.

    **Exclude mode** (returns evidence for CEL evaluation)::

        exclude_files: list[str] - Globs to check for presence

    Common fields:
        min_matches: int - Minimum matches per pattern per file (default: 1)
        max_depth: int - When > 0, walk subdirectories up to this many levels
            deep when resolving non-glob ``files`` entries or ``exclude_files``
            patterns that contain no wildcards. Default 0 (root only,
            backward-compatible). Glob patterns containing ``*`` are still
            evaluated by ``glob.glob`` exactly as before. Well-known noise
            directories (``.git``, ``node_modules``, ``__pycache__``, build
            outputs, etc.) are pruned during the walk so monorepo performance
            stays bounded.

    Evidence shape (available in orchestrator ``expr`` as ``output.*``):
        any_match: bool - True if any pattern matched in any file
        files_checked: int - Number of files examined
        results: list[dict] - Per-file match details
        patterns_checked: list[str] - Pattern names checked
        resolved_files: list[str] - (match mode) absolute paths of files
            that existed on disk and were scanned. A downstream
            ``llm_eval`` pass automatically falls back to this list when
            ``files_to_include`` produces no content (issue #402).
        files_found: int - (exclude mode) number of files matching globs
        found_files: list[str] - (exclude mode) matched file paths
    """
    # --- Exclude mode: glob files and return evidence (CEL does pass/fail) ---
    max_depth = int(config.get("max_depth", 0) or 0)
    exclude_files = config.get("exclude_files", [])
    if exclude_files:
        return _regex_exclude_evidence(exclude_files, context, max_depth)

    # --- Resolve file list ---
    file_paths = _resolve_regex_files(config, context, max_depth)
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
    pass_if_any = config.get("pass_if_any", True)

    return _regex_match_files(
        file_paths,
        patterns,
        min_matches,
        pass_if_any,
        fail_on_miss=bool(config.get("fail_on_miss", False)),
    )


def _regex_exclude_evidence(
    exclude_globs: list[str],
    context: HandlerContext,
    max_depth: int = 0,
) -> HandlerResult:
    """Glob for excluded files and return evidence. CEL ``expr`` decides pass/fail.

    When ``max_depth > 0``, plain filename patterns (no ``*``/``?``) are
    resolved with a depth-bounded walk instead of only checking the root.
    Glob patterns are always passed to ``glob.glob`` unchanged.
    """
    import glob as globmod

    found: list[str] = []
    for pattern in exclude_globs:
        if "*" in pattern or "?" in pattern:
            matches = globmod.glob(
                os.path.join(context.local_path, pattern),
                recursive=True,
            )
            found.extend(matches)
        elif max_depth > 0:
            # Depth-limited walk for plain filenames (no wildcards).
            # dirs.clear() at the boundary depth means directory entries AT
            # that depth are no longer descended into; only files at each
            # visited dir are matched here.
            for dirpath, _d in _walk_depth_limited(context.local_path, max_depth):
                candidate = os.path.join(dirpath, pattern)
                if os.path.exists(candidate):
                    found.append(candidate)
        else:
            candidate = os.path.join(context.local_path, pattern)
            if os.path.exists(candidate):
                found.append(candidate)

    rel_paths = [os.path.relpath(f, context.local_path) for f in found[:10]]
    evidence = {
        "exclude_globs": exclude_globs,
        "files_found": len(found),
        "found_files": rel_paths,
    }
    # Return PASS with evidence — if an expr is present the orchestrator
    # will override based on the CEL result (e.g. 'output.files_found == 0').
    # When no expr is present, finding zero files is the common success case.
    if not found:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message="No excluded files found",
            confidence=1.0,
            evidence=evidence,
        )
    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message=f"Found {len(found)} excluded file(s): {', '.join(rel_paths[:5])}",
        confidence=1.0,
        evidence=evidence,
    )


def _resolve_regex_files(
    config: dict[str, Any],
    context: HandlerContext,
    max_depth: int = 0,
) -> list[str] | None:
    """Resolve the list of absolute file paths to search.

    Returns a list of absolute paths, or None if no files could be resolved.

    When ``max_depth > 0``, plain filename entries in ``files`` (those without
    ``*`` or ``?``) are resolved with a depth-bounded walk via
    ``_walk_depth_limited`` so nested manifests like ``src/app/config.yml``
    are discovered. Glob patterns are always passed to ``glob.glob`` unchanged
    to preserve existing behavior bit-for-bit for non-opt-in controls.
    """
    import glob as globmod

    # Multi-file format: files = ["README.md", "*.yml"]
    files_list = config.get("files", [])
    if files_list:
        resolved: list[str] = []
        for file_pattern in files_list:
            if "*" in file_pattern or "?" in file_pattern:
                # Glob patterns: always use glob.glob; max_depth does not apply.
                # sorted() so downstream ordering is stable across filesystems.
                # Determinism Tier 1 (#418).
                matches = sorted(
                    globmod.glob(
                        os.path.join(context.local_path, file_pattern),
                        recursive=True,
                    )
                )
                resolved.extend(m for m in matches if os.path.isfile(m))
            elif max_depth > 0:
                # Depth-limited walk for plain filenames (no wildcards).
                # Only files are collected; dirs.clear() at the depth boundary
                # prevents descending further without skipping files at that depth.
                for dirpath, _d in _walk_depth_limited(context.local_path, max_depth):
                    candidate = os.path.join(dirpath, file_pattern)
                    if os.path.isfile(candidate):
                        resolved.append(candidate)
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
    config: dict[str, Any],
    context: HandlerContext,
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
    pass_if_any: bool,
    fail_on_miss: bool = False,
) -> HandlerResult:
    """Match patterns across files and return a result.

    A miss is INCONCLUSIVE unless ``fail_on_miss``: a keyword being absent
    rarely proves a control is unmet (feature 041, FR-004).
    """
    miss_status = HandlerResultStatus.FAIL if fail_on_miss else HandlerResultStatus.INCONCLUSIVE
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

            all_results.append(
                {
                    "file": fpath,
                    "pattern_name": pname,
                    "pattern": pregex,
                    "match_count": match_count,
                    "matched": matched,
                    "matches_preview": matches[:3],
                }
            )

            if matched:
                any_match = True

    evidence: dict[str, Any] = {
        "files_checked": len(file_paths),
        "patterns_checked": list(patterns.keys()),
        "results": all_results[:20],
        "any_match": any_match,
        # Issue #402 Option 2: paths of files that actually existed on
        # disk and were scanned. A downstream `llm_eval` pass can fall
        # back to this list when `$FOUND_FILE` is empty (e.g.
        # `pattern -> llm_eval` shapes with no `file_exists` sibling),
        # avoiding the empty-file_contents bug documented in #402. Absolute
        # paths -- llm_eval accepts either shape (see llm_eval_handler).
        "resolved_files": list(file_paths),
    }

    if pass_if_any:
        if any_match:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message=f"Pattern matched in {sum(1 for r in all_results if r['matched'])} result(s)",
                confidence=0.8,
                evidence=evidence,
            )
        return HandlerResult(
            status=miss_status,
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
        status=miss_status,
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
        files_to_include: list[str] - Files whose contents to bundle with
            the consultation. Supports:
            - literal paths (relative to repo root or absolute)
            - ``"$FOUND_FILE"`` -> `gathered_evidence["found_file"]` (from
              a preceding `file_exists` PASS)
            - ``"$RESOLVED_FILES"`` -> `gathered_evidence["resolved_files"]`
              (list from a preceding `regex`/`pattern` pass). Fans out to
              multiple candidates from a single sentinel (issue #402).
            Missing files are silently skipped. Capped at 5 file contents
            total; each capped at 10000 bytes.

            When `files_to_include` produces no file contents at all
            (empty $FOUND_FILE, missing literal paths, and no
            $RESOLVED_FILES sentinel), the handler automatically falls
            back to `gathered_evidence["resolved_files"]` so a
            `pattern -> llm_eval` shape without a `file_exists` sibling
            never ships an empty consultation (issue #402).

    Note: This handler returns INCONCLUSIVE with a consultation request in the details,
    since actual LLM invocation happens at the MCP server level.
    """
    prompt = config.get("prompt", "")
    if not prompt:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No prompt specified for LLM evaluation",
        )

    # Resolve files_to_include: read file contents for LLM context.
    # Supported sentinels:
    #   $FOUND_FILE      -> gathered_evidence["found_file"] (from file_exists)
    #   $RESOLVED_FILES  -> gathered_evidence["resolved_files"] (from regex/pattern; issue #402)
    # Literal paths are opened directly; missing files are silently skipped.
    files_to_include = config.get("files_to_include", [])
    file_contents: dict[str, str] = {}

    def _read(resolved: str) -> None:
        if not resolved or len(file_contents) >= 5:
            return
        full = os.path.join(context.local_path, resolved) if not os.path.isabs(resolved) else resolved
        try:
            with open(full, encoding="utf-8", errors="ignore") as fh:
                rel = os.path.relpath(full, context.local_path)
                file_contents[rel] = fh.read()[:10000]
        except OSError:
            pass

    for f in files_to_include[:5]:
        if f == "$FOUND_FILE":
            _read(context.gathered_evidence.get("found_file", ""))
        elif f == "$RESOLVED_FILES":
            for candidate in context.gathered_evidence.get("resolved_files", []) or []:
                _read(candidate)
        else:
            _read(f)

    # Issue #402 Option 2: automatic fallback for TOMLs that still ship
    # `files_to_include = ["$FOUND_FILE"]` and no `file_exists` sibling.
    # If nothing above resolved to real content, try `resolved_files` from
    # the preceding regex/pattern pass. Preserves single-source-of-truth
    # for the file list (the sibling pattern already declares it).
    if not file_contents:
        for candidate in context.gathered_evidence.get("resolved_files", []) or []:
            _read(candidate)

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
                "file_contents": file_contents,
            },
        },
    )


def llm_extract_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """LLM-backed EXTRACTION step (feature 025 T045).

    Unlike ``llm_eval`` which asks the LLM to make a pass/fail judgment,
    ``llm_extract`` asks the LLM to extract a VALUE from repository content
    (e.g., "propose a security contact by scanning README and docs").

    Registered with an empty ceiling (feature 041): the extracted value is a
    proposal for human confirmation, never authority for concluding a
    control. This matches the RFC's Constitution Principle IV
    (never conclude a user-judgment value from code alone).

    Config fields:
        prompt: str - Prompt describing what to extract
        files: list[str] - Glob patterns for content to include
        target_key: str - Optional context key the extraction targets (for
            downstream Collect confirmation matching)

    Returns INCONCLUSIVE with a structured `extraction_request` payload in
    ``details``; the actual LLM call is dispatched via the LLMStep protocol
    at a later phase (Slice D T047 + downstream drivers). Attaches the
    prompt + gathered content to evidence for provenance.
    """
    import glob as globmod

    prompt = config.get("prompt", "")
    if not prompt:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No prompt specified for llm_extract",
        )

    # Resolve files to include (bounded).
    globs = config.get("files", [])
    file_contents: dict[str, str] = {}
    for pattern in globs[:5]:  # cap breadth
        matches = globmod.glob(
            os.path.join(context.local_path, pattern),
            recursive=True,
        )
        for m in matches[:5]:  # cap depth per glob
            try:
                with open(m, encoding="utf-8", errors="ignore") as fh:
                    rel = os.path.relpath(m, context.local_path)
                    file_contents[rel] = fh.read()[:10000]
            except OSError:
                continue

    # Feature 026: also emit `consultation_request` so the sieve's
    # PENDING (llm_judgment) branch triggers when a driver runs with stop_on_llm=True.
    # This makes llm_extract a first-class participant in the harness's
    # LLM dispatch loop (research.md R1) -- same shape llm_eval uses.
    # `extraction_request` is kept for backward-compat with existing tests.
    consultation_payload = {
        "prompt": prompt,
        "control_id": context.control_id,
        "target_key": config.get("target_key"),
        "file_contents": file_contents,
        "gathered_evidence": context.gathered_evidence,
    }
    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message=f"LLM extraction requested for control {context.control_id}",
        evidence={
            "llm_extract_prompt": prompt,
            "llm_extract_files_gathered": sorted(file_contents.keys()),
        },
        details={
            "extraction_request": consultation_payload,
            "consultation_request": consultation_payload,
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


def _repo_path(path: str, context: HandlerContext) -> str:
    """``path`` relative to the repository, or ValueError if it is outside it."""
    from darnit.remediation.plan import normalize_repo_path

    if os.path.isabs(path):
        root = os.path.realpath(context.local_path)
        resolved = os.path.realpath(path)
        if os.path.commonpath([root, resolved]) != root:
            raise ValueError(f"path is outside the repository: {path}")
        path = os.path.relpath(resolved, root)
    return normalize_repo_path(path.replace(os.sep, "/"))


def _read_text(full_path: str) -> str | None:
    try:
        with open(full_path, encoding="utf-8", newline="") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _file_changes_evidence(changes: list[Any], **extra: Any) -> dict[str, Any]:
    return {**extra, "file_changes": [change.model_dump(mode="json") for change in changes]}


def file_create_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Plan the creation of a file from a template or content (feature 043: never writes).

    Returns the planned :class:`~darnit.remediation.plan.FileChange` in
    ``evidence["file_changes"]`` in both modes; the remediation executor
    writes it. An existing file is left alone (``action = "none"``,
    ``reason = "already_exists"``) unless ``overwrite`` is set.

    Config fields:
        path: str - Destination file path (relative to repo)
        template: str - Template name to use (looked up from framework templates)
        content: str - Direct content (used if template not specified)
        overwrite: bool - Whether to overwrite existing files (default: false)
    """
    from darnit.remediation.plan import FileChange, content_digest

    path = config.get("path", "")
    if not path:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="No path specified for file creation",
        )
    try:
        relative = _repo_path(path, context)
    except ValueError as e:
        return HandlerResult(status=HandlerResultStatus.ERROR, message=str(e), evidence={"path": path})

    full_path = os.path.join(context.local_path, relative)
    exists = os.path.lexists(full_path)

    if exists and not config.get("overwrite", False):
        change = FileChange(path=relative, action="none", reason="already_exists")
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"File already exists: {relative}",
            evidence=_file_changes_evidence([change], path=relative, action="none"),
        )

    content = config.get("content", "")
    if not content:
        # Template resolution would happen at a higher level
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"No content or template for file creation: {relative}",
            evidence={"path": relative},
        )

    if exists:
        current = _read_text(full_path)
        if current is None:
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=f"Cannot read existing file to overwrite: {relative}",
                evidence={"path": relative},
            )
        if current == content:
            change = FileChange(path=relative, action="none", reason="already_exists")
        else:
            change = FileChange(path=relative, action="modify", content=content, before_digest=content_digest(current))
    else:
        change = FileChange(path=relative, action="create", content=content)

    verb = {"create": "Create", "modify": "Overwrite", "none": "Unchanged"}[change.action]
    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"{verb} file: {relative}",
        confidence=1.0,
        evidence=_file_changes_evidence([change], path=relative, action=change.action),
    )


def platform_setting_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Plan or apply a platform requirement through the platform engine (feature 043, framework-design 4.5).

    The step declares a requirement on a target, never a payload. In plan
    mode the planned :class:`~darnit.remediation.platform.ChangeSet` is
    returned in ``evidence["change_sets"]`` and nothing is written. In apply
    mode the engine writes it only as the operator policy allows (approved
    digest under ``prompt``, never under ``manual``) and reads it back; the
    digests it wrote are in ``evidence["applied_change_sets"]`` and the
    engine's result in ``evidence["platform_results"]``.

    Config fields:
        target: str - ``branch_protection``, ``repository``, or ``vulnerability_reporting``
        require: dict - Requirement keys for the target
        branch: str - Optional; ``branch_protection`` only (default: the repository's default branch)
    """
    from darnit.config.operator.loader import OperatorConfigError
    from darnit.remediation.platform import (
        PlatformRequirement,
        PlatformSession,
        platform_repository,
        resolve_policy,
    )

    try:
        request = PlatformRequirement(
            target=config.get("target"), require=config.get("require") or {}, branch=config.get("branch")
        )
    except ValueError as e:
        return HandlerResult(status=HandlerResultStatus.ERROR, message=f"Invalid platform_setting: {e}")

    session = context.platform
    if session is None:
        repository = platform_repository(context.local_path, context.owner or None, context.repo or None)
        if repository is None:
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message="platform_setting: cannot determine which repository's settings to change",
            )
        try:
            policy = resolve_policy(context.local_path)
        except OperatorConfigError as e:
            return HandlerResult(status=HandlerResultStatus.ERROR, message=f"Remediation policy unavailable: {e}")
        session = PlatformSession(repository, policy=policy)

    if context.mode == "plan":
        planned = session.plan_for(request)
        evidence: dict[str, Any] = {"platform_plans": [planned.model_dump(mode="json")]}
        if planned.change_set is not None:
            evidence["change_sets"] = [planned.change_set.model_dump(mode="json")]
        if planned.error is not None:
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=f"Cannot plan {request.target}: {planned.error.cause}",
                evidence=evidence,
                error_class=planned.error.error_class,
            )
        if not planned.supported:
            return HandlerResult(
                status=HandlerResultStatus.INCONCLUSIVE,
                message=f"Manual: {planned.steps[0]}",
                evidence={**evidence, "steps": planned.steps},
            )
        change_set = planned.change_set
        assert change_set is not None
        message = (
            f"Change {request.target}: {len(change_set.operations)} operation(s), digest {change_set.digest}"
            if change_set.operations
            else f"{request.target} already satisfied ({change_set.satisfied_by})"
        )
        return HandlerResult(status=HandlerResultStatus.PASS, message=message, evidence=evidence)

    result = session.apply_for(request)
    evidence = {"platform_results": [result.model_dump(mode="json")]}
    if result.change_set is not None:
        evidence["change_sets"] = [result.change_set.model_dump(mode="json")]
    if result.change_set is not None and (result.kind == "applied" or result.changed):
        evidence["applied_change_sets"] = [result.change_set.digest]
    if result.steps:
        evidence["steps"] = result.steps
    if result.kind == "error":
        assert result.error is not None
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Platform change failed: {result.error.cause}",
            evidence=evidence,
            error_class=result.error.error_class,
        )
    if result.kind == "applied":
        return HandlerResult(status=HandlerResultStatus.PASS, message=f"Applied {request.target}", evidence=evidence)
    if result.kind == "unchanged" and result.reason != "stale_preview":
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"{request.target} already satisfied ({result.reason})",
            evidence=evidence,
        )
    messages = {
        "needs_approval": f"{request.target} change needs approval of its digest",
        "manual": f"{request.target} change is manual ({result.reason})",
        "unchanged": f"{request.target} settings changed since the preview; preview again (stale_preview)",
    }
    return HandlerResult(status=HandlerResultStatus.INCONCLUSIVE, message=messages[result.kind], evidence=evidence)


def project_update_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Plan an update of ``.project/`` values (feature 043: never writes).

    The changed ``.project/`` files are returned in
    ``evidence["file_changes"]``, rendered by the same round-trip writer the
    executor uses for ``project_update`` (feature 042, FR-020).

    Config fields:
        updates: dict[str, Any] - Dotted path -> value pairs to set
        create_if_missing: bool - Create ``.project/project.yaml`` if absent (default: true)
    """
    updates = config.get("updates", {})
    if not updates:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No updates specified for project_update handler",
        )

    from darnit.remediation.executor import plan_project_update

    try:
        changes = plan_project_update(context.local_path, updates, create=config.get("create_if_missing", True))
    except ValueError as e:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Cannot update .project/: {e}",
            evidence={"updates": updates},
        )

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"Project update: {list(updates.keys())}",
        evidence=_file_changes_evidence(changes, updates=updates),
        details={"project_updates": updates},
    )


def yaml_inject_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Plan the injection of a top-level key into YAML files that lack it (feature 043: never writes).

    Designed for safe, idempotent additions -- e.g., adding `permissions: {}`
    to GitHub Actions workflows. Only files missing the key get a change;
    files that already have it are reported with ``reason = "already_exists"``.

    Config fields:
        files: str - Glob pattern for YAML files (relative to repo)
        key: str - The top-level key to inject (e.g., "permissions")
        value: str - The YAML value to inject (e.g., "{}")
        insert_after: str - Insert after this key (e.g., "on"). If not found,
            inserts at the top of the file after any leading comments.
    """
    import glob as glob_mod

    from darnit.remediation.plan import FileChange, content_digest

    files_pattern = config.get("files", "")
    key = config.get("key", "")
    value = config.get("value", "{}")
    insert_after = config.get("insert_after", "on")

    if not files_pattern or not key:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="yaml_inject requires 'files' and 'key' config fields",
        )

    pattern = os.path.join(context.local_path, files_pattern)
    matched_files = sorted(glob_mod.glob(pattern))
    if not matched_files:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"No files matched pattern: {files_pattern}",
            evidence={"pattern": files_pattern},
        )

    changes: list[FileChange] = []
    modified = []
    skipped = []
    for filepath in matched_files:
        try:
            relative = _repo_path(filepath, context)
        except ValueError:
            continue
        content = _read_text(filepath)
        if content is None:
            continue

        # Skip if key already exists at the top level (not indented)
        if re.search(rf"^{re.escape(key)}\s*:", content, re.MULTILINE):
            skipped.append(relative)
            changes.append(FileChange(path=relative, action="none", reason="already_exists"))
            continue

        # Find insertion point: after the insert_after key's block
        lines = content.split("\n")
        insert_idx = 0
        in_target_block = False
        for i, line in enumerate(lines):
            if re.match(rf"^{re.escape(insert_after)}\s*:", line):
                in_target_block = True
                continue
            if in_target_block:
                # End of block: next top-level key or blank line after content
                if line and not line[0].isspace() and not line.startswith("#"):
                    insert_idx = i
                    break
                if not line.strip() and i > 0 and lines[i - 1].strip():
                    insert_idx = i + 1
                    break
        else:
            if in_target_block:
                insert_idx = len(lines)

        injection = f"\n{key}: {value}\n"
        lines.insert(insert_idx, injection.rstrip())
        changes.append(
            FileChange(path=relative, action="modify", content="\n".join(lines), before_digest=content_digest(content))
        )
        modified.append(relative)

    if not modified:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"All {len(skipped)} file(s) already have '{key}:'",
            evidence=_file_changes_evidence(changes, modified=[], skipped=skipped),
        )

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"Inject '{key}: {value}' into {len(modified)} file(s)",
        confidence=1.0,
        evidence=_file_changes_evidence(changes, modified=modified, skipped=skipped),
    )


# =============================================================================
# Feature 031: mcp handler
# =============================================================================


def mcp_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Call a tool on an allowlisted MCP server and evaluate ``expr`` over ``result.*``.

    Config fields:
        server: Name of an allowlisted ``[mcp_servers.<name>]`` block.
        tool: Name of the tool to invoke on that server.
        args: Dict of tool arguments; ``$OWNER``, ``$REPO``, ``$BRANCH``,
            and ``$PATH`` placeholders in string values are substituted
            from the ``HandlerContext``.
        expr: Optional CEL expression evaluated over ``{"result": <response>}``.
            When absent, PASS iff the tool returned successfully.
        timeout: Optional per-call timeout override in seconds. Defaults
            to :data:`MCP_DEFAULT_TIMEOUT_SECONDS`.

    Emits :class:`HandlerResult` per the failure-mode table in
    ``docs/architecture/feature-031/mcp-handler-contract.md``. Does NOT
    emit the ``dispatching_mcp`` progress line -- the orchestrator's
    dispatch site owns that so ``[N/M]`` counter state is available.
    """
    server_name = config.get("server")
    tool_name = config.get("tool")
    args = dict(config.get("args") or {})
    expr = config.get("expr")
    timeout = float(config.get("timeout", MCP_DEFAULT_TIMEOUT_SECONDS))

    if not isinstance(server_name, str) or not server_name:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="mcp handler pass missing 'server' field",
        )
    if not isinstance(tool_name, str) or not tool_name:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="mcp handler pass missing 'tool' field",
        )

    pool = context.mcp_pool
    if pool is None:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="mcp handler invoked without pool wiring (internal error)",
        )

    server_config = _lookup_mcp_server(context, server_name)
    substituted_args = _substitute_mcp_args(args, context)

    import time as _time

    from .mcp_pool import (
        McpServerBinaryMissing,
        McpServerHandshakeFailed,
        McpServerUnusable,
        McpServerVerificationFailed,
        McpToolError,
        McpToolResponseNotJson,
        McpToolTimeout,
        UnknownMcpServer,
    )

    call_start = _time.time()
    error_info: tuple[HandlerResultStatus, str] | None = None
    raw_response: dict[str, Any] | None = None
    trust_label: str

    try:
        raw_response = pool.call_tool(server_name, tool_name, substituted_args, timeout)
    except UnknownMcpServer as err:
        # A control names a server the operator never configured. Not
        # strictly environmental, but the operator fix is the same shape as
        # a missing binary: make the server available.
        error_info = (HandlerResultStatus.ERROR, str(err), "not_found")
    except McpServerBinaryMissing as err:
        # optional=true (default) -> INCONCLUSIVE; optional=false -> ERROR.
        # A missing server is a broken measurement, never FAIL (feature 041).
        optional = True
        if server_config is not None:
            optional = bool(getattr(server_config, "optional", True))
        status = HandlerResultStatus.INCONCLUSIVE if optional else HandlerResultStatus.ERROR
        message = str(err) if optional else f"Required MCP server binary not found. {err}"
        error_info = (status, message, "missing_tool")
    except McpServerVerificationFailed as err:
        # Sigstore verification failure is auth-shaped: the operator has to
        # fix a trust relationship, not a network path.
        error_info = (HandlerResultStatus.ERROR, str(err), "auth")
    except McpServerHandshakeFailed as err:
        # Contract: INCONCLUSIVE by default; ERROR when the operator marked
        # the server as required (optional=false).
        optional = True
        if server_config is not None:
            optional = bool(getattr(server_config, "optional", True))
        status = HandlerResultStatus.INCONCLUSIVE if optional else HandlerResultStatus.ERROR
        error_info = (status, str(err), "network")
    except McpServerUnusable as err:
        # Broken twice -- treat like an unusable binary: INCONCLUSIVE unless
        # the operator marked the server required (optional=false), then ERROR.
        optional = True
        if server_config is not None:
            optional = bool(getattr(server_config, "optional", True))
        status = HandlerResultStatus.INCONCLUSIVE if optional else HandlerResultStatus.ERROR
        error_info = (status, str(err), "network")
    except McpToolTimeout as err:
        error_info = (HandlerResultStatus.ERROR, str(err), "timeout")
    except McpToolError as err:
        # The tool ran but errored internally -- it did not complete cleanly.
        error_info = (HandlerResultStatus.ERROR, str(err), "crashed")
    except McpToolResponseNotJson as err:
        # The tool ran and produced output we cannot interpret.
        error_info = (HandlerResultStatus.ERROR, str(err), "crashed")
    except Exception as err:  # noqa: BLE001 - final safety net
        error_info = (
            HandlerResultStatus.ERROR,
            f"MCP handler unexpected error: {type(err).__name__}: {err}",
            "crashed",
        )

    elapsed_ms = int((_time.time() - call_start) * 1000)

    if server_config is not None:
        trust_label = (
            "sigstore-verified"
            if getattr(server_config, "trusted_publisher", None)
            else "operator-trusted-path"
        )
    else:
        trust_label = "operator-trusted-path"

    session = pool._sessions.get(server_name) if hasattr(pool, "_sessions") else None
    if session is not None:
        trust_label = session.trust_label

    if error_info is not None:
        status, message, error_class = error_info
        _log_environmental_failure(
            context.control_id, f"mcp:{server_name}.{tool_name}", error_class, message
        )
        invocation_record = {
            "server": server_name,
            "tool": tool_name,
            "args_after_substitution": substituted_args,
            "error": message,
            "trust_label": trust_label,
            "elapsed_ms": elapsed_ms,
        }
        evidence: dict[str, Any] = {"mcp_calls": [invocation_record]}
        return HandlerResult(
            status=status,
            message=message,
            evidence=evidence,
            error_class=error_class,
        )

    assert raw_response is not None
    invocation_record = {
        "server": server_name,
        "tool": tool_name,
        "args_after_substitution": substituted_args,
        "raw_response": raw_response,
        "trust_label": trust_label,
        "elapsed_ms": elapsed_ms,
    }
    evidence = {"mcp_calls": [invocation_record], "result": raw_response}

    if expr:
        cel_ok, cel_value, cel_error = _eval_cel_over_result(expr, raw_response)
        if not cel_ok:
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=f"MCP expr evaluation failed: {cel_error}",
                evidence=evidence,
            )
        if cel_value:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message=f"MCP {server_name}.{tool_name} expr matched",
                confidence=1.0,
                evidence=evidence,
            )
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"MCP {server_name}.{tool_name} expr did not match",
            evidence=evidence,
        )

    # No expr -> presence of a successful tool response is PASS.
    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"MCP {server_name}.{tool_name} returned successfully",
        confidence=1.0,
        evidence=evidence,
    )


def _lookup_mcp_server(context: HandlerContext, server_name: str) -> Any | None:
    """Return the ``McpServerConfig`` for ``server_name`` on the exec context, if any."""
    execution_context = context.execution_context
    if execution_context is None:
        return None
    servers = getattr(execution_context, "mcp_servers", None)
    if not isinstance(servers, dict):
        return None
    return servers.get(server_name)


def _substitute_mcp_args(args: dict[str, Any], context: HandlerContext) -> dict[str, Any]:
    """Substitute ``$OWNER``/``$REPO``/``$BRANCH``/``$PATH`` in string values.

    Feature 033 T005: uses :func:`darnit.core.env_subst.substitute_dollar_vars`
    with ``missing="leave"`` semantics so unknown ``$VAR`` tokens in the
    template are preserved as-is (matches the previous
    ``_apply_replacements`` behavior). Only the four context-derived
    tokens are substituted.
    """
    from darnit.core.env_subst import substitute_dollar_vars

    replacements = {
        "OWNER": context.owner or "",
        "REPO": context.repo or "",
        "BRANCH": context.default_branch or "main",
        "PATH": context.local_path or "",
    }
    out: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            out[key] = substitute_dollar_vars(value, replacements, missing="leave")
        else:
            out[key] = value
    return out


def _eval_cel_over_result(
    expr: str, raw_response: dict[str, Any]
) -> tuple[bool, Any, str | None]:
    """Evaluate ``expr`` against ``{"result": raw_response}``.

    Returns ``(ok, value, error)``. ``ok=False`` means evaluation itself
    failed (surface as ERROR); ``ok=True`` means it produced a value that
    the caller interprets as truthy/falsy.
    """
    try:
        from .cel_evaluator import evaluate_cel
    except Exception as err:  # noqa: BLE001 - CEL evaluator import surprise
        return False, None, f"CEL evaluator unavailable: {err}"

    cel_result = evaluate_cel(expr, {"result": raw_response})
    if not cel_result.success:
        return False, None, str(cel_result.error)
    return True, cel_result.value, None


# =============================================================================
# Registration
# =============================================================================


# Feature 044 (framework-design 3.0.3): the step keys each step type reads,
# beyond the common step fields, and the names its ``expr`` may use.
_POST_STEP_EXPRESSION_NAMES = frozenset({"output", "project"})
_REGEX_SETTINGS = frozenset({"file", "files", "pattern", "pass_if_any", "min_matches", "exclude_files", "max_depth"})
# docs_url is read by the remediation report, not the handler.
_MANUAL_SETTINGS = frozenset({"steps", "docs_url"})


def register_builtin_handlers() -> None:
    """Register all built-in sieve handlers with the global registry.

    Ceilings per step type (feature 041, data-model.md "HandlerCeiling"):
    presence and pattern steps prove only absence ({fail}; {pass, fail} when
    the step declares ``existence``); command, platform API, and MCP
    observations may conclude either way; model, manual, and remediation handlers conclude
    nothing.
    """
    registry = get_sieve_handler_registry()

    # Verification handlers
    registry.register(
        "file_exists",
        phase="deterministic",
        handler_fn=file_exists_handler,
        description="Check file existence from a list of paths",
        ceiling={"fail"},
        existence_ceiling={"pass", "fail"},
        settings={"files", "max_depth"},
    )
    registry.register(
        "exec",
        phase="deterministic",
        handler_fn=exec_handler,
        description="Run external command, evaluate exit code / CEL expr",
        ceiling={"pass", "fail"},
        settings={
            "command",
            "pass_exit_codes",
            "fail_exit_codes",
            "output_format",
            "timeout",
            "env",
            "cwd",
            "effects",
            "offline",
        },
        expression_names=_POST_STEP_EXPRESSION_NAMES,
    )
    # Feature 041: only declared statuses prove failure; any other non-2xx
    # answer is ERROR, so the step may conclude either way.
    registry.register(
        "gh_api",
        phase="deterministic",
        handler_fn=gh_api_handler,
        description="Call the platform API via gh; decide from HTTP status and CEL over response.*",
        ceiling={"pass", "fail"},
        settings={"endpoint", "evidence_fields"},
        expression_names={"response"},
    )
    registry.register(
        "regex",
        phase="pattern",
        handler_fn=regex_handler,
        description="Match regex patterns in file content",
        ceiling={"fail"},
        existence_ceiling={"pass", "fail"},
        settings=_REGEX_SETTINGS,
        expression_names=_POST_STEP_EXPRESSION_NAMES,
    )
    registry.register(
        "pattern",
        phase="pattern",
        handler_fn=regex_handler,
        description="Alias for regex handler (match regex patterns in file content)",
        ceiling={"fail"},
        existence_ceiling={"pass", "fail"},
        settings=_REGEX_SETTINGS,
        expression_names=_POST_STEP_EXPRESSION_NAMES,
    )
    registry.register(
        "llm_eval",
        phase="llm",
        handler_fn=llm_eval_handler,
        description="AI evaluation with confidence threshold",
        settings={"prompt", "confidence_threshold", "analysis_hints", "files_to_include"},
    )
    # RFC-0001 Stage 1 (feature 025 T045): llm_extract for value extraction.
    # Like llm_eval, it never concludes a control.
    registry.register(
        "llm_extract",
        phase="llm",
        handler_fn=llm_extract_handler,
        description="LLM-backed value extraction (suggestive; never concludes a control)",
        settings={"prompt", "files", "target_key"},
    )
    # Feature 043: manual steps have no side effects, so a manual
    # remediation stays previewable and batch-eligible.
    registry.register(
        "manual_steps",
        phase="manual",
        handler_fn=manual_steps_handler,
        description="Human verification checklist",
        supports_plan=True,
        settings=_MANUAL_SETTINGS,
    )
    registry.register(
        "manual",
        phase="manual",
        handler_fn=manual_steps_handler,
        description="Alias for manual_steps handler (human verification checklist)",
        supports_plan=True,
        settings=_MANUAL_SETTINGS,
    )
    # Feature 031: external MCP server as observation source. It may
    # conclude either way because the tool observes ground truth (a real
    # subprocess reports its state); the trust label separately surfaces
    # whether the binary was Sigstore-verified or operator-trusted-on-PATH.
    registry.register(
        "mcp",
        phase="deterministic",
        handler_fn=mcp_handler,
        description="Call a tool on an external MCP server; evaluate CEL over result.*",
        ceiling={"pass", "fail"},
        settings={"server", "tool", "args", "timeout"},
        expression_names={"result"},
    )

    # Remediation handlers. Feature 043: those registered with supports_plan
    # return FileChanges and never write; the remediation executor is the
    # single writer.
    registry.register(
        "file_create",
        phase="deterministic",
        handler_fn=file_create_handler,
        description="Create a file from a template or content",
        supports_plan=True,
        # template, project_reference, and llm_enhance are read by the
        # remediation executor.
        settings={"path", "template", "content", "overwrite", "project_reference", "llm_enhance"},
    )
    registry.register(
        "platform_setting",
        phase="deterministic",
        handler_fn=platform_setting_handler,
        description="Change a platform setting by the minimal approved change that satisfies a requirement",
        supports_plan=True,
        settings={"target", "require", "branch"},
    )
    registry.register(
        "project_update",
        phase="deterministic",
        handler_fn=project_update_handler,
        description="Update .project/project.yaml values",
        supports_plan=True,
        settings={"updates", "create_if_missing"},
    )
    registry.register(
        "yaml_inject",
        phase="deterministic",
        handler_fn=yaml_inject_handler,
        description="Inject a top-level key into YAML files that lack it",
        supports_plan=True,
        settings={"files", "key", "value", "insert_after"},
    )
