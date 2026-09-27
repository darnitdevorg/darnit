"""Tests for the built-in ``mcp`` sieve handler.

These tests spawn the in-repo mock MCP server (see
``tests/darnit/sieve/fixtures/mock_mcp_server``) as a real subprocess and
drive the handler through :class:`McpPool`. Every test constructs its own
pool and tears it down in a finalizer so the daemon-thread loop and stdio
subprocess do not leak between tests.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from darnit.config.framework_schema import McpServerConfig
from darnit.core.models import ExecutionContext
from darnit.sieve.builtin_handlers import mcp_handler
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
from darnit.sieve.mcp_pool import McpPool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pool_and_ctx(
    tmp_path: Path,
    mock_mcp_server_command: list[str],
    mcp_counter_file: Path,
    *,
    server_name: str = "mock",
    tool_env_score: str | None = None,
    trusted_publisher: str | None = None,
    trust_verifier: Any = None,
    optional: bool = True,
    extra_env: dict[str, str] | None = None,
) -> tuple[McpPool, HandlerContext]:
    """Return ``(pool, handler_ctx)`` wired to the mock server.

    The mock's counter file path and score are propagated via TOML
    ``env`` substitution so the mock's parent env stays curated.
    """
    parent_env: dict[str, str] = {
        "DARNIT_MOCK_MCP_COUNTER_FILE_SRC": str(mcp_counter_file),
    }
    if tool_env_score is not None:
        parent_env["DARNIT_MOCK_MCP_SCORE_SRC"] = tool_env_score
    for key, value in parent_env.items():
        os.environ[key] = value

    server_env: dict[str, str] = {
        "DARNIT_MOCK_MCP_COUNTER_FILE": "$DARNIT_MOCK_MCP_COUNTER_FILE_SRC",
    }
    if tool_env_score is not None:
        server_env["DARNIT_MOCK_MCP_SCORE"] = "$DARNIT_MOCK_MCP_SCORE_SRC"
    if extra_env:
        server_env.update(extra_env)

    config = McpServerConfig(
        command=mock_mcp_server_command,
        env=server_env,
        trusted_publisher=trusted_publisher,
        optional=optional,
        install_hint="Install the mock (test-only)",
    )

    pool = McpPool(
        servers={server_name: config},
        trust_verifier=trust_verifier or (lambda p, tp: (True, "test")),
    )
    execution_context = ExecutionContext(
        owner="octo",
        repo="hello",
        local_path=str(tmp_path),
        mcp_servers={server_name: config},
    )
    handler_ctx = HandlerContext(
        local_path=str(tmp_path),
        owner="octo",
        repo="hello",
        default_branch="main",
        control_id="TEST-MCP-01",
        execution_context=execution_context,
        mcp_pool=pool,
    )
    return pool, handler_ctx


@pytest.fixture()
def mock_pool_ctx(tmp_path, mock_mcp_server_command, mcp_counter_file, request):
    """Yield a pool+ctx pair, guaranteeing teardown after each test."""
    pool, ctx = _make_pool_and_ctx(
        tmp_path, mock_mcp_server_command, mcp_counter_file
    )

    def _finalize() -> None:
        pool.teardown_all()

    request.addfinalizer(_finalize)
    return pool, ctx, mcp_counter_file


def _read_counter(counter_file: Path) -> list[dict[str, Any]]:
    if not counter_file.exists():
        return []
    return [json.loads(line) for line in counter_file.read_text().splitlines() if line]


# ---------------------------------------------------------------------------
# T019: pass evaluates expr over result
# ---------------------------------------------------------------------------


def test_pass_evaluates_expr_over_result(mock_pool_ctx):
    _, ctx, _ = mock_pool_ctx
    result = mcp_handler(
        {
            "server": "mock",
            "tool": "get_score",
            "args": {"repo_url": "github.com/octo/hello"},
            "expr": "result.score >= 7.0",
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.PASS, (
        f"handler said {result.status}: {result.message} "
        f"evidence={result.evidence}"
    )
    call = result.evidence["mcp_calls"][0]
    assert call["raw_response"]["score"] == 8.5
    assert call["trust_label"] == "operator-trusted-path"


# ---------------------------------------------------------------------------
# T020: fail when expr false
# ---------------------------------------------------------------------------


def test_fail_when_expr_false(tmp_path, mock_mcp_server_command, mcp_counter_file, request):
    pool, ctx = _make_pool_and_ctx(
        tmp_path,
        mock_mcp_server_command,
        mcp_counter_file,
        tool_env_score="5.0",
    )
    request.addfinalizer(pool.teardown_all)

    result = mcp_handler(
        {
            "server": "mock",
            "tool": "get_score",
            "args": {},
            "expr": "result.score >= 7.0",
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.FAIL
    assert result.evidence["mcp_calls"][0]["raw_response"]["score"] == 5.0


# ---------------------------------------------------------------------------
# T021: arg substitution against context
# ---------------------------------------------------------------------------


def test_arg_substitution(mock_pool_ctx):
    _, ctx, _ = mock_pool_ctx
    result = mcp_handler(
        {
            "server": "mock",
            "tool": "echo",
            "args": {"text": "repo=$OWNER/$REPO branch=$BRANCH"},
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.PASS
    call = result.evidence["mcp_calls"][0]
    assert call["args_after_substitution"]["text"] == "repo=octo/hello branch=main"
    # Mock echoed the substituted value
    assert call["raw_response"]["text"] == "repo=octo/hello branch=main"


# ---------------------------------------------------------------------------
# T022: progress log line emitted by the orchestrator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T028: env curation drops credentials
# ---------------------------------------------------------------------------


def test_env_curation_drops_credentials(monkeypatch):
    for k, v in {
        "AWS_SECRET_ACCESS_KEY": "shhh",
        "GITHUB_TOKEN": "ghp_x",
        "HOME": "/h",
        "PATH": "/usr/bin",
        "XDG_CONFIG_HOME": "/xdg",
        "LC_ALL": "en_US.UTF-8",
    }.items():
        monkeypatch.setenv(k, v)
    # Clear anything else that might already be set from the parent shell.
    for leaky in ("AWS_ACCESS_KEY_ID",):
        monkeypatch.delenv(leaky, raising=False)

    env = McpPool.build_child_env(McpServerConfig(command=["true"], env={}))
    assert env["HOME"] == "/h"
    assert env["PATH"] == "/usr/bin"
    assert env["XDG_CONFIG_HOME"] == "/xdg"
    assert env["LC_ALL"] == "en_US.UTF-8"
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "GITHUB_TOKEN" not in env


# ---------------------------------------------------------------------------
# T029: TOML env block substitutes from parent shell
# ---------------------------------------------------------------------------


def test_env_toml_block_substitutes_from_parent(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_realtoken")
    env = McpPool.build_child_env(
        McpServerConfig(
            command=["true"],
            env={"GITHUB_TOKEN": "$GH_TOKEN", "STATIC_VAL": "literal"},
        )
    )
    assert env["GITHUB_TOKEN"] == "ghp_realtoken"
    assert env["STATIC_VAL"] == "literal"


# ---------------------------------------------------------------------------
# T030: unset variable substitutes as empty string
# ---------------------------------------------------------------------------


def test_env_unset_var_substitutes_empty(monkeypatch):
    monkeypatch.delenv("DARNIT_TEST_UNSET_VAR", raising=False)
    env = McpPool.build_child_env(
        McpServerConfig(command=["true"], env={"X": "$DARNIT_TEST_UNSET_VAR"})
    )
    assert env["X"] == ""


# ---------------------------------------------------------------------------
# T031: unknown server -> ERROR without any spawn
# ---------------------------------------------------------------------------


def test_unknown_server_produces_error(tmp_path, mcp_counter_file):
    execution_context = ExecutionContext(
        owner="octo",
        repo="hello",
        local_path=str(tmp_path),
        mcp_servers={},  # no `rogue` registered
    )
    pool = McpPool(servers={})
    ctx = HandlerContext(
        local_path=str(tmp_path),
        control_id="TEST-01",
        execution_context=execution_context,
        mcp_pool=pool,
    )
    result = mcp_handler(
        {"server": "rogue", "tool": "anything", "args": {}}, ctx
    )
    assert result.status == HandlerResultStatus.ERROR
    assert "unknown MCP server: rogue" in result.message
    assert not mcp_counter_file.exists() or _read_counter(mcp_counter_file) == []


# ---------------------------------------------------------------------------
# T036: trust verification failure -> ERROR + no evidence tool call
# ---------------------------------------------------------------------------


def test_verification_failure_produces_error_no_evidence(
    tmp_path, mock_mcp_server_command, mcp_counter_file, request
):
    def _fail_verify(_binary, _tp):
        return False, "TEST verification failed"

    pool, ctx = _make_pool_and_ctx(
        tmp_path,
        mock_mcp_server_command,
        mcp_counter_file,
        server_name="pinned",
        trusted_publisher="https://github.com/example/example",
        trust_verifier=_fail_verify,
    )
    request.addfinalizer(pool.teardown_all)

    result = mcp_handler(
        {
            "server": "pinned",
            "tool": "get_score",
            "args": {},
            "expr": "result.score >= 7.0",
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.ERROR
    assert "Sigstore verification failed" in result.message
    # No successful tool call in evidence
    call = result.evidence["mcp_calls"][0]
    assert "raw_response" not in call
    assert "error" in call
    # Counter file records ZERO tool_call events
    events = _read_counter(mcp_counter_file)
    assert not any(e.get("kind") == "tool_call" for e in events)


# ---------------------------------------------------------------------------
# T037: trust verification success -> PASS + trust_label = sigstore-verified
# ---------------------------------------------------------------------------


def test_verification_success_trust_label(
    tmp_path, mock_mcp_server_command, mcp_counter_file, request
):
    def _ok_verify(_binary, _tp):
        return True, "verified against https://github.com/example/example"

    pool, ctx = _make_pool_and_ctx(
        tmp_path,
        mock_mcp_server_command,
        mcp_counter_file,
        server_name="pinned",
        trusted_publisher="https://github.com/example/example",
        trust_verifier=_ok_verify,
    )
    request.addfinalizer(pool.teardown_all)

    result = mcp_handler(
        {
            "server": "pinned",
            "tool": "get_score",
            "args": {},
            "expr": "result.score >= 7.0",
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.PASS
    assert result.evidence["mcp_calls"][0]["trust_label"] == "sigstore-verified"


# ---------------------------------------------------------------------------
# T038: trusted_publisher absent -> label = operator-trusted-path, verify NOT called
# ---------------------------------------------------------------------------


def test_trusted_publisher_absent_label_is_operator_trusted_path(
    tmp_path, mock_mcp_server_command, mcp_counter_file, request
):
    verify_called = False

    def _spy_verify(_binary, _tp):
        nonlocal verify_called
        verify_called = True
        return True, "should not run"

    pool, ctx = _make_pool_and_ctx(
        tmp_path,
        mock_mcp_server_command,
        mcp_counter_file,
        trusted_publisher=None,  # no verification
        trust_verifier=_spy_verify,
    )
    request.addfinalizer(pool.teardown_all)

    result = mcp_handler(
        {
            "server": "mock",
            "tool": "get_score",
            "args": {},
            "expr": "result.score >= 7.0",
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.PASS
    assert result.evidence["mcp_calls"][0]["trust_label"] == "operator-trusted-path"
    assert verify_called is False


# ---------------------------------------------------------------------------
# T039: binary absent + optional=true -> INCONCLUSIVE with install hint
# ---------------------------------------------------------------------------


def test_binary_absent_optional_true_inconclusive(tmp_path, mcp_counter_file):
    absent_cmd = ["definitelynotarealthing_xyzq_abc"]
    server_config = McpServerConfig(
        command=absent_cmd,
        install_hint="Install with: brew install thing",
        optional=True,
    )
    pool = McpPool(servers={"missing": server_config})
    execution_context = ExecutionContext(
        owner="octo",
        repo="hello",
        local_path=str(tmp_path),
        mcp_servers={"missing": server_config},
    )
    ctx = HandlerContext(
        local_path=str(tmp_path),
        control_id="TEST-01",
        execution_context=execution_context,
        mcp_pool=pool,
    )
    result = mcp_handler(
        {"server": "missing", "tool": "echo", "args": {}}, ctx
    )
    assert result.status == HandlerResultStatus.INCONCLUSIVE
    assert "MCP server binary not found: definitelynotarealthing_xyzq_abc" in result.message
    assert "Install with: brew install thing" in result.message
    assert not mcp_counter_file.exists() or _read_counter(mcp_counter_file) == []


# ---------------------------------------------------------------------------
# T040: binary absent + optional=false -> ERROR with same shape (feature 041:
# a missing required server is a broken measurement, never FAIL)
# ---------------------------------------------------------------------------


def test_binary_absent_optional_false_errors(tmp_path, mcp_counter_file):
    absent_cmd = ["definitelynotarealthing_xyzq_abc"]
    server_config = McpServerConfig(
        command=absent_cmd,
        install_hint="Install with: brew install thing",
        optional=False,
    )
    pool = McpPool(servers={"missing": server_config})
    execution_context = ExecutionContext(
        owner="octo",
        repo="hello",
        local_path=str(tmp_path),
        mcp_servers={"missing": server_config},
    )
    ctx = HandlerContext(
        local_path=str(tmp_path),
        control_id="TEST-01",
        execution_context=execution_context,
        mcp_pool=pool,
    )
    result = mcp_handler(
        {"server": "missing", "tool": "echo", "args": {}}, ctx
    )
    assert result.status == HandlerResultStatus.ERROR
    assert result.error_class == "missing_tool"
    assert "MCP server binary not found: definitelynotarealthing_xyzq_abc" in result.message


# ---------------------------------------------------------------------------
# T041: tool timeout -> ERROR + session broken + respawn on next call
# ---------------------------------------------------------------------------


def test_tool_timeout_produces_error_marks_broken(
    tmp_path, mock_mcp_server_command, mcp_counter_file, request
):
    pool, ctx = _make_pool_and_ctx(
        tmp_path, mock_mcp_server_command, mcp_counter_file
    )
    request.addfinalizer(pool.teardown_all)

    result = mcp_handler(
        {
            "server": "mock",
            "tool": "sleep_forever",
            "args": {},
            "timeout": 1,
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.ERROR
    assert "timed out" in result.message.lower() or "exceeded" in result.message.lower()

    # Second call to the same server should succeed because the pool
    # respawns after the broken session.
    result2 = mcp_handler(
        {
            "server": "mock",
            "tool": "get_score",
            "args": {},
            "expr": "result.score >= 7.0",
        },
        ctx,
    )
    assert result2.status == HandlerResultStatus.PASS, (
        f"expected respawn to succeed, got {result2.status}: {result2.message}"
    )

    # Verify the mock's counter file shows exactly TWO spawn events
    # (initial + one respawn). Note: SC-002's spawn-once property applies
    # only to the no-crash path (see test_teardown_on_success_path).
    events = _read_counter(mcp_counter_file)
    spawn_events = [e for e in events if e.get("kind") == "spawn"]
    assert len(spawn_events) == 2, (
        f"expected 2 spawn events (initial + respawn), got {len(spawn_events)}"
    )


# ---------------------------------------------------------------------------
# T042: tool-side isError -> ERROR + session NOT broken
# ---------------------------------------------------------------------------


def test_tool_side_error_produces_error_no_broken(
    tmp_path, mock_mcp_server_command, mcp_counter_file, request
):
    pool, ctx = _make_pool_and_ctx(
        tmp_path, mock_mcp_server_command, mcp_counter_file
    )
    request.addfinalizer(pool.teardown_all)

    result = mcp_handler(
        {
            "server": "mock",
            "tool": "raise_error",
            "args": {"reason": "test"},
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.ERROR
    assert "MCP tool error" in result.message

    # Same server, different tool: should NOT respawn (session not marked broken)
    result2 = mcp_handler(
        {"server": "mock", "tool": "echo", "args": {"text": "hi"}},
        ctx,
    )
    assert result2.status == HandlerResultStatus.PASS
    events = _read_counter(mcp_counter_file)
    spawn_events = [e for e in events if e.get("kind") == "spawn"]
    assert len(spawn_events) == 1, (
        f"expected exactly ONE spawn (tool-side error is not session failure), got {len(spawn_events)}"
    )


# ---------------------------------------------------------------------------
# T043: handshake failure (binary exits immediately) -> INCONCLUSIVE
# ---------------------------------------------------------------------------


def test_handshake_failure_produces_inconclusive_no_evidence(tmp_path, mcp_counter_file):
    import sys as _sys

    server_config = McpServerConfig(
        command=[_sys.executable, "-c", "import sys; sys.exit(0)"],
        optional=True,
    )
    pool = McpPool(servers={"deadbin": server_config})
    execution_context = ExecutionContext(
        owner="octo",
        repo="hello",
        local_path=str(tmp_path),
        mcp_servers={"deadbin": server_config},
    )
    ctx = HandlerContext(
        local_path=str(tmp_path),
        control_id="TEST-01",
        execution_context=execution_context,
        mcp_pool=pool,
    )
    try:
        result = mcp_handler(
            {"server": "deadbin", "tool": "anything", "args": {}}, ctx
        )
    finally:
        pool.teardown_all()

    assert result.status == HandlerResultStatus.INCONCLUSIVE, (
        f"expected INCONCLUSIVE, got {result.status}: {result.message}"
    )
    assert "handshake failed" in result.message.lower() or "handshake" in result.message.lower()
    call = result.evidence["mcp_calls"][0]
    assert "raw_response" not in call


# ---------------------------------------------------------------------------
# Regression: captured sys.stderr must not break subprocess spawn
# ---------------------------------------------------------------------------


def test_pool_survives_captured_sys_stderr(
    tmp_path, mock_mcp_server_command, mcp_counter_file, request, monkeypatch
):
    """PR #380 review finding 3.

    ``mcp.client.stdio.stdio_client`` binds its ``errlog=sys.stderr``
    default at module-import time. Under pytest, if the mcp module was
    first imported while a capsys-active test held ``sys.stderr``
    replaced with a non-fd stream, every subsequent spawn raised
    ``io.UnsupportedOperation: fileno``. Simulate that state directly
    (a stderr stream without a working ``fileno()``) and confirm the
    pool still spawns cleanly.
    """
    import io as _io

    class _NoFilenoStream(_io.StringIO):
        def fileno(self):
            raise _io.UnsupportedOperation("fileno")

    monkeypatch.setattr("sys.stderr", _NoFilenoStream())

    pool, ctx = _make_pool_and_ctx(
        tmp_path, mock_mcp_server_command, mcp_counter_file
    )
    request.addfinalizer(pool.teardown_all)

    result = mcp_handler(
        {
            "server": "mock",
            "tool": "get_score",
            "args": {},
            "expr": "result.score >= 7.0",
        },
        ctx,
    )
    assert result.status == HandlerResultStatus.PASS, (
        f"handler said {result.status}: {result.message}"
    )


def test_progress_log_line_emitted(
    tmp_path, mock_mcp_server_command, mcp_counter_file, caplog, request
):
    """The orchestrator emits `[N/M] <control_id> dispatching_mcp <server>.<tool>`."""
    import logging

    from darnit.config.framework_schema import HandlerInvocation
    from darnit.sieve.models import CheckContext, ControlSpec
    from darnit.sieve.orchestrator import SieveOrchestrator

    parent_env = {"DARNIT_MOCK_MCP_COUNTER_FILE_SRC": str(mcp_counter_file)}
    for key, value in parent_env.items():
        os.environ[key] = value

    server_config = McpServerConfig(
        command=mock_mcp_server_command,
        env={"DARNIT_MOCK_MCP_COUNTER_FILE": "$DARNIT_MOCK_MCP_COUNTER_FILE_SRC"},
    )
    invocation = HandlerInvocation(
        handler="mcp",
        server="mock",
        tool="get_score",
        args={"repo_url": "github.com/$OWNER/$REPO"},
        expr="result.score >= 7.0",
    )
    control_spec = ControlSpec(
        control_id="OSPS-VM-01.01",
        level=1,
        domain=None,
        name="MockScore",
        description="",
        metadata={"handler_invocations": [invocation]},
    )

    execution_context = ExecutionContext(
        owner="octo",
        repo="hello",
        local_path=str(tmp_path),
        mcp_servers={"mock": server_config},
    )
    check_context = CheckContext(
        owner="octo",
        repo="hello",
        local_path=str(tmp_path),
        default_branch="main",
        control_id="OSPS-VM-01.01",
        execution_context=execution_context,
    )

    orchestrator = SieveOrchestrator(stop_on_llm=False)

    def _finalize() -> None:
        if orchestrator._mcp_pool is not None:
            orchestrator._mcp_pool.teardown_all()
            orchestrator._mcp_pool = None

    request.addfinalizer(_finalize)

    with caplog.at_level(logging.INFO, logger="darnit.harness"):
        result = orchestrator.verify(control_spec, check_context)

    assert result.status == "PASS", f"expected PASS got {result.status}: {result.message}"
    matched = [
        rec
        for rec in caplog.records
        if rec.name == "darnit.harness"
        and re.match(r"\[\d+/\d+\] \S+ dispatching_mcp mock\.get_score", rec.getMessage())
    ]
    assert len(matched) == 1, f"expected 1 dispatching_mcp line, got {len(matched)}"
