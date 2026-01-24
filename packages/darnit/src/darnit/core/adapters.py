"""Abstract base classes and registry for pluggable check and remediation adapters.

This module provides:
- Abstract base classes for check and remediation adapters
- Concrete adapter implementations (Command, Script)
- AdapterRegistry for managing adapter discovery and instantiation
- Resolution functions for loading adapters from configuration
"""

from abc import ABC, abstractmethod
import importlib
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, Union

from darnit.core.models import (
    CheckResult,
    RemediationResult,
    AdapterCapability,
)

logger = logging.getLogger(__name__)


class CheckAdapter(ABC):
    """Base class for check adapters.

    # TODO: Shared Execution Context (Future Enhancement)
    # Currently each check() call is independent. To support tools like OpenSSF Scorecard
    # that run once and produce results for multiple controls, we need:
    #
    # 1. Add ExecutionContext parameter to check() and check_batch():
    #    def check(self, control_id, owner, repo, local_path, config,
    #              context: Optional[ExecutionContext] = None) -> CheckResult
    #
    # 2. Add prefetch() method for adapters to run tool once and cache results:
    #    def prefetch(self, context: ExecutionContext, control_ids: List[str]) -> None
    #
    # 3. ExecutionContext would contain:
    #    - tool_outputs: Dict[str, Any]  # Cached tool outputs (scorecard, trivy, etc.)
    #    - api_responses: Dict[str, Any]  # Cached GitHub API responses
    #    - cached_results: Dict[str, CheckResult]  # Already-computed results
    #
    # See: darnit/core/models.py for ExecutionContext definition
    # See: docs/declarative-configuration.md for design discussion
    """

    @abstractmethod
    def name(self) -> str:
        """Return adapter name."""
        pass

    @abstractmethod
    def capabilities(self) -> AdapterCapability:
        """Return what controls this adapter can check."""
        pass

    @abstractmethod
    def check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any]
    ) -> CheckResult:
        """Run check for a specific control."""
        pass

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any]
    ) -> List[CheckResult]:
        """
        Run checks for multiple controls in a single invocation.
        Default implementation calls check() for each control.
        Override for adapters that support batch operations.

        # TODO: Enhance batch support for shared tool runs
        # For tools like Scorecard that produce multiple results per run:
        #
        # 1. Add optional ExecutionContext parameter for result caching
        # 2. Implement internal caching pattern for adapters:
        #    ```python
        #    _cached_result = None
        #    _cached_path = None
        #
        #    def check(self, control_id, ...):
        #        if self._cached_path != local_path:
        #            self._cached_result = self._run_tool(local_path)
        #            self._cached_path = local_path
        #        return self._extract_control(control_id, self._cached_result)
        #    ```
        #
        # 3. Consider adding cache_key to AdapterCapability for explicit caching
        """
        results = []
        for control_id in control_ids:
            results.append(self.check(control_id, owner, repo, local_path, config))
        return results

    def supports_control(self, control_id: str) -> bool:
        """Check if this adapter can handle a specific control."""
        caps = self.capabilities()
        return "*" in caps.control_ids or control_id in caps.control_ids


class RemediationAdapter(ABC):
    """Base class for remediation adapters."""

    @abstractmethod
    def name(self) -> str:
        """Return adapter name."""
        pass

    @abstractmethod
    def capabilities(self) -> AdapterCapability:
        """Return what controls this adapter can remediate."""
        pass

    @abstractmethod
    def remediate(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
        dry_run: bool = True
    ) -> RemediationResult:
        """Apply remediation for a specific control."""
        pass

    def preview(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any]
    ) -> str:
        """Preview what remediation would do (dry run)."""
        result = self.remediate(control_id, owner, repo, local_path, config, dry_run=True)
        return result.message

    def supports_control(self, control_id: str) -> bool:
        """Check if this adapter can handle a specific control."""
        caps = self.capabilities()
        return "*" in caps.control_ids or control_id in caps.control_ids


# =============================================================================
# Concrete Adapter Implementations
# =============================================================================


class CommandCheckAdapter(CheckAdapter):
    """Adapter that runs an external command for checks.

    Supports CLI tools like Kusari, Trivy, etc. that output JSON results.

    Example config:
        ```toml
        [adapters.kusari]
        type = "command"
        command = "kusari"
        output_format = "json"
        ```
    """

    def __init__(
        self,
        adapter_name: str,
        command: str,
        output_format: str = "json",
        timeout: int = 300,
        control_ids: Optional[List[str]] = None,
    ):
        self._name = adapter_name
        self._command = command
        self._output_format = output_format
        self._timeout = timeout
        self._control_ids = control_ids or ["*"]

    def name(self) -> str:
        return self._name

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids=set(self._control_ids),
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
        """Run command and parse output."""

        try:
            # Build command with arguments
            cmd = [self._command]

            # Add common arguments
            if owner and repo:
                cmd.extend(["--owner", owner, "--repo", repo])
            if local_path:
                cmd.extend(["--path", local_path])
            if control_id:
                cmd.extend(["--control", control_id])

            # Add any extra config
            for key, value in config.items():
                if isinstance(value, bool):
                    if value:
                        cmd.append(f"--{key}")
                else:
                    cmd.extend([f"--{key}", str(value)])

            logger.debug(f"Running command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )

            if self._output_format == "json":
                try:
                    output = json.loads(result.stdout)
                    return CheckResult(
                        control_id=control_id,
                        status=output.get("status", "ERROR"),
                        message=output.get("message", result.stdout),
                        level=output.get("level", 1),
                        source=self._name,
                    )
                except json.JSONDecodeError:
                    pass

            # Non-JSON or parse failure
            status = "PASS" if result.returncode == 0 else "FAIL"
            return CheckResult(
                control_id=control_id,
                status=status,
                message=result.stdout or result.stderr,
                level=1,
                source=self._name,
            )

        except subprocess.TimeoutExpired:
            return CheckResult(
                control_id=control_id,
                status="ERROR",
                message=f"Command timed out after {self._timeout}s",
                level=1,
                source=self._name,
            )
        except FileNotFoundError:
            return CheckResult(
                control_id=control_id,
                status="ERROR",
                message=f"Command not found: {self._command}",
                level=1,
                source=self._name,
            )
        except Exception as e:
            return CheckResult(
                control_id=control_id,
                status="ERROR",
                message=f"Command failed: {e}",
                level=1,
                source=self._name,
            )


class ScriptCheckAdapter(CheckAdapter):
    """Adapter that runs a shell script for checks.

    The script receives environment variables:
    - CONTROL_ID: The control being checked
    - OWNER: Repository owner
    - REPO: Repository name
    - LOCAL_PATH: Path to local repository
    - CONFIG_*: Any config values as env vars

    Example config:
        ```toml
        [adapters.custom]
        type = "script"
        command = "./scripts/check.sh"
        ```
    """

    def __init__(
        self,
        adapter_name: str,
        script_path: str,
        output_format: str = "json",
        timeout: int = 300,
        control_ids: Optional[List[str]] = None,
    ):
        self._name = adapter_name
        self._script_path = script_path
        self._output_format = output_format
        self._timeout = timeout
        self._control_ids = control_ids or ["*"]

    def name(self) -> str:
        return self._name

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids=set(self._control_ids),
            supports_batch=False,
        )

    def check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> CheckResult:
        """Run script and parse output."""
        import os as _os

        try:
            # Build environment
            env = {
                "CONTROL_ID": control_id,
                "OWNER": owner or "",
                "REPO": repo or "",
                "LOCAL_PATH": local_path or ".",
            }

            # Add config as env vars
            for key, value in config.items():
                env[f"CONFIG_{key.upper()}"] = str(value)

            logger.debug(f"Running script: {self._script_path}")

            result = subprocess.run(
                [self._script_path],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env={**dict(_os.environ), **env},
            )

            if self._output_format == "json":
                try:
                    output = json.loads(result.stdout)
                    return CheckResult(
                        control_id=control_id,
                        status=output.get("status", "ERROR"),
                        message=output.get("message", result.stdout),
                        level=output.get("level", 1),
                        source=self._name,
                    )
                except json.JSONDecodeError:
                    pass

            # Non-JSON or parse failure
            status = "PASS" if result.returncode == 0 else "FAIL"
            return CheckResult(
                control_id=control_id,
                status=status,
                message=result.stdout.strip() or result.stderr.strip(),
                level=1,
                source=self._name,
            )

        except subprocess.TimeoutExpired:
            return CheckResult(
                control_id=control_id,
                status="ERROR",
                message=f"Script timed out after {self._timeout}s",
                level=1,
                source=self._name,
            )
        except FileNotFoundError:
            return CheckResult(
                control_id=control_id,
                status="ERROR",
                message=f"Script not found: {self._script_path}",
                level=1,
                source=self._name,
            )
        except Exception as e:
            return CheckResult(
                control_id=control_id,
                status="ERROR",
                message=f"Script failed: {e}",
                level=1,
                source=self._name,
            )


# =============================================================================
# Adapter Registry
# =============================================================================


@dataclass
class AdapterRegistry:
    """Registry for managing check and remediation adapters.

    Supports:
    - Registration of adapter classes and instances
    - Lazy loading from configuration
    - Entry point discovery for plugins

    Example:
        ```python
        registry = AdapterRegistry()

        # Register a class
        registry.register_check_adapter("builtin", BuiltinCheckAdapter)

        # Register from config
        registry.register_from_config("kusari", {
            "type": "command",
            "command": "kusari",
        })

        # Get adapter instance
        adapter = registry.get_check_adapter("kusari")
        ```
    """

    # Registered adapter classes
    _check_classes: Dict[str, Type[CheckAdapter]] = field(default_factory=dict)
    _remediation_classes: Dict[str, Type[RemediationAdapter]] = field(
        default_factory=dict
    )

    # Instantiated adapters (cached)
    _check_instances: Dict[str, CheckAdapter] = field(default_factory=dict)
    _remediation_instances: Dict[str, RemediationAdapter] = field(default_factory=dict)

    # Config-based adapter definitions
    _adapter_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Allowed module prefixes for dynamic imports (security whitelist)
    ALLOWED_MODULE_PREFIXES: tuple = (
        "darnit.",
        "darnit_baseline.",
        "darnit_plugins.",
        "darnit_testchecks.",
    )

    def register_check_adapter(
        self,
        name: str,
        adapter: Union[Type[CheckAdapter], CheckAdapter],
    ) -> None:
        """Register a check adapter class or instance.

        Args:
            name: Adapter name
            adapter: Adapter class or instance
        """
        if isinstance(adapter, type):
            self._check_classes[name] = adapter
        else:
            self._check_instances[name] = adapter

    def register_remediation_adapter(
        self,
        name: str,
        adapter: Union[Type[RemediationAdapter], RemediationAdapter],
    ) -> None:
        """Register a remediation adapter class or instance.

        Args:
            name: Adapter name
            adapter: Adapter class or instance
        """
        if isinstance(adapter, type):
            self._remediation_classes[name] = adapter
        else:
            self._remediation_instances[name] = adapter

    def register_from_config(
        self,
        name: str,
        config: Dict[str, Any],
    ) -> None:
        """Register an adapter from configuration.

        Args:
            name: Adapter name
            config: Adapter configuration dict
        """
        self._adapter_configs[name] = config

    def get_check_adapter(self, name: str) -> Optional[CheckAdapter]:
        """Get a check adapter by name.

        Resolution order:
        1. Check local cache
        2. Instantiate from registered class
        3. Create from local config
        4. Lookup via PluginRegistry entry points

        Args:
            name: Adapter name

        Returns:
            CheckAdapter instance or None if not found
        """
        # Check cache first
        if name in self._check_instances:
            return self._check_instances[name]

        # Try to instantiate from class
        if name in self._check_classes:
            instance = self._check_classes[name]()
            self._check_instances[name] = instance
            return instance

        # Try to create from config
        if name in self._adapter_configs:
            instance = self._create_check_adapter_from_config(
                name, self._adapter_configs[name]
            )
            if instance:
                self._check_instances[name] = instance
                return instance

        # Fallback: Try PluginRegistry for entry point lookup
        try:
            from .registry import get_plugin_registry

            registry = get_plugin_registry()
            instance = registry.get_check_adapter(name)
            if instance:
                self._check_instances[name] = instance
                return instance
        except ImportError:
            pass  # Registry not available

        return None

    def get_remediation_adapter(self, name: str) -> Optional[RemediationAdapter]:
        """Get a remediation adapter by name.

        Resolution order:
        1. Check local cache
        2. Instantiate from registered class
        3. Lookup via PluginRegistry entry points

        Args:
            name: Adapter name

        Returns:
            RemediationAdapter instance or None if not found
        """
        # Check cache first
        if name in self._remediation_instances:
            return self._remediation_instances[name]

        # Try to instantiate from class
        if name in self._remediation_classes:
            instance = self._remediation_classes[name]()
            self._remediation_instances[name] = instance
            return instance

        # Fallback: Try PluginRegistry for entry point lookup
        try:
            from .registry import get_plugin_registry

            registry = get_plugin_registry()
            instance = registry.get_remediation_adapter(name)
            if instance:
                self._remediation_instances[name] = instance
                return instance
        except ImportError:
            pass  # Registry not available

        return None

    def _create_check_adapter_from_config(
        self,
        name: str,
        config: Dict[str, Any],
    ) -> Optional[CheckAdapter]:
        """Create a check adapter from configuration.

        Args:
            name: Adapter name
            config: Adapter configuration

        Returns:
            CheckAdapter instance or None
        """
        adapter_type = config.get("type", "python")

        if adapter_type == "command":
            return CommandCheckAdapter(
                adapter_name=name,
                command=config["command"],
                output_format=config.get("output_format", "json"),
                timeout=config.get("timeout", 300),
                control_ids=config.get("controls"),
            )

        elif adapter_type == "script":
            return ScriptCheckAdapter(
                adapter_name=name,
                script_path=config["command"],
                output_format=config.get("output_format", "json"),
                timeout=config.get("timeout", 300),
                control_ids=config.get("controls"),
            )

        elif adapter_type == "python":
            return self._load_python_adapter(name, config, CheckAdapter)

        return None

    def _load_python_adapter(
        self,
        name: str,
        config: Dict[str, Any],
        expected_type: type,
    ) -> Optional[Any]:
        """Load a Python adapter from module path.

        Args:
            name: Adapter name
            config: Config with 'module' and optionally 'class' keys
            expected_type: Expected base class

        Returns:
            Adapter instance or None
        """
        module_path = config.get("module")
        class_name = config.get("class", "Adapter")

        if not module_path:
            logger.error(f"Adapter {name} missing 'module' in config")
            return None

        # Security: Validate module path against whitelist to prevent arbitrary code loading
        if not any(module_path.startswith(prefix) for prefix in self.ALLOWED_MODULE_PREFIXES):
            logger.error(
                f"Adapter {name}: module '{module_path}' not in allowed prefixes. "
                f"Allowed: {self.ALLOWED_MODULE_PREFIXES}"
            )
            return None

        try:
            module = importlib.import_module(module_path)
            adapter_class = getattr(module, class_name)

            if not issubclass(adapter_class, expected_type):
                logger.error(
                    f"Adapter {name}: {class_name} is not a {expected_type.__name__}"
                )
                return None

            return adapter_class()

        except ImportError as e:
            logger.error(f"Failed to import adapter {name}: {e}")
            return None
        except AttributeError as e:
            logger.error(f"Adapter {name}: class {class_name} not found: {e}")
            return None

    def list_adapters(self) -> Dict[str, List[str]]:
        """List all registered adapters.

        Returns:
            Dict with 'check' and 'remediation' adapter names
        """
        check_names = set(self._check_classes.keys())
        check_names.update(self._check_instances.keys())
        check_names.update(
            name
            for name, cfg in self._adapter_configs.items()
            if cfg.get("type") in ("command", "script", "python")
        )

        remediation_names = set(self._remediation_classes.keys())
        remediation_names.update(self._remediation_instances.keys())

        return {
            "check": sorted(check_names),
            "remediation": sorted(remediation_names),
        }


# Global registry instance
_global_registry: Optional[AdapterRegistry] = None


def get_adapter_registry() -> AdapterRegistry:
    """Get the global adapter registry.

    Returns:
        Global AdapterRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = AdapterRegistry()
    return _global_registry


def reset_adapter_registry() -> None:
    """Reset the global adapter registry (for testing)."""
    global _global_registry
    _global_registry = None
