"""Gittuf plugin implementation for darnit."""

from pathlib import Path
from typing import Any

from darnit.core.plugin import ControlSpec
from darnit_gittuf import handlers


class GittufImplementation:
    """Gittuf policy checks plugin.

    Provides checks for Gittuf initialization, policy validity,
    and commit signing. Integrates via the darnit plugin protocol.
    """

    @property
    def name(self) -> str:
        return "gittuf"

    @property
    def display_name(self) -> str:
        return "Gittuf Policy Checks"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "gittuf v0.1"

    def get_all_controls(self) -> list[ControlSpec]:
        controls = []
        for level in [1, 2]:
            controls.extend(self.get_controls_by_level(level))
        return controls

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        all_controls = [
            ControlSpec(
                control_id="GT-01.01",
                name="GittufInitialized",
                description="Repository has Gittuf initialized",
                level=1,
                domain="GT",
                metadata={},
            ),
            ControlSpec(
                control_id="GT-01.02",
                name="GittufPolicyValid",
                description="Gittuf policy passes verification",
                level=1,
                domain="GT",
                metadata={},
            ),
            ControlSpec(
                control_id="GT-02.01",
                name="CommitsSigned",
                description="Recent commits are cryptographically signed",
                level=2,
                domain="GT",
                metadata={},
            ),
        ]
        return [c for c in all_controls if c.level == level]

    def get_rules_catalog(self) -> dict[str, Any]:
        return {}

    def get_remediation_registry(self) -> dict[str, Any]:
        return {}

    def get_framework_config_path(self) -> Path | None:
        return Path(__file__).parent.parent.parent / "gittuf.toml"

    def register_controls(self) -> None:
        pass

    def register_sieve_handlers(self) -> None:
        """Register the Gittuf-specific check handlers."""
        from darnit.sieve.handler_registry import get_sieve_handler_registry
        from . import handlers

        registry = get_sieve_handler_registry()
        registry.set_plugin_context(self.name)

        registry.register(
            "gittuf_verify_policy",
            phase="deterministic",
            handler_fn=handlers.gittuf_verify_policy_handler,
            description="Run gittuf verify-ref HEAD",
        )
        registry.register(
            "gittuf_commits_signed",
            phase="deterministic",
            handler_fn=handlers.gittuf_commits_signed_handler,
            description="Check last 5 commits for cryptographic signatures",
        )

        registry.set_plugin_context(None)

    # These are the three action handlers from Phase 2
    def get_check_handlers(self) -> dict:
        return {
            "gittuf_verify_policy": handlers.gittuf_verify_policy_handler,
            "gittuf_commits_signed": handlers.gittuf_commits_signed_handler,
        }

    def get_context_handlers(self) -> dict:
        return {}

    def get_remediation_handlers(self) -> dict:
        return {}