"""Echo adapter for testing and examples.

This module provides a simple check adapter that echoes back the
configuration as the result. Useful for testing, examples, and
debugging adapter integration.

Usage:
    In a framework config::

        [controls."TEST-001"]
        check = { adapter = "echo", config = { status = "PASS" } }

    Programmatically::

        from darnit_plugins.adapters.echo import EchoCheckAdapter

        adapter = EchoCheckAdapter()
        result = adapter.check(
            "TEST-001",
            "",
            "",
            "/path",
            {"status": "PASS", "message": "All good!"},
        )
        print(result.status)   # PASS
        print(result.message)  # All good!

Configuration:
    The adapter accepts the following configuration options:

    - ``status``: CheckStatus to return (PASS, FAIL, ERROR, SKIP, MANUAL)
    - ``message``: Message to include in result
    - ``delay``: Seconds to sleep before returning (for testing timeouts)

Example:
    Testing a framework's control routing::

        # .baseline.toml
        [controls."MY-CTRL-01"]
        check = { adapter = "echo", config = { status = "PASS" } }

        [controls."MY-CTRL-02"]
        check = { adapter = "echo", config = { status = "FAIL", message = "Test failure" } }

See Also:
    - :class:`darnit.core.adapters.CheckAdapter` for the adapter interface
"""

import time
from typing import Any, Dict, List

from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus


class EchoCheckAdapter(CheckAdapter):
    """Simple echo adapter for testing and examples.

    Returns configurable results based on the provided configuration.
    Useful for testing framework integration, control routing, and
    as an example for building custom adapters.

    Attributes:
        default_status: Default status when not specified in config

    Example:
        Basic usage::

            adapter = EchoCheckAdapter()

            # Returns PASS
            result = adapter.check("CTRL-001", "", "", "/path", {
                "status": "PASS",
                "message": "Everything is fine",
            })

            # Returns FAIL
            result = adapter.check("CTRL-002", "", "", "/path", {
                "status": "FAIL",
                "message": "Something went wrong",
            })

        Testing timeout handling::

            result = adapter.check("CTRL-003", "", "", "/path", {
                "delay": 5,  # Sleep for 5 seconds
                "status": "PASS",
            })

    See Also:
        - :class:`darnit.core.adapters.CheckAdapter` for the base interface
    """

    def __init__(self, default_status: str = "PASS"):
        """Initialize the echo adapter.

        Args:
            default_status: Default status when not specified in config
        """
        self.default_status = default_status

    def name(self) -> str:
        """Return adapter name.

        Returns:
            The string "echo"
        """
        return "echo"

    def capabilities(self) -> AdapterCapability:
        """Return adapter capabilities.

        The echo adapter can handle any control (wildcard).

        Returns:
            AdapterCapability with wildcard control support
        """
        return AdapterCapability(
            control_ids={"*"},  # Handles any control
            supports_batch=True,
        )

    def check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> CheckResult:
        """Return a check result based on configuration.

        Args:
            control_id: The control identifier
            owner: Repository owner (ignored)
            repo: Repository name (ignored)
            local_path: Path to repository (ignored)
            config: Configuration dict with optional keys:
                - status: CheckStatus string (PASS, FAIL, ERROR, SKIP, MANUAL)
                - message: Result message
                - delay: Seconds to sleep before returning
                - level: Control level (1, 2, 3)

        Returns:
            CheckResult with configured status and message

        Example:
            >>> adapter = EchoCheckAdapter()
            >>> result = adapter.check("TEST-001", "", "", "/path", {
            ...     "status": "PASS",
            ...     "message": "Test passed!",
            ... })
            >>> result.status
            <CheckStatus.PASS: 'PASS'>
        """
        # Optional delay for testing timeouts
        delay = config.get("delay", 0)
        if delay:
            time.sleep(delay)

        # Get status from config or default
        status_str = config.get("status", self.default_status)
        try:
            # Handle case-insensitive status values
            status = CheckStatus(status_str.lower())
        except (ValueError, AttributeError):
            status = CheckStatus.ERROR
            status_str = f"Invalid status '{status_str}', using ERROR"

        # Get message from config or generate one
        message = config.get(
            "message",
            f"Echo adapter: {control_id} returned {status_str}",
        )

        # Get level from config or default to 1
        level = config.get("level", 1)

        return CheckResult(
            control_id=control_id,
            status=status,
            message=message,
            level=level,
            source="echo",
        )

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        """Return check results for multiple controls.

        Args:
            control_ids: List of control identifiers
            owner: Repository owner
            repo: Repository name
            local_path: Path to repository
            config: Configuration dict (applied to all controls)

        Returns:
            List of CheckResult objects

        Example:
            >>> results = adapter.check_batch(
            ...     ["TEST-001", "TEST-002"],
            ...     "", "", "/path",
            ...     {"status": "PASS"},
            ... )
            >>> len(results)
            2
        """
        return [
            self.check(control_id, owner, repo, local_path, config)
            for control_id in control_ids
        ]
