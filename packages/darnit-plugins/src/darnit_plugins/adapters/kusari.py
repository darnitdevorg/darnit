"""Kusari adapter for darnit.

This module provides a check adapter that wraps the Kusari CLI tool
for analyzing code changes, dependencies, and security posture.

Kusari Inspector analyzes the differences between a git repository's working
tree and a specified revision. It performs:

- **Dependency Analysis**: Identifies added/removed/modified dependencies
- **SBOM Generation**: Creates Software Bill of Materials when needed
- **Vulnerability Scanning**: Checks dependencies against known vulnerabilities
- **Code Change Analysis**: Reviews code modifications for security implications

The analysis results are uploaded to Kusari Console and returned in the
specified output format (markdown or SARIF).

Usage:
    The adapter can be referenced by name in framework configs::

        # In framework.toml or .baseline.toml
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
            {"git_rev": "HEAD", "output_format": "sarif"},
        )

Configuration Options:
    The adapter accepts the following configuration options:

    - ``git_rev``: Git revision to compare against (default: "HEAD")
        Examples: "HEAD", "HEAD^", "origin/main", commit SHA
    - ``output_format``: Output format - "markdown" or "sarif" (default: "markdown")
    - ``wait``: Wait for results (default: True)
    - ``console_url``: Kusari Console URL (optional)
    - ``platform_url``: Kusari Platform URL (optional)
    - ``verbose``: Enable verbose output (default: False)

Requirements:
    Kusari CLI must be installed and authenticated::

        # Install
        brew install kusari
        # or download from https://github.com/kusaridev/kusari-cli

        # Authenticate
        kusari auth login

See Also:
    - https://github.com/kusaridev/kusari-cli for CLI documentation
    - https://console.us.kusari.cloud/ for Kusari Console
"""

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus

logger = logging.getLogger(__name__)


