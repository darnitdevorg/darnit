"""Scientific reproducibility plugin implementation for darnit."""

from pathlib import Path
from typing import Any

from darnit.core.plugin import ControlSpec
from darnit_reproducibility import handlers


class ReproducibilityImplementation:
    """Scientific reproducibility checks plugin.

    Provides checks for dependency pinning, build environment
    declaration, hermetic builds, provenance, and bit-for-bit
    reproducibility. Follows the darnit plugin protocol.
    """

    @property
    def name(self) -> str:
        return "reproducibility"

    @property
    def display_name(self) -> str:
        return "Scientific Reproducibility Checks"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "repro v0.1"

    def get_all_controls(self) -> list[ControlSpec]:
        controls = []
        for level in [1, 2, 3]:
            controls.extend(self.get_controls_by_level(level))
        return controls

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        all_controls = [
            ControlSpec(
                control_id="RE-01.01",
                name="DependenciesPinned",
                description="Dependencies are pinned to exact versions with checksums",
                level=1,
                domain="RE",
                metadata={},
            ),
            ControlSpec(
                control_id="RE-01.02",
                name="BuildEnvDeclared",
                description="Build environment is explicitly declared",
                level=1,
                domain="RE",
                metadata={},
            ),
            ControlSpec(
                control_id="RE-02.01",
                name="HermeticBuild",
                description="Build does not fetch dependencies at build time",
                level=2,
                domain="RE",
                metadata={},
            ),
            ControlSpec(
                control_id="RE-02.02",
                name="ProvenanceExists",
                description="Build produces a signed provenance attestation",
                level=2,
                domain="RE",
                metadata={},
            ),
            ControlSpec(
                control_id="RE-03.01",
                name="BitForBitReproducible",
                description="Build output is identical across independent builds",
                level=3,
                domain="RE",
                metadata={},
            ),
        ]
        return [c for c in all_controls if c.level == level]

    def get_rules_catalog(self) -> dict[str, Any]:
        return {}

    def get_remediation_registry(self) -> dict[str, Any]:
        # Intentionally empty: TOML is the source of truth for remediation.
        # RemediationExecutor reads FrameworkConfig.controls[id].remediation directly.
        return {}

    def get_framework_config_path(self) -> Path | None:
        return Path(__file__).parent.parent.parent / "reproducibility.toml"

    def register_controls(self) -> None:
        pass

    def register_sieve_handlers(self) -> None:
        """Register the reproducibility-specific check handlers."""
        from darnit.sieve.handler_registry import get_sieve_handler_registry

        registry = get_sieve_handler_registry()
        registry.set_plugin_context(self.name)

        registry.register(
            "repro_deps_pinned",
            phase="deterministic",
            handler_fn=handlers.repro_deps_pinned_handler,
            description="Check for lock files indicating pinned dependencies",
        )
        registry.register(
            "repro_build_env_declared",
            phase="deterministic",
            handler_fn=handlers.repro_build_env_declared_handler,
            description="Check for Dockerfile, Nix flake, or similar env declaration",
        )
        registry.register(
            "repro_hermetic_build",
            phase="pattern",
            handler_fn=handlers.repro_hermetic_build_handler,
            description="Scan CI workflows for live network fetches during build",
        )
        registry.register(
            "repro_provenance_exists",
            phase="pattern",
            handler_fn=handlers.repro_provenance_exists_handler,
            description="Check CI workflows for sigstore/SLSA provenance steps",
        )
        registry.register(
            "repro_bit_for_bit",
            phase="pattern",
            handler_fn=handlers.repro_bit_for_bit_handler,
            description="Check for SOURCE_DATE_EPOCH and reprotest signals",
        )

        registry.set_plugin_context(None)
