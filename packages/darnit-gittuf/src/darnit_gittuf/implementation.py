"""Gittuf plugin implementation for darnit."""

from pathlib import Path

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

    def get_framework_config_path(self) -> Path | None:
        from importlib.resources import files

        resource = files(__package__) / "gittuf.toml"
        path = Path(str(resource))
        if not path.is_file():
            raise FileNotFoundError(
                f"gittuf.toml not found in installed darnit_gittuf package at "
                f"{path}. This indicates a broken build; check the wheel's "
                f"force-include configuration."
            )
        return path

    def register_handlers(self) -> None:
        """Register the Gittuf-specific check handlers."""
        from darnit.sieve.handler_registry import get_sieve_handler_registry

        from . import handlers

        registry = get_sieve_handler_registry()
        registry.set_plugin_context(self.name)

        # RFC-0001 Stage 1: both handlers observe ground truth
        # (gittuf verify-ref and commit signature presence). They register
        # the {pass, fail} ceiling so a passing result concludes the control.
        registry.register(
            "gittuf_verify_policy",
            phase="deterministic",
            handler_fn=handlers.gittuf_verify_policy_handler,
            description="Run gittuf verify-ref HEAD",
            ceiling={"pass", "fail"},
            settings=frozenset(),
        )
        registry.register(
            "gittuf_commits_signed",
            phase="deterministic",
            handler_fn=handlers.gittuf_commits_signed_handler,
            description="Check last 5 commits for cryptographic signatures",
            ceiling={"pass", "fail"},
            settings=frozenset(),
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