class KusariCheckAdapter(CheckAdapter):
    """Check adapter that wraps the Kusari CLI tool.

    Kusari analyzes code changes between the working tree and a git revision,
    performing dependency analysis, SBOM generation, and vulnerability scanning.
    Results are uploaded to Kusari Console and returned for compliance checking.

    Attributes:
        _kusari_path: Path to the kusari binary
        _timeout: Command timeout in seconds
        _default_git_rev: Default git revision for comparisons

    Example:
        Basic usage with default settings (compare against HEAD)::

            adapter = KusariCheckAdapter()
            result = adapter.check(
                control_id="OSPS-VM-05.03",
                owner="kusari-oss",
                repo="darnit",
                local_path="/path/to/repo",
                config={},  # Uses HEAD by default
            )

        Compare against a specific revision::

            result = adapter.check(
                control_id="OSPS-VM-05.02",
                owner="",
                repo="myproject",
                local_path="/path/to/repo",
                config={
                    "git_rev": "origin/main",
                    "output_format": "sarif",
                },
            )

        Check pre-release changes (compare working tree to last commit)::

            result = adapter.check(
                control_id="OSPS-VM-05.02",
                owner="",
                repo="myproject",
                local_path="/path/to/repo",
                config={"git_rev": "HEAD"},
            )

    See Also:
        - :class:`darnit.core.adapters.CheckAdapter` for the base interface
    """

    # Controls this adapter can handle
    # These map to OpenSSF Baseline controls related to dependency/vulnerability management
    SUPPORTED_CONTROLS = {
        # Vulnerability Management controls
        "OSPS-VM-05.01",  # Automated dependency vulnerability scanning
        "OSPS-VM-05.02",  # Pre-release SCA (software composition analysis)
        "OSPS-VM-05.03",  # Known vulnerability remediation
        # Build & Release controls
        "OSPS-BR-01.02",  # SBOM generation
        "OSPS-BR-01.03",  # Dependency inventory
    }

    def __init__(
        self,
        kusari_path: str = "kusari",
        timeout: int = 300,
        default_git_rev: str = "HEAD",
    ):
        """Initialize the Kusari adapter.

        Args:
            kusari_path: Path to the kusari binary (default: "kusari")
            timeout: Command timeout in seconds (default: 300)
            default_git_rev: Default git revision for comparisons (default: "HEAD")
        """
        self._kusari_path = kusari_path
        self._timeout = timeout
        self._default_git_rev = default_git_rev

    def name(self) -> str:
        """Return adapter name.

        Returns:
            The string "kusari"
        """
        return "kusari"

    def capabilities(self) -> AdapterCapability:
        """Return adapter capabilities.

        Kusari supports batch operations since a single scan can provide
        data for multiple controls (dependencies, vulnerabilities, SBOM).

        Returns:
            AdapterCapability indicating supported controls and features

        Example:
            >>> adapter = KusariCheckAdapter()
            >>> caps = adapter.capabilities()
            >>> "OSPS-VM-05.02" in caps.control_ids
            True
            >>> caps.supports_batch
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
        """Run a compliance check using Kusari repo scan.

        Executes ``kusari repo scan <local_path> <git_rev>`` to analyze
        code changes and dependencies. The scan results are used to
        determine compliance with the specified control.

        Args:
            control_id: The control identifier to check
            owner: Repository owner (used for context, not in command)
            repo: Repository name (used for context, not in command)
            local_path: Path to the local git repository
            config: Configuration options:
                - git_rev: Git revision to compare against (default: "HEAD")
                - output_format: "markdown" or "sarif" (default: "markdown")
                - wait: Wait for results (default: True)
                - verbose: Enable verbose output (default: False)

        Returns:
            CheckResult with the scan outcome and any findings

        Example:
            >>> result = adapter.check(
            ...     "OSPS-VM-05.03",
            ...     "kusari-oss",
            ...     "darnit",
            ...     "/path/to/repo",
            ...     {"git_rev": "HEAD", "output_format": "sarif"},
            ... )
            >>> print(result.status)
        """
        git_rev = config.get("git_rev", self._default_git_rev)
        output_format = config.get("output_format", "markdown")
        wait = config.get("wait", True)
        verbose = config.get("verbose", False)

        # Build the kusari repo scan command
        cmd = [
            self._kusari_path,
            "repo",
            "scan",
            local_path,
            git_rev,
            "--output-format",
            output_format,
        ]

        if wait:
            cmd.append("--wait")

        if verbose:
            cmd.append("--verbose")

        # Add optional URL overrides
        if config.get("console_url"):
            cmd.extend(["--console-url", config["console_url"]])
        if config.get("platform_url"):
            cmd.extend(["--platform-url", config["platform_url"]])

        logger.debug(f"Running Kusari command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )

            # Parse the output based on format and control type
            return self._parse_result(
                control_id=control_id,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                output_format=output_format,
            )

        except subprocess.TimeoutExpired:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.ERROR,
                message=f"Kusari scan timed out after {self._timeout}s",
                level=self._get_control_level(control_id),
                source="kusari",
            )
        except FileNotFoundError:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.ERROR,
                message=(
                    f"Kusari CLI not found at '{self._kusari_path}'. "
                    "Install with: brew install kusari"
                ),
                level=self._get_control_level(control_id),
                source="kusari",
            )
        except Exception as e:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.ERROR,
                message=f"Kusari scan failed: {e}",
                level=self._get_control_level(control_id),
                source="kusari",
            )

    def _parse_result(
        self,
        control_id: str,
        returncode: int,
        stdout: str,
        stderr: str,
        output_format: str,
    ) -> CheckResult:
        """Parse Kusari output into a CheckResult.

        Args:
            control_id: The control being checked
            returncode: Command exit code
            stdout: Command stdout
            stderr: Command stderr
            output_format: Output format used ("markdown" or "sarif")

        Returns:
            CheckResult based on scan findings
        """
        level = self._get_control_level(control_id)

        # Check for authentication errors
        if "auth error" in stderr.lower() or "token is expired" in stderr.lower():
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.ERROR,
                message="Kusari authentication required. Run: kusari auth login",
                level=level,
                source="kusari",
            )

        # SARIF format parsing
        if output_format == "sarif":
            return self._parse_sarif_result(control_id, stdout, stderr, level)

        # Markdown format - check for flagged issues
        if "No Flagged Issues Detected" in stdout:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.PASS,
                message="Kusari scan completed with no flagged issues",
                level=level,
                source="kusari",
                evidence=stdout[:500] if stdout else None,
            )
        elif "Flagged Issues Detected" in stdout:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.FAIL,
                message="Kusari scan detected flagged issues",
                level=level,
                source="kusari",
                details={"raw_output": stdout},
                evidence=stdout[:1000] if stdout else None,
            )
        elif returncode == 0:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.PASS,
                message="Kusari scan completed successfully",
                level=level,
                source="kusari",
                evidence=stdout[:500] if stdout else None,
            )
        else:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.FAIL,
                message=f"Kusari scan failed: {stderr or stdout}",
                level=level,
                source="kusari",
            )

    def _parse_sarif_result(
        self,
        control_id: str,
        stdout: str,
        stderr: str,
        level: int,
    ) -> CheckResult:
        """Parse SARIF format output.

        Args:
            control_id: The control being checked
            stdout: SARIF JSON output
            stderr: Command stderr
            level: Control level

        Returns:
            CheckResult based on SARIF findings
        """
        try:
            sarif = json.loads(stdout)
            runs = sarif.get("runs", [])

            total_results = 0
            errors = 0
            warnings = 0

            for run in runs:
                for result in run.get("results", []):
                    total_results += 1
                    result_level = result.get("level", "note")
                    if result_level == "error":
                        errors += 1
                    elif result_level == "warning":
                        warnings += 1

            if errors > 0:
                return CheckResult(
                    control_id=control_id,
                    status=CheckStatus.FAIL,
                    message=f"Kusari found {errors} error(s) and {warnings} warning(s)",
                    level=level,
                    source="kusari",
                    details={"sarif": sarif, "errors": errors, "warnings": warnings},
                )
            elif warnings > 0:
                return CheckResult(
                    control_id=control_id,
                    status=CheckStatus.WARN,
                    message=f"Kusari found {warnings} warning(s)",
                    level=level,
                    source="kusari",
                    details={"sarif": sarif, "warnings": warnings},
                )
            else:
                return CheckResult(
                    control_id=control_id,
                    status=CheckStatus.PASS,
                    message="Kusari scan completed with no issues",
                    level=level,
                    source="kusari",
                )

        except json.JSONDecodeError:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.ERROR,
                message=f"Failed to parse Kusari SARIF output: {stderr or stdout[:200]}",
                level=level,
                source="kusari",
            )

    def _get_control_level(self, control_id: str) -> int:
        """Get the maturity level for a control.

        Args:
            control_id: The control identifier

        Returns:
            Maturity level (1, 2, or 3)
        """
        # Level mappings based on OpenSSF Baseline
        level_map = {
            "OSPS-VM-05.01": 2,  # Automated scanning
            "OSPS-VM-05.02": 3,  # Pre-release SCA
            "OSPS-VM-05.03": 3,  # Known vulnerability remediation
            "OSPS-BR-01.02": 2,  # SBOM generation
            "OSPS-BR-01.03": 2,  # Dependency inventory
        }
        return level_map.get(control_id, 1)

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        """Run checks for multiple controls using a single Kusari scan.

        Since Kusari performs comprehensive analysis in a single scan,
        this method runs the scan once and maps the results to multiple
        controls based on the findings.

        Args:
            control_ids: List of control identifiers to check
            owner: Repository owner
            repo: Repository name
            local_path: Path to the local repository
            config: Configuration options (see check() for details)

        Returns:
            List of CheckResult objects, one per control

        Example:
            >>> results = adapter.check_batch(
            ...     ["OSPS-VM-05.02", "OSPS-VM-05.03", "OSPS-BR-01.02"],
            ...     "kusari-oss",
            ...     "darnit",
            ...     "/path/to/repo",
            ...     {"git_rev": "HEAD"},
            ... )
            >>> for r in results:
            ...     print(f"{r.control_id}: {r.status.value}")
        """
        # Run a single scan with SARIF output for detailed parsing
        sarif_config = dict(config)
        sarif_config["output_format"] = "sarif"

        # Use the first control for the initial scan
        primary_result = self.check(
            control_ids[0] if control_ids else "OSPS-VM-05.01",
            owner,
            repo,
            local_path,
            sarif_config,
        )

        # If scan failed, return error for all controls
        if primary_result.status == CheckStatus.ERROR:
            return [
                CheckResult(
                    control_id=cid,
                    status=CheckStatus.ERROR,
                    message=primary_result.message,
                    level=self._get_control_level(cid),
                    source="kusari",
                )
                for cid in control_ids
            ]

        # Map scan results to individual controls
        # In a full implementation, this would parse SARIF findings
        # and map specific issues to specific controls
        results = []
        for control_id in control_ids:
            results.append(
                CheckResult(
                    control_id=control_id,
                    status=primary_result.status,
                    message=primary_result.message,
                    level=self._get_control_level(control_id),
                    source="kusari",
                    details=primary_result.details,
                )
            )

        return results
