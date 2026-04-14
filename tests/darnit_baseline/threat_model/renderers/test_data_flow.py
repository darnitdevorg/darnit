"""Tests for the data-flow.md renderer (T018)."""

from __future__ import annotations

from darnit_baseline.threat_model.discovery_models import (
    DataStoreKind,
    DiscoveredDataStore,
    DiscoveredEntryPoint,
    DiscoveryResult,
    EntryPointKind,
    FileScanStats,
    Location,
)
from darnit_baseline.threat_model.renderers.common import GeneratorOptions
from darnit_baseline.threat_model.renderers.data_flow import render_data_flow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_empty_result = DiscoveryResult()

_result_with_assets = DiscoveryResult(
    entry_points=[
        DiscoveredEntryPoint(
            kind=EntryPointKind.HTTP_ROUTE,
            name="get_users",
            framework="fastapi",
            http_method="GET",
            route_path="/api/users",
            location=Location(file="src/api.py", line=10, column=1, end_line=10, end_column=30),
            has_auth_decorator=False,
            language="python",
            source_query="python.entry_point.fastapi_route",
        ),
    ],
    data_stores=[
        DiscoveredDataStore(
            technology="PostgreSQL",
            kind=DataStoreKind.RELATIONAL_DB,
            import_evidence="import psycopg2",
            dependency_manifest_evidence=None,
            location=Location(file="src/db.py", line=5, column=1, end_line=5, end_column=20),
            language="python",
            source_query="python.data_store.psycopg2",
        ),
    ],
    file_scan_stats=FileScanStats(
        total_files_seen=10,
        excluded_dir_count=2,
        unsupported_file_count=5,
        in_scope_files=5,
        by_language={"python": 5},
        shallow_mode=False,
        shallow_threshold=500,
    ),
)


# ---------------------------------------------------------------------------
# T018 tests
# ---------------------------------------------------------------------------


class TestT018DataFlow:
    """Data-flow.md rendering (T018)."""

    def test_has_title(self) -> None:
        output = render_data_flow(_result_with_assets, GeneratorOptions())
        assert "# Data Flow Analysis" in output

    def test_contains_mermaid_block(self) -> None:
        output = render_data_flow(_result_with_assets, GeneratorOptions())
        assert "```mermaid" in output

    def test_asset_inventory_tables(self) -> None:
        output = render_data_flow(_result_with_assets, GeneratorOptions())
        assert "### Entry Points" in output
        assert "### Data Stores" in output

    def test_attack_chains_section(self) -> None:
        output = render_data_flow(_result_with_assets, GeneratorOptions())
        assert "## Attack Chains" in output

    def test_empty_result(self) -> None:
        output = render_data_flow(_empty_result, GeneratorOptions())
        # Should still be valid output with the title
        assert "# Data Flow Analysis" in output
        # No mermaid diagram for an empty result
        assert "```mermaid" not in output
        # Should indicate no assets or empty state
        assert (
            "No assets discovered" in output
            or "No HTTP route handlers" in output
            or "No data stores detected" in output
        )
