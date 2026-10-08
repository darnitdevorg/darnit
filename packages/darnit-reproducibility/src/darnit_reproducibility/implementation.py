"""Scientific reproducibility plugin implementation for darnit."""

from pathlib import Path

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

    def get_framework_config_path(self) -> Path | None:
        from importlib.resources import files

        resource = files(__package__) / "reproducibility.toml"
        path = Path(str(resource))
        if not path.is_file():
            raise FileNotFoundError(
                f"reproducibility.toml not found in installed darnit_reproducibility "
                f"package at {path}. This indicates a broken build; check the "
                f"wheel's force-include configuration."
            )
        return path

    def register_sieve_handlers(self) -> None:
        """Register the reproducibility-specific check handlers."""
        from darnit.sieve.handler_registry import get_sieve_handler_registry

        registry = get_sieve_handler_registry()
        registry.set_plugin_context(self.name)

        # Feature 044 (FR-010): these five decide from text and file-presence
        # signals, which can show a requirement is unmet but not that it is
        # met. They register {fail}: a PASS they report is evidence for the
        # control's later steps, and concludes only with a corpus-backed
        # promotion on the step (framework-design 3.0.1). The ceiling is
        # part of this registration, not the package name, so it survives
        # a rename.
        registry.register(
            "repro_deps_pinned",
            phase="deterministic",
            handler_fn=handlers.repro_deps_pinned_handler,
            description="Check for lock files indicating pinned dependencies",
            ceiling={"fail"},
            settings=frozenset(),
        )
        registry.register(
            "repro_build_env_declared",
            phase="deterministic",
            handler_fn=handlers.repro_build_env_declared_handler,
            description="Check for Dockerfile, Nix flake, or similar env declaration",
            ceiling={"fail"},
            settings=frozenset(),
        )
        registry.register(
            "repro_hermetic_build",
            phase="pattern",
            handler_fn=handlers.repro_hermetic_build_handler,
            description="Scan CI workflows for live network fetches during build",
            ceiling={"fail"},
            settings=frozenset(),
        )
        # #553: a verified runtime trace can show the build accessed the
        # network, but an empty or absent network log is also what a monitor
        # that does not trace sockets records, so it cannot show the opposite.
        # {fail} until monitor types are allowlisted against real attestations.
        registry.register(
            "repro_witness_attestation",
            phase="deterministic",
            handler_fn=handlers.repro_witness_attestation_handler,
            description=(
                "Verify the audited commit's Witness / in-toto runtime-trace attestations "
                "and fail on recorded network access"
            ),
            ceiling={"fail"},
            settings={"verify_witness_attestations"},
        )
        registry.register(
            "repro_provenance_exists",
            phase="pattern",
            handler_fn=handlers.repro_provenance_exists_handler,
            description="Check CI workflows for sigstore/SLSA provenance steps",
            ceiling={"fail"},
            settings=frozenset(),
        )
        registry.register(
            "repro_bit_for_bit",
            phase="pattern",
            handler_fn=handlers.repro_bit_for_bit_handler,
            description="Check for SOURCE_DATE_EPOCH and reprotest signals",
            ceiling={"fail"},
            settings=frozenset(),
        )

        registry.set_plugin_context(None)
