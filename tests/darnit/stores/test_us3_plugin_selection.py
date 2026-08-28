"""US3 T035: TOML-selected third-party plugin drives the attestation write.

Feature 033. With the fixture plugin installed AND
``[stores.attestation] backend = "example"`` selected via
``StoresConfig``, an attestation write MUST route through the plugin's
``write()`` (recorded in ``ExampleAttestationStore._writes``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


class TestUS3PluginSelection:
    def test_selected_plugin_receives_the_write(
        self, example_store_plugin_installed, tmp_path: Path
    ):
        from example_store_plugin.backend import ExampleAttestationStore

        from darnit.config.framework_schema import StoreBlock, StoresConfig
        from darnit.stores.selection import resolve_stores
        from darnit_baseline.attestation.generator import (
            generate_attestation_from_results,
        )

        # Clear any residual state from prior tests.
        ExampleAttestationStore._writes.clear()

        config = StoresConfig(attestation=StoreBlock(backend="example"))
        bundle = resolve_stores(config, repo_path=tmp_path)

        audit_result = MagicMock()
        audit_result.commit = "cafefeed"
        audit_result.owner = "us3"
        audit_result.repo = "plugin-repo"
        audit_result.ref = "main"
        audit_result.level = 1
        audit_result.all_results = []
        audit_result.project_config = None
        audit_result.local_path = str(tmp_path)

        generate_attestation_from_results(
            audit_result=audit_result,
            sign=False,
            attestation_store=bundle.attestation,
        )

        assert len(ExampleAttestationStore._writes) == 1
        bundle_id, _, content_type = ExampleAttestationStore._writes[0]
        assert bundle_id == "plugin-repo-baseline-attestation"
        assert content_type == "application/vnd.in-toto+json"
