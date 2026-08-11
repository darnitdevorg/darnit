"""Backend extensibility tests (feature 029 T020).

Covers SC-007: a new backend can be added via constructor injection
(runner's `backends=` parameter) without touching any shared file.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.darnit.parity.tier2.backends.base import (
    SkillInvocationBackend,
    SkillInvocationResult,
)
from tests.darnit.parity.tier2.backends.noop import NoopBackend
from tests.darnit.parity.tier2.run import main


class TestSC007ExtensibilityViaConstructorInjection:
    def test_noop_backend_invoked_via_injected_registry(
        self,
        tmp_path: Path,
    ) -> None:
        """SC-007: `run.main()` with a `backends=` dict override picks up
        NoopBackend and invokes it. No edit to BACKEND_REGISTRY required."""
        artifact_dir = tmp_path / "artifacts"

        # NoopBackend requires no env; a run should complete cleanly.
        rc = main(
            argv=[
                "--backend",
                "noop",
                "--model",
                "noop-model",
                "--fixture-glob",
                "all_pass_repo",
                "--artifact-dir",
                str(artifact_dir),
                "--max-turns",
                "1",
            ],
            backends={"noop": NoopBackend},
        )

        # NoopBackend's canned response is unparseable by the shared parser
        # (only "Passed: 0\nFailed: 0" -- no per-control claims), so we
        # expect exit 2 (unparseable), NOT exit 3 (setup) or exit 1
        # (disagree). This proves the NoopBackend WAS invoked -- the runner
        # got past the check_env fail-fast and ran the mock's canned
        # response through the parser.
        assert rc == 2, f"expected exit 2 (unparseable), got {rc}"

        # Artifact bundle written to the fixture path.
        fixture_artifacts = artifact_dir / "all_pass_repo"
        assert fixture_artifacts.exists()
        # NoopBackend's provider filename prefix defaults to 'noop'.
        assert (fixture_artifacts / "noop_final_message.md").exists()
        metadata = json.loads((fixture_artifacts / "metadata.json").read_text())
        assert metadata.get("backend") == "noop"

    def test_ad_hoc_inline_backend_registered_and_invoked(
        self,
        tmp_path: Path,
    ) -> None:
        """SC-007 stronger form: define a backend inline (no module),
        inject it, and confirm the runner picks it up."""

        class _InlineTestBackend:
            """Inline backend defined at test-collection time. If SC-007
            holds, no edit to run.py, diff.py, or any shared file is needed
            to make this work."""

            name = "inline_test"

            @classmethod
            def check_env(cls) -> None:
                return None

            async def invoke(
                self,
                fixture_dir: Path,
                model: str,
                max_turns: int,
            ) -> SkillInvocationResult:
                return SkillInvocationResult(
                    final_message=("# Inline test backend\n\nPassed: 0\nFailed: 0\n\n- **OSPS-DO-01.01**: PASS\n"),
                    model=model,
                    turn_count=1,
                    metadata={"backend": "inline_test"},
                )

        assert isinstance(_InlineTestBackend(), SkillInvocationBackend)

        artifact_dir = tmp_path / "artifacts"
        rc = main(
            argv=[
                "--backend",
                "inline_test",
                "--model",
                "inline-model",
                "--fixture-glob",
                "all_pass_repo",
                "--artifact-dir",
                str(artifact_dir),
                "--max-turns",
                "1",
            ],
            backends={"inline_test": _InlineTestBackend},
        )

        # Whatever the diff outcome (likely disagree because the inline
        # backend's canned OSPS-DO-01.01 status is PASS but the audit's
        # actual OSPS-DO-01.01 might be different), the runner DID invoke
        # the inline backend. Return codes 0, 1, or 2 all indicate the
        # backend was reached; 3 (setup) would mean the injection failed.
        assert rc in (0, 1, 2), (
            f"expected 0/1/2 (backend invoked); got {rc} which suggests the injected backend was not picked up"
        )

    def test_unknown_backend_name_returns_setup_error(
        self,
        tmp_path: Path,
    ) -> None:
        """Guardrail: `--backend <unknown>` fails fast with exit 3."""
        rc = main(
            argv=[
                "--backend",
                "nonexistent",
                "--model",
                "x",
                "--fixture-glob",
                "all_pass_repo",
                "--artifact-dir",
                str(tmp_path / "artifacts"),
            ],
        )
        assert rc == 3
