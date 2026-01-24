"""Builtin adapter wrapping existing Python check/remediation functions.

This adapter bridges the declarative configuration system with the existing
Python-based check implementations, allowing controls defined in TOML to
delegate verification to the battle-tested Python functions.

Example usage:
    ```python
    adapter = BuiltinCheckAdapter()

    # Check single control
    result = adapter.check(
        control_id="OSPS-AC-03.01",
        owner="org",
        repo="repo",
        local_path="/path/to/repo",
        config={"default_branch": "main"}
    )

    # Check multiple controls
    results = adapter.check_batch(
        control_ids=["OSPS-AC-03.01", "OSPS-AC-03.02"],
        owner="org",
        repo="repo",
        local_path="/path/to/repo",
        config={"default_branch": "main"}
    )
    ```
"""

import logging
from typing import Any, Dict, List, Optional, Set

from darnit.core.adapters import CheckAdapter, RemediationAdapter
from darnit.core.models import (
    AdapterCapability,
    CheckResult,
    CheckStatus,
    RemediationResult,
)

# Import existing check functions
from darnit_baseline.checks.level1 import (
    check_level1_access_control,
    check_level1_build_release,
    check_level1_documentation,
    check_level1_governance,
    check_level1_legal,
    check_level1_quality,
    check_level1_vulnerability,
)
from darnit_baseline.checks.level2 import (
    check_level2_access_control,
    check_level2_build_release,
    check_level2_documentation,
    check_level2_governance,
    check_level2_legal,
    check_level2_quality,
    check_level2_security_architecture,
    check_level2_vulnerability,
)
from darnit_baseline.checks.level3 import (
    check_level3_access_control,
    check_level3_build_release,
    check_level3_documentation,
    check_level3_governance,
    check_level3_quality,
    check_level3_security_architecture,
    check_level3_vulnerability,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Control to Function Mapping
# =============================================================================

# Maps control ID prefixes to their check functions
# Format: (domain_code, level) -> (function, requires_default_branch)
DOMAIN_CHECK_FUNCTIONS: Dict[tuple, tuple] = {
    # Level 1
    ("AC", 1): (check_level1_access_control, True),
    ("BR", 1): (check_level1_build_release, False),
    ("DO", 1): (check_level1_documentation, False),
    ("GV", 1): (check_level1_governance, False),
    ("LE", 1): (check_level1_legal, False),
    ("QA", 1): (check_level1_quality, False),
    ("VM", 1): (check_level1_vulnerability, False),
    # Level 2
    ("AC", 2): (check_level2_access_control, True),
    ("BR", 2): (check_level2_build_release, True),
    ("DO", 2): (check_level2_documentation, False),
    ("GV", 2): (check_level2_governance, False),
    ("LE", 2): (check_level2_legal, False),
    ("QA", 2): (check_level2_quality, True),
    ("SA", 2): (check_level2_security_architecture, False),
    ("VM", 2): (check_level2_vulnerability, False),
    # Level 3
    ("AC", 3): (check_level3_access_control, True),
    ("BR", 3): (check_level3_build_release, True),
    ("DO", 3): (check_level3_documentation, False),
    ("GV", 3): (check_level3_governance, False),
    ("QA", 3): (check_level3_quality, True),
    ("SA", 3): (check_level3_security_architecture, False),
    ("VM", 3): (check_level3_vulnerability, False),
}


def parse_control_id(control_id: str) -> tuple:
    """Parse control ID to extract domain and determine level.

    Control ID format: OSPS-{DOMAIN}-{NN}.{NN}
    Examples:
        OSPS-AC-03.01 -> domain=AC, control numbers imply level

    Args:
        control_id: Control identifier (e.g., "OSPS-AC-03.01")

    Returns:
        Tuple of (domain_code, level)
    """
    # Extract domain from control ID
    # Format: OSPS-{DOMAIN}-{NN}.{NN}
    parts = control_id.split("-")
    if len(parts) >= 2:
        domain = parts[1]  # e.g., "AC", "BR", "VM"
    else:
        domain = "UNKNOWN"

    # Determine level from control ID pattern
    # Level 1: OSPS-XX-01.XX through OSPS-XX-07.XX (roughly)
    # Level 2: OSPS-XX-XX.XX where not in L1/L3
    # Level 3: Higher numbered controls
    # This is a simplification - in practice, level comes from framework config

    # For now, return domain and we'll determine level from config
    return domain


def get_level_for_control(control_id: str) -> int:
    """Determine the OSPS level for a control ID.

    This mapping is based on OSPS v2025.10.10 specification.

    Args:
        control_id: Control identifier

    Returns:
        Level (1, 2, or 3)
    """
    # Level 1 controls
    level1_controls = {
        "OSPS-AC-01.01", "OSPS-AC-02.01", "OSPS-AC-03.01", "OSPS-AC-03.02",
        "OSPS-BR-01.01", "OSPS-BR-01.02", "OSPS-BR-03.01", "OSPS-BR-03.02",
        "OSPS-BR-07.01",
        "OSPS-DO-01.01", "OSPS-DO-02.01",
        "OSPS-GV-02.01", "OSPS-GV-03.01",
        "OSPS-LE-02.01", "OSPS-LE-02.02", "OSPS-LE-03.01", "OSPS-LE-03.02",
        "OSPS-QA-01.01", "OSPS-QA-01.02", "OSPS-QA-02.01", "OSPS-QA-04.01",
        "OSPS-QA-05.01", "OSPS-QA-05.02",
        "OSPS-VM-02.01",
    }

    # Level 2 controls
    level2_controls = {
        "OSPS-AC-03.03",
        "OSPS-BR-02.01", "OSPS-BR-02.02", "OSPS-BR-02.03", "OSPS-BR-05.01",
        "OSPS-DO-03.01", "OSPS-DO-04.01",
        "OSPS-GV-01.01", "OSPS-GV-01.02", "OSPS-GV-03.02", "OSPS-GV-04.01",
        "OSPS-LE-01.01",
        "OSPS-QA-02.02", "OSPS-QA-03.01", "OSPS-QA-07.01",
        "OSPS-SA-02.01", "OSPS-SA-03.01",
        "OSPS-VM-01.01", "OSPS-VM-03.01",
    }

    # Level 3 controls
    level3_controls = {
        "OSPS-AC-01.02", "OSPS-AC-03.04", "OSPS-AC-04.01", "OSPS-AC-04.02",
        "OSPS-BR-02.04", "OSPS-BR-04.01", "OSPS-BR-04.02", "OSPS-BR-06.01",
        "OSPS-DO-05.01", "OSPS-DO-06.01",
        "OSPS-GV-01.03",
        "OSPS-QA-02.03", "OSPS-QA-06.01",
        "OSPS-SA-01.01", "OSPS-SA-03.02",
        "OSPS-VM-04.01", "OSPS-VM-04.02", "OSPS-VM-05.01", "OSPS-VM-05.02",
        "OSPS-VM-05.03",
    }

    if control_id in level1_controls:
        return 1
    elif control_id in level2_controls:
        return 2
    elif control_id in level3_controls:
        return 3
    else:
        # Default to level 1 for unknown controls
        return 1


def status_from_string(status_str: str) -> CheckStatus:
    """Convert status string to CheckStatus enum.

    Args:
        status_str: Status string (PASS, FAIL, WARN, N/A, ERROR)

    Returns:
        CheckStatus enum value
    """
    status_map = {
        "PASS": CheckStatus.PASS,
        "FAIL": CheckStatus.FAIL,
        "WARN": CheckStatus.WARN,
        "N/A": CheckStatus.NA,
        "ERROR": CheckStatus.ERROR,
    }
    return status_map.get(status_str.upper(), CheckStatus.ERROR)


def convert_legacy_result(result_dict: Dict[str, Any]) -> CheckResult:
    """Convert legacy result dict to CheckResult.

    Legacy format: {"id": str, "status": str, "details": str, "level": int}
    New format: CheckResult dataclass

    Args:
        result_dict: Legacy result dictionary

    Returns:
        CheckResult instance
    """
    return CheckResult(
        control_id=result_dict.get("id", "UNKNOWN"),
        status=status_from_string(result_dict.get("status", "ERROR")),
        message=result_dict.get("details", ""),
        level=result_dict.get("level", 1),
        source="builtin",
    )


# =============================================================================
# Builtin Check Adapter
# =============================================================================


class BuiltinCheckAdapter(CheckAdapter):
    """Adapter that delegates to existing Python check functions.

    This adapter wraps the existing domain-specific check functions
    (check_level1_access_control, check_level2_vulnerability, etc.)
    and exposes them through the unified CheckAdapter interface.

    The adapter supports:
    - Single control checks via check()
    - Batch checks via check_batch() for efficiency
    - Automatic routing to the correct domain function

    Example:
        ```python
        adapter = BuiltinCheckAdapter()
        result = adapter.check(
            "OSPS-AC-03.01", "owner", "repo", "/path", {"default_branch": "main"}
        )
        ```
    """

    def __init__(self):
        """Initialize the builtin adapter."""
        self._result_cache: Dict[str, List[CheckResult]] = {}

    def name(self) -> str:
        """Return adapter name."""
        return "builtin"

    def capabilities(self) -> AdapterCapability:
        """Return what controls this adapter can check.

        The builtin adapter supports all OSPS controls.
        """
        return AdapterCapability(
            control_ids={"*"},  # Supports all controls
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
        """Run check for a specific control.

        Routes the check to the appropriate domain function based on
        the control ID, then filters the results to return only the
        requested control's result.

        Args:
            control_id: Control identifier (e.g., "OSPS-AC-03.01")
            owner: GitHub owner/org
            repo: Repository name
            local_path: Path to local repository clone
            config: Additional configuration (e.g., default_branch)

        Returns:
            CheckResult for the specified control
        """
        # Get all results for this control's domain
        domain_results = self._run_domain_check(
            control_id, owner, repo, local_path, config
        )

        # Find the specific control result
        for result in domain_results:
            if result.control_id == control_id:
                return result

        # Control not found in domain results
        return CheckResult(
            control_id=control_id,
            status=CheckStatus.ERROR,
            message=f"Control {control_id} not found in domain check results",
            level=get_level_for_control(control_id),
            source="builtin",
        )

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        """Run checks for multiple controls efficiently.

        Groups controls by domain and runs each domain check once,
        then collects and returns all requested results.

        Args:
            control_ids: List of control identifiers
            owner: GitHub owner/org
            repo: Repository name
            local_path: Path to local repository clone
            config: Additional configuration

        Returns:
            List of CheckResult for all requested controls
        """
        results = []
        checked_domains: Set[tuple] = set()

        for control_id in control_ids:
            domain = parse_control_id(control_id)
            level = get_level_for_control(control_id)
            domain_key = (domain, level)

            # Run domain check if not already done
            if domain_key not in checked_domains:
                domain_results = self._run_domain_check(
                    control_id, owner, repo, local_path, config
                )
                # Cache all domain results
                for result in domain_results:
                    if result.control_id in control_ids:
                        results.append(result)
                checked_domains.add(domain_key)

        # Ensure we have results for all requested controls
        found_ids = {r.control_id for r in results}
        for control_id in control_ids:
            if control_id not in found_ids:
                results.append(CheckResult(
                    control_id=control_id,
                    status=CheckStatus.ERROR,
                    message=f"Control {control_id} not implemented in builtin checks",
                    level=get_level_for_control(control_id),
                    source="builtin",
                ))

        return results

    def _run_domain_check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        """Run the domain check function for a control.

        Args:
            control_id: Control identifier to determine domain
            owner: GitHub owner/org
            repo: Repository name
            local_path: Path to local repository clone
            config: Additional configuration

        Returns:
            List of CheckResult from the domain check
        """
        domain = parse_control_id(control_id)
        level = get_level_for_control(control_id)
        domain_key = (domain, level)

        # Get the check function for this domain/level
        func_info = DOMAIN_CHECK_FUNCTIONS.get(domain_key)
        if not func_info:
            logger.warning(f"No check function for domain {domain} level {level}")
            return []

        check_func, requires_default_branch = func_info
        default_branch = config.get("default_branch", "main")

        try:
            # Call the check function with appropriate arguments
            if requires_default_branch:
                legacy_results = check_func(owner, repo, local_path, default_branch)
            else:
                legacy_results = check_func(owner, repo, local_path)

            # Convert legacy results to CheckResult
            return [convert_legacy_result(r) for r in legacy_results]

        except Exception as e:
            logger.error(f"Error running {domain} level {level} checks: {e}")
            return [CheckResult(
                control_id=control_id,
                status=CheckStatus.ERROR,
                message=f"Error running domain check: {e}",
                level=level,
                source="builtin",
            )]


# =============================================================================
# Builtin Remediation Adapter
# =============================================================================


class BuiltinRemediationAdapter(RemediationAdapter):
    """Adapter that delegates to existing Python remediation functions.

    This adapter wraps the existing remediation functions and exposes
    them through the unified RemediationAdapter interface.
    """

    def __init__(self):
        """Initialize the builtin remediation adapter."""
        # Lazy import to avoid circular dependencies
        self._remediation_registry = None

    def name(self) -> str:
        """Return adapter name."""
        return "builtin"

    def capabilities(self) -> AdapterCapability:
        """Return what controls this adapter can remediate."""
        # Get supported controls from remediation registry
        supported = self._get_supported_controls()
        return AdapterCapability(
            control_ids=supported,
            supports_batch=False,
        )

    def _get_supported_controls(self) -> Set[str]:
        """Get set of control IDs that can be remediated."""
        try:
            from darnit_baseline.remediation.registry import get_remediation_registry
            registry = get_remediation_registry()
            return set(registry.keys())
        except ImportError:
            return set()

    def remediate(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Apply remediation for a specific control.

        Args:
            control_id: Control identifier
            owner: GitHub owner/org
            repo: Repository name
            local_path: Path to local repository clone
            config: Additional configuration
            dry_run: If True, show what would be done without making changes

        Returns:
            RemediationResult describing the outcome
        """
        try:
            from darnit_baseline.remediation.registry import get_remediation_registry
            registry = get_remediation_registry()

            if control_id not in registry:
                return RemediationResult(
                    control_id=control_id,
                    success=False,
                    message=f"No remediation available for {control_id}",
                    source="builtin",
                )

            remediation_func = registry[control_id]

            # Call remediation function
            # Most remediation functions expect: local_path, owner, repo, dry_run
            result = remediation_func(
                local_path=local_path,
                owner=owner,
                repo=repo,
                dry_run=dry_run,
            )

            # Convert to RemediationResult if needed
            if isinstance(result, RemediationResult):
                return result
            elif isinstance(result, dict):
                return RemediationResult(
                    control_id=control_id,
                    success=result.get("success", False),
                    message=result.get("message", ""),
                    changes_made=result.get("changes_made", []),
                    requires_manual_action=result.get("requires_manual_action", False),
                    manual_steps=result.get("manual_steps", []),
                    source="builtin",
                )
            else:
                return RemediationResult(
                    control_id=control_id,
                    success=True,
                    message=str(result) if result else "Remediation completed",
                    source="builtin",
                )

        except ImportError as e:
            logger.error(f"Could not import remediation registry: {e}")
            return RemediationResult(
                control_id=control_id,
                success=False,
                message=f"Remediation not available: {e}",
                source="builtin",
            )
        except Exception as e:
            logger.error(f"Error running remediation for {control_id}: {e}")
            return RemediationResult(
                control_id=control_id,
                success=False,
                message=f"Remediation failed: {e}",
                source="builtin",
            )


# =============================================================================
# Factory Functions
# =============================================================================

# Singleton instances
_builtin_check_adapter: Optional[BuiltinCheckAdapter] = None
_builtin_remediation_adapter: Optional[BuiltinRemediationAdapter] = None


def get_builtin_check_adapter() -> BuiltinCheckAdapter:
    """Get the singleton builtin check adapter instance.

    Returns:
        BuiltinCheckAdapter instance
    """
    global _builtin_check_adapter
    if _builtin_check_adapter is None:
        _builtin_check_adapter = BuiltinCheckAdapter()
    return _builtin_check_adapter


def get_builtin_remediation_adapter() -> BuiltinRemediationAdapter:
    """Get the singleton builtin remediation adapter instance.

    Returns:
        BuiltinRemediationAdapter instance
    """
    global _builtin_remediation_adapter
    if _builtin_remediation_adapter is None:
        _builtin_remediation_adapter = BuiltinRemediationAdapter()
    return _builtin_remediation_adapter
