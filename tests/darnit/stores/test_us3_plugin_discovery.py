"""US3 T034: entry-point discovery against a real installed distribution.

Feature 033 FR-005. Confirms the discovery mechanism (not just the
monkeypatched-EP path from Phase 2) finds the fixture plugin's
``ExampleAttestationStore`` under ``darnit.stores.attestation``.
"""

from __future__ import annotations

from darnit.stores.discovery import discover_stores


class TestUS3PluginDiscovery:
    def test_fixture_plugin_discovered_via_real_entry_point(
        self, example_store_plugin_installed
    ):
        result = discover_stores("darnit.stores.attestation")
        assert "example" in result, (
            "Fixture plugin's entry point was not picked up. "
            f"Registered names: {list(result.keys())}"
        )
        cls = result["example"]
        assert cls.__name__ == "ExampleAttestationStore"
