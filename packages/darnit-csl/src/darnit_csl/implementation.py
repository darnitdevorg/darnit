"""CommunitySpecImplementation — CSL 1.0 compliance, defined in TOML.

This is a TOML-first ``ComplianceImplementation`` (see the project's
TOML-First Architecture principle): every control, template, and context
prompt lives in ``community-spec.toml``. No Python control logic is needed —
the framework loads the TOML via :meth:`get_framework_config_path`.
"""

from __future__ import annotations

from pathlib import Path


class CommunitySpecImplementation:
    """Community Specification License 1.0 compliance implementation."""

    # ---- Identity -----------------------------------------------------------

    @property
    def name(self) -> str:
        """Slug — must match the key in pyproject.toml's
        [project.entry-points."darnit.implementations"] table."""
        return "community-spec"

    @property
    def display_name(self) -> str:
        return "Community Specification License (CSL 1.0)"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "CSL 1.0"

    # ---- Protocol methods ---------------------------------------------------

    def get_framework_config_path(self) -> Path | None:
        """Absolute path to the bundled TOML config (the source of truth)."""
        from importlib.resources import files

        resource = files(__package__) / "community-spec.toml"
        path = Path(str(resource))
        if not path.is_file():
            raise FileNotFoundError(
                f"community-spec.toml not found in installed darnit_csl package "
                f"at {path}. This indicates a broken build; check the wheel's "
                f"force-include configuration."
            )
        return path

    def register_sieve_handlers(self) -> None:
        """Register the ``csl_llm_if_present`` step type (again, after a registry reset)."""
        from .handlers import register_sieve_handlers

        register_sieve_handlers()
