"""Per-audit MCP client-session pool.

Spawn-lazy: no session is created until a control's mcp-handler pass actually
references its server. Teardown-in-finally: verify_batch guarantees every
session is closed before returning, even on exceptions.

Sync-over-async bridge: MCP's stdio client requires a live event loop for
the subprocess's read/write pumps. Darnit's sieve orchestrator is
synchronous, so the pool owns one background asyncio loop running in a
daemon thread for the pool's whole lifetime. Every sync ``call_tool`` /
``acquire`` / ``teardown_all`` call submits a coroutine via
``run_coroutine_threadsafe`` and blocks on the future.

Public surface used by the handler: :class:`McpPool.call_tool`. The pool
owns the allowlist (dict of server name -> McpServerConfig) and the session
cache. The exception hierarchy at the bottom of this module names every
distinct failure mode the handler maps to a HandlerResult status (see the
failure-mode table in ``contracts/mcp-handler-contract.md``).

The sandbox follow-up (issue #375) will extend :func:`McpPool._spawn`'s
pre-spawn hooks (env curation, Sigstore verification) without touching the
pool's session cache or the handler's public shape.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import shutil
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from darnit.config.framework_schema import McpServerConfig  # noqa: F401

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MCP_ENV_SAFE_KEYS: tuple[str, ...] = ("PATH", "HOME", "LANG", "SSL_CERT_FILE")
MCP_ENV_SAFE_PREFIXES: tuple[str, ...] = ("LC_", "XDG_")
MCP_ENV_SAFE_KEYS_WINDOWS: tuple[str, ...] = ("SYSTEMROOT", "SYSTEMDRIVE")
MCP_PROGRESS_VERB: str = "dispatching_mcp"


# =============================================================================
# Exception hierarchy
#
# Each concrete exception names the failure mode the handler maps to a
# HandlerResult status. Kept flat and specific so a caller can distinguish
# "binary missing" (INCONCLUSIVE/FAIL depending on `optional`) from
# "handshake failed" (INCONCLUSIVE always) without string-matching messages.
# =============================================================================


class McpPoolError(Exception):
    """Base class for every pool-side failure."""


class McpServerBinaryMissing(McpPoolError):
    """The allowlisted `command[0]` is not resolvable on PATH."""


class McpServerVerificationFailed(McpPoolError):
    """`trusted_publisher` was set and Sigstore verification did not pass."""


class McpServerHandshakeFailed(McpPoolError):
    """The MCP `initialize` handshake failed or the child exited early."""


class McpServerUnusable(McpPoolError):
    """The session was broken and a single respawn also failed."""


class UnknownMcpServer(McpPoolError):
    """No allowlist entry exists for the referenced server name."""


class McpToolTimeout(McpPoolError):
    """`session.call_tool` did not return within the configured timeout."""


class McpToolError(McpPoolError):
    """The MCP tool explicitly returned isError=True with a message."""


class McpToolResponseNotJson(McpPoolError):
    """Tool response content was non-text or not JSON-parseable."""


# =============================================================================
# PooledSession
# =============================================================================


@dataclass
class PooledSession:
    """One live MCP client session, cached in the pool by server name.

    Lifecycle: FRESH -> USED -> TEARDOWN. Any call that raises a
    session-level error (crash, timeout, handshake death) transitions the
    session to BROKEN; the next reference respawns exactly once. A double-
    broken session raises :class:`McpServerUnusable` on further references.
    Tool-side errors (`isError=True`) are NOT session-level failures and do
    not mark the session broken.
    """

    server_name: str
    config: Any  # McpServerConfig -- typed as Any to avoid the import cycle
    session: Any | None  # mcp.ClientSession, or None while broken
    trust_label: Literal["sigstore-verified", "operator-trusted-path"]
    spawn_ts: datetime
    broken: bool = False
    # Owner task: holds the stdio_client + ClientSession contexts open on
    # the pool's bridge loop. Closes on _shutdown_event.set().
    _owner_task: Any = None
    _shutdown_event: Any = None

    def mark_broken(self) -> None:
        self.broken = True

    def is_healthy(self) -> bool:
        return not self.broken and self.session is not None


# =============================================================================
# _LoopBridge -- sync-over-async
# =============================================================================


class _LoopBridge:
    """One long-lived asyncio loop running in a daemon thread.

    The pool submits coroutines here so stdio-client subprocesses stay
    alive across successive sync ``call_tool`` invocations. Kept private
    to this module; not part of the reader contract.

    Thread-ownership contract: the loop MUST be constructed inside the
    runner thread, not the calling thread. On POSIX, asyncio's child
    watcher (used for subprocess pipe management) binds to the thread
    that CREATED the loop. If the creating thread had an existing loop
    with an incompatible watcher (a common state after other tests
    exercise asyncio in the calling thread), stdio-subprocess spawn
    fails inside anyio with the tell-tale ``fileno`` error. Creating
    the loop in the runner side-steps that entirely.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._runner,
            name="darnit-mcp-pool-loop",
            daemon=True,
        )
        self._thread.start()
        # Block until _runner has set self._loop AND started run_forever.
        self._ready.wait()

    def _runner(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001 - shutdown best-effort
                pass

    def run(self, coro: Any, timeout: float | None = None) -> Any:
        assert self._loop is not None, "bridge not ready"
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as err:
            future.cancel()
            raise McpToolTimeout(f"MCP call exceeded {timeout:g}s") from err

    def close(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=5)


# =============================================================================
# McpPool
# =============================================================================


class McpPool:
    """Per-audit-run pool of MCP client sessions keyed by server name.

    Owns the allowlist (a dict of ``server_name -> McpServerConfig``) and
    the cache of live sessions. Constructed lazily by the orchestrator on
    first reference to an mcp-handler pass; torn down in the orchestrator's
    ``verify_batch`` finally block.
    """

    def __init__(
        self,
        servers: dict[str, Any] | None = None,
        trust_verifier: Any = None,
    ) -> None:
        """Initialise the pool.

        Args:
            servers: Allowlist mapping ``server_name -> McpServerConfig``.
                A missing entry at ``call_tool`` time raises
                :class:`UnknownMcpServer`.
            trust_verifier: Callable ``(binary_path, trusted_publisher)
                -> (ok: bool, reason: str)`` used when a server's config
                declares ``trusted_publisher``. Defaults to
                :func:`darnit.sieve.mcp_trust.verify` -- injected here so
                tests can substitute a monkeypatched verifier without
                reaching into module globals.
        """
        self._servers: dict[str, Any] = dict(servers or {})
        self._sessions: dict[str, PooledSession] = {}
        self._bridge: _LoopBridge | None = None
        if trust_verifier is None:
            from darnit.sieve import mcp_trust

            trust_verifier = mcp_trust.verify
        self._verify = trust_verifier

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call_tool(
        self,
        server_name: str,
        tool: str,
        args: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Call ``tool`` on ``server_name`` and return the parsed response.

        Raises the specific pool exception on any failure. The mcp handler
        is responsible for mapping each exception to a HandlerResult status
        per the failure-mode table.
        """
        config = self._servers.get(server_name)
        if config is None:
            raise UnknownMcpServer(f"unknown MCP server: {server_name}")

        session = self.acquire(server_name, config)
        assert session.session is not None  # acquire returns healthy session

        try:
            result = self._bridge_run(
                self._call_tool_async(session.session, tool, args, timeout),
                timeout=timeout + 5,
            )
        except McpToolTimeout:
            session.mark_broken()
            raise
        except McpPoolError:
            raise
        except Exception as err:  # noqa: BLE001 - session-level surprise
            session.mark_broken()
            raise McpServerHandshakeFailed(
                f"MCP session error during {server_name}.{tool}: {err}"
            ) from err

        # mcp.CallToolResult carries `.isError` and `.content` (list of
        # content parts). Success responses are expected to carry one text
        # part containing JSON.
        is_error = bool(getattr(result, "isError", False))
        content = getattr(result, "content", None) or []
        if is_error:
            message = _first_text(content) or "tool reported isError without message"
            raise McpToolError(f"MCP tool error: {message}")

        text = _first_text(content)
        if text is None:
            raise McpToolResponseNotJson(
                f"MCP tool response was non-text content on {server_name}.{tool}"
            )
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as err:
            raise McpToolResponseNotJson(
                f"MCP tool response not JSON-parseable on {server_name}.{tool}: {err}"
            ) from err
        if not isinstance(parsed, dict):
            raise McpToolResponseNotJson(
                f"MCP tool response was not a JSON object on {server_name}.{tool}"
            )
        return parsed

    def acquire(self, server_name: str, config: Any) -> PooledSession:
        """Return a healthy :class:`PooledSession`, respawning at most once."""
        session = self._sessions.get(server_name)
        if session is not None and session.is_healthy():
            return session

        if session is not None and session.broken:
            self._teardown_one(session)
            self._sessions.pop(server_name, None)
            fresh = self._spawn(server_name, config)
            if not fresh.is_healthy():
                raise McpServerUnusable(
                    f"MCP server session broken and respawn failed for {server_name}"
                )
            return fresh

        return self._spawn(server_name, config)

    def teardown_all(self) -> None:
        """Close every cached session, best-effort, then clear the cache.

        Also stops the background asyncio loop -- the pool is single-use;
        callers who need a fresh pool construct a new one.
        """
        for session in list(self._sessions.values()):
            self._teardown_one(session)
        self._sessions.clear()
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None

    # ------------------------------------------------------------------
    # Env curation
    # ------------------------------------------------------------------

    @staticmethod
    def build_child_env(server_config: Any) -> dict[str, str]:
        """Compose the child process env: safe-set + operator TOML block.

        The safe-set is a small allowlist (PATH, HOME, LANG, LC_*, XDG_*,
        SSL_CERT_FILE). ``$VAR`` placeholders in the operator's TOML
        ``env`` block are substituted from the parent shell at spawn time;
        unset variables substitute as empty string (matching the ``exec``
        handler behavior).
        """
        parent = dict(os.environ)
        env: dict[str, str] = {}
        allow_keys = set(MCP_ENV_SAFE_KEYS)
        if sys.platform == "win32":
            allow_keys.update(MCP_ENV_SAFE_KEYS_WINDOWS)
        for key, value in parent.items():
            if key in allow_keys or any(key.startswith(p) for p in MCP_ENV_SAFE_PREFIXES):
                env[key] = value

        for key, template in (getattr(server_config, "env", {}) or {}).items():
            env[key] = _substitute_dollar_vars(str(template), parent)
        return env

    # ------------------------------------------------------------------
    # Spawn / teardown internals
    # ------------------------------------------------------------------

    def _spawn(self, server_name: str, config: Any) -> PooledSession:
        command = list(getattr(config, "command", []) or [])
        if not command:
            raise McpServerHandshakeFailed(
                f"MCP server '{server_name}' has empty command"
            )
        program = command[0]
        binary_path: Path
        if os.path.isabs(program):
            binary_path = Path(program)
            if not binary_path.exists():
                raise McpServerBinaryMissing(_absent_binary_message(program, config))
        else:
            resolved = shutil.which(program)
            if resolved is None:
                raise McpServerBinaryMissing(_absent_binary_message(program, config))
            binary_path = Path(resolved)

        trust_label: Literal["sigstore-verified", "operator-trusted-path"]
        trusted_publisher = getattr(config, "trusted_publisher", None)
        if trusted_publisher:
            ok, reason = self._verify(binary_path, trusted_publisher)
            if not ok:
                raise McpServerVerificationFailed(
                    f"Sigstore verification failed for {program}: {reason}"
                )
            trust_label = "sigstore-verified"
        else:
            trust_label = "operator-trusted-path"

        env = self.build_child_env(config)

        # Close a PATH TOCTOU: exec the resolved absolute path we
        # verified above, not the caller's relative command name. If we
        # handed StdioServerParameters `command[0]` unchanged, the OS
        # would re-resolve PATH at exec time and could pick up a
        # different binary than the one we hashed / Sigstore-verified.
        exec_command = [str(binary_path), *command[1:]]

        # Ensure the bridge loop is running before we schedule the owner
        # task on it.
        if self._bridge is None:
            self._bridge = _LoopBridge()
        loop = self._bridge._loop

        ready_future: concurrent.futures.Future[Any] = concurrent.futures.Future()

        async def _run_session_owner() -> None:
            shutdown = asyncio.Event()
            try:
                session, _stack = await _open_session_async(exec_command, env)
            except Exception as err:  # noqa: BLE001 -- surface to caller
                ready_future.set_exception(err)
                return
            ready_future.set_result((session, shutdown))
            try:
                await shutdown.wait()
            finally:
                # _open_session_async's AsyncExitStack was returned to us
                # but keeping the with-scope in this task ensures cancel
                # scopes stay bound to this same task.
                await _stack.aclose()

        owner_task_future = asyncio.run_coroutine_threadsafe(
            _run_session_owner(), loop
        )

        try:
            session, shutdown = ready_future.result(timeout=30)
        except concurrent.futures.TimeoutError as err:
            owner_task_future.cancel()
            raise McpServerHandshakeFailed(
                f"MCP handshake for {server_name} exceeded 30s"
            ) from err
        except Exception as err:  # noqa: BLE001 -- handshake surprises
            owner_task_future.cancel()
            raise McpServerHandshakeFailed(
                f"MCP handshake failed for {server_name}: {err}"
            ) from err

        pooled = PooledSession(
            server_name=server_name,
            config=config,
            session=session,
            trust_label=trust_label,
            spawn_ts=datetime.now(),
            _owner_task=owner_task_future,
            _shutdown_event=shutdown,
        )
        self._sessions[server_name] = pooled
        return pooled

    def _teardown_one(self, session: PooledSession) -> None:
        shutdown = session._shutdown_event
        owner = session._owner_task
        if shutdown is None or owner is None:
            return
        loop = self._bridge._loop if self._bridge is not None else None
        try:
            if loop is not None:
                loop.call_soon_threadsafe(shutdown.set)
            # Wait for the owner task to finish (which closes the async
            # exit stack in the task that opened it, avoiding anyio's
            # "different-task" cancel-scope error).
            try:
                owner.result(timeout=5)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "MCP session teardown for %s did not complete within 5s",
                    session.server_name,
                )
        except Exception as err:  # noqa: BLE001 - best-effort close
            logger.warning(
                "MCP session teardown for %s raised %s: %s",
                session.server_name,
                type(err).__name__,
                err,
            )
        finally:
            session._shutdown_event = None
            session._owner_task = None
            session.session = None

    # ------------------------------------------------------------------
    # Sync-over-async bridge access (private)
    # ------------------------------------------------------------------

    def _bridge_run(self, coro: Any, timeout: float | None = None) -> Any:
        if self._bridge is None:
            self._bridge = _LoopBridge()
        return self._bridge.run(coro, timeout=timeout)

    @staticmethod
    async def _call_tool_async(
        session: Any, tool: str, args: dict[str, Any], timeout: float
    ) -> Any:
        return await asyncio.wait_for(session.call_tool(tool, args), timeout=timeout)


# =============================================================================
# Module helpers
# =============================================================================


def _absent_binary_message(program: str, config: Any) -> str:
    """Build the operator-facing message for a missing MCP server binary."""
    install_hint = getattr(config, "install_hint", "") or ""
    message = f"MCP server binary not found: {program}"
    if install_hint:
        message = f"{message}. {install_hint}"
    return message


def _substitute_dollar_vars(template: str, env: dict[str, str]) -> str:
    """Thin shim over :func:`darnit.core.env_subst.substitute_dollar_vars`.

    Feature 033 T006 migrated this call site from the duplicated inline
    implementation to the shared helper. Kept as a shim so the internal
    ``mcp_pool`` call sites remain unchanged; the shim can be removed
    when the module is next touched.
    """
    from darnit.core.env_subst import substitute_dollar_vars

    return substitute_dollar_vars(template, env, missing="empty")


def _first_text(parts: list[Any]) -> str | None:
    for part in parts:
        text = getattr(part, "text", None)
        if isinstance(text, str):
            return text
    return None


async def _open_session_async(
    command: list[str], env: dict[str, str]
) -> tuple[Any, Any]:
    """Enter stdio_client + ClientSession contexts; return (session, stack).

    The returned :class:`contextlib.AsyncExitStack` owns both context
    managers and MUST be closed on the same event loop that opened it.
    """
    from contextlib import AsyncExitStack

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command=command[0], args=command[1:], env=env)

    # Resolve child stderr at call time, not at mcp-module-import time.
    # ``stdio_client`` binds its ``errlog=sys.stderr`` default when the
    # mcp module first loads; if that happened inside a pytest capsys
    # context, the captured stream lacks a ``fileno()`` and every
    # subsequent subprocess spawn raises ``io.UnsupportedOperation``.
    # Pick a stream that always has a valid OS-level fd.
    errlog = _resolve_child_stderr()

    stack = AsyncExitStack()
    streams = await stack.enter_async_context(stdio_client(params, errlog=errlog))
    read, write = streams
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session, stack


def _resolve_child_stderr() -> Any:
    """Return a stderr stream the child subprocess can inherit.

    Preference order:

    1. ``sys.stderr`` if it exposes a working ``fileno()`` -- normal case
       for CLI and interactive runs.
    2. ``sys.__stderr__`` (the original pre-capture stderr) if usable.
    3. ``os.devnull`` opened for write as a last resort.
    """
    for candidate in (sys.stderr, sys.__stderr__):
        if candidate is None:
            continue
        fileno = getattr(candidate, "fileno", None)
        if not callable(fileno):
            continue
        try:
            fileno()
        except (OSError, ValueError):
            continue
        return candidate
    # Fall back to devnull so the subprocess still gets a valid fd for
    # its stderr. The caller MUST NOT close this stream; the AsyncExitStack
    # is not responsible for it, but the fd leak is bounded to one per
    # spawn and the OS reclaims it on process exit.
    return open(os.devnull, "w")  # noqa: SIM115 - lifetime tied to child


__all__ = [
    "MCP_ENV_SAFE_KEYS",
    "MCP_ENV_SAFE_PREFIXES",
    "MCP_PROGRESS_VERB",
    "McpPool",
    "McpPoolError",
    "McpServerBinaryMissing",
    "McpServerHandshakeFailed",
    "McpServerUnusable",
    "McpServerVerificationFailed",
    "McpToolError",
    "McpToolResponseNotJson",
    "McpToolTimeout",
    "PooledSession",
    "UnknownMcpServer",
]
