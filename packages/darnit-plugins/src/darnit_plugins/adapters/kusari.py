"""Kusari SBOM/SCA adapter for darnit.

This module provides a check adapter that wraps the Kusari CLI tool
for software composition analysis (SCA) and SBOM generation.

Kusari is a tool for analyzing software dependencies and generating
Software Bill of Materials (SBOM) in various formats.

Usage:
    The adapter can be referenced by name in framework configs::

        # In framework.toml
        [controls."OSPS-VM-05.02"]
        check = { adapter = "kusari" }

    Or instantiated directly::

        from darnit_plugins.adapters.kusari import KusariCheckAdapter

        adapter = KusariCheckAdapter()
        result = adapter.check(
            "OSPS-VM-05.02",
            "owner",
            "repo",
            "/path/to/repo",
            {"severity": "high"},
        )

Configuration:
    The adapter accepts the following configuration options:

    - ``command``: Path to kusari binary (default: "kusari")
    - ``severity``: Minimum severity to report (low, medium, high, critical)
    - ``format``: Output format (json, sarif, cyclonedx)
    - ``timeout``: Command timeout in seconds (default: 300)

Requirements:
    Kusari must be installed and available in PATH::

        pip install kusari
        # or
        brew install kusari

See Also:
    - https://github.com/kusaridev/kusari for Kusari documentation
    - :class:`darnit.core.adapters.CommandCheckAdapter` for CLI wrapper base
"""

from typing import Any, Dict, List, Optional

from darnit.core.adapters import CheckAdapter, CommandCheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus


class KusariCheckAdapter(CheckAdapter):
    """Check adapter that wraps the Kusari SBOM/SCA CLI tool.

    This adapter delegates to the Kusari command-line tool to perform
    software composition analysis checks.

    Attributes:
        _command: The underlying CommandCheckAdapter instance
        _kusari_path: Path to the kusari binary

    Example:
        Basic usage::

            adapter = KusariCheckAdapter()

            # Check for dependency vulnerabilities
            result = adapter.check(
                control_id="OSPS-VM-05.03",
                owner="",
                repo="myproject",
                local_path="/path/to/repo",
                config={"severity": "high"},
            )

            if result.status == CheckStatus.PASS:
                print("No vulnerabilities found!")
            else:
                print(f"Issues: {result.message}")

        With custom kusari path::

            adapter = KusariCheckAdapter(kusari_path="/opt/tools/kusari")

    See Also:
        - :class:`darnit.core.adapters.CheckAdapter` for the base interface
        - :class:`darnit.core.adapters.CommandCheckAdapter` for CLI wrapping
    """

    # Controls this adapter can handle
    SUPPORTED_CONTROLS = {
        # Dependency scanning controls
        "OSPS-VM-05.02",  # Pre-release SCA
        "OSPS-VM-05.03",  # Known vulnerabilities
        # SBOM controls
        "OSPS-BR-01.02",  # SBOM generation
        # Generic SCA controls (can be used by any framework)
        "*-SCA-*",  # Wildcard for SCA controls
        "*-SBOM-*",  # Wildcard for SBOM controls
    }

    def __init__(
        self,
        kusari_path: str = "kusari",
        timeout: int = 300,
    ):
        """Initialize the Kusari adapter.

        Args:
            kusari_path: Path to the kusari binary (default: "kusari")
            timeout: Command timeout in seconds (default: 300)
        """
        self._kusari_path = kusari_path
        self._timeout = timeout
        self._command = CommandCheckAdapter(
            adapter_name="kusari",
            command=kusari_path,
            output_format="json",
            timeout=timeout,
        )

    def name(self) -> str:
        """Return adapter name.

        Returns:
            The string "kusari"
        """
        return "kusari"

    def capabilities(self) -> AdapterCapability:
        """Return adapter capabilities.

        Returns:
            AdapterCapability indicating supported controls and features

        Example:
            >>> adapter = KusariCheckAdapter()
            >>> caps = adapter.capabilities()
            >>> print(caps.supports_batch)
            True
        """
        return AdapterCapability(
            control_ids=self.SUPPORTED_CONTROLS,
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
        """Run a check using Kusari.

        Maps the control ID to the appropriate Kusari subcommand and
        executes the scan.

        Args:
            control_id: The control identifier to check
            owner: Repository owner (may be empty)
            repo: Repository name
            local_path: Path to the local repository
            config: Additional configuration options

        Returns:
            CheckResult with the scan outcome

        Example:
            >>> result = adapter.check(
            ...     "OSPS-VM-05.03",
            ...     "",
            ...     "myrepo",
            ...     "/path/to/repo",
            ...     {"severity": "high"},
            ... )
            >>> print(result.status)
        """
        # Map control to kusari scan type
        enhanced_config = dict(config)

        if "VM-05" in control_id:
            # Vulnerability scanning
            enhanced_config.setdefault("scan_type", "vulnerabilities")
        elif "BR-01" in control_id or "SBOM" in control_id:
            # SBOM generation
            enhanced_config.setdefault("scan_type", "sbom")
        elif "SCA" in control_id:
            # Generic SCA
            enhanced_config.setdefault("scan_type", "dependencies")

        return self._command.check(
            control_id,
            owner,
            repo,
            local_path,
            enhanced_config,
        )

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        """Run checks for multiple controls.

        For efficiency, groups controls by scan type and runs
        Kusari once per scan type.

        Args:
            control_ids: List of control identifiers to check
            owner: Repository owner
            repo: Repository name
            local_path: Path to the local repository
            config: Additional configuration options

        Returns:
            List of CheckResult objects

        Example:
            >>> results = adapter.check_batch(
            ...     ["OSPS-VM-05.02", "OSPS-VM-05.03"],
            ...     "",
            ...     "myrepo",
            ...     "/path/to/repo",
            ...     {},
            ... )
            >>> for r in results:
            ...     print(f"{r.control_id}: {r.status}")
        """
        # Simple implementation: check each control
        # A more sophisticated implementation could batch by scan type
        return [
            self.check(control_id, owner, repo, local_path, config)
            for control_id in control_ids
        ]
