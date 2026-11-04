"""Tests for the raw-findings.json renderer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from darnit_baseline.threat_model.discovery_models import (
    CandidateFinding,
    CodeSnippet,
    DataStoreKind,
    DiscoveredDataStore,
    DiscoveredEntryPoint,
    DiscoveryResult,
    EntryPointKind,
    FileScanStats,
    FindingSource,
    Location,
    MitigationEntry,
    MitigationStatus,
)
from darnit_baseline.threat_model.models import StrideCategory
from darnit_baseline.threat_model.renderers.raw_json import render_raw_json


def _make_finding(
    query_id: str = "python.sink.sql_injection",
    severity: int = 8,
    confidence: float = 0.9,
    title: str = "SQL Injection in Query",
    category: StrideCategory = StrideCategory.TAMPERING,
    file: str = "src/database.py",
    line: int = 42,
    fingerprint: str = "sha256:abcd1234ef567890",
) -> CandidateFinding:
    return CandidateFinding(
        category=category,
        title=title,
        source=FindingSource.TREE_SITTER_STRUCTURAL,
        primary_location=Location(file=file, line=line, column=1, end_line=line + 1, end_column=30),
        related_assets=(),
        code_snippet=CodeSnippet(
            lines=("cursor.execute(query)", "return cursor.fetchall()"),
            start_line=line,
            marker_line=line,
        ),
        severity=severity,
        confidence=confidence,
        rationale="Raw parameter concatenated into SQL query string",
        query_id=query_id,
        fingerprint=fingerprint,
    )


class TestRawJsonMetadata:
    """Metadata serialization tests in render_raw_json."""

    def test_empty_discovery_result_defaults(self) -> None:
        result = DiscoveryResult()
        output = render_raw_json(result, [], {})
        data = json.loads(output)

        metadata = data["metadata"]
        assert isinstance(metadata["repository"], str)
        assert metadata["scan_date"] == datetime.now(tz=UTC).date().isoformat()
        assert metadata["languages"] == []
        assert metadata["files_scanned"] == 0
        assert metadata["opengrep_available"] is False

        assert data["findings"] == []
        assert data["entry_points"] == []
        assert data["data_stores"] == []
        assert data["file_scan_stats"] is None

    def test_metadata_languages_sorted(self) -> None:
        stats = FileScanStats(
            total_files_seen=20,
            excluded_dir_count=5,
            unsupported_file_count=2,
            in_scope_files=18,
            by_language={"python": 12, "go": 4, "rust": 2},
            shallow_mode=False,
            shallow_threshold=500,
        )
        result = DiscoveryResult(file_scan_stats=stats)
        data = json.loads(render_raw_json(result, [], {}))

        assert data["metadata"]["languages"] == ["go", "python", "rust"]
        assert data["metadata"]["files_scanned"] == 18

    def test_metadata_opengrep_available_flag(self) -> None:
        result = DiscoveryResult(opengrep_available=True)
        data = json.loads(render_raw_json(result, [], {}))
        assert data["metadata"]["opengrep_available"] is True

    def test_repo_display_name_derived(self, tmp_path: Any) -> None:
        project_dir = tmp_path / "custom-service"
        project_dir.mkdir()
        result = DiscoveryResult()
        data = json.loads(render_raw_json(result, [], {}, repo_path=str(project_dir)))
        assert data["metadata"]["repository"] == "custom-service"


class TestRawJsonFindings:
    """Candidate findings and sidecar mitigation serialization tests."""

    def test_finding_fields_serialization(self) -> None:
        finding = _make_finding()
        data = json.loads(render_raw_json(DiscoveryResult(), [finding], {}))

        assert len(data["findings"]) == 1
        item = data["findings"][0]
        assert item["query_id"] == "python.sink.sql_injection"
        assert item["category"] == "tampering"
        assert item["title"] == "SQL Injection in Query"
        assert item["severity"] == 8
        assert item["confidence"] == 0.9
        assert item["file"] == "src/database.py"
        assert item["line"] == 42
        assert item["end_line"] == 43
        assert item["snippet"] == "cursor.execute(query)\nreturn cursor.fetchall()"
        assert item["fingerprint"] == "sha256:abcd1234ef567890"
        assert "mitigation" not in item

    def test_finding_with_mitigation_entry(self) -> None:
        finding = _make_finding(fingerprint="sha256:target1")
        mitigation = MitigationEntry(
            fingerprint="sha256:target1",
            status=MitigationStatus.MITIGATED,
            note="Escaped with parameterized driver query",
            reviewer="security-lead",
            reviewed_at="2026-11-01T15:30:00Z",
            stale=False,
        )
        sidecar_matches = {"sha256:target1": mitigation}

        data = json.loads(render_raw_json(DiscoveryResult(), [finding], sidecar_matches))
        item = data["findings"][0]

        assert "mitigation" in item
        assert item["mitigation"] == {
            "status": "mitigated",
            "note": "Escaped with parameterized driver query",
            "reviewer": "security-lead",
            "reviewed_at": "2026-11-01T15:30:00Z",
            "stale": False,
        }

    def test_finding_with_plain_string_mitigation_status(self) -> None:
        @dataclass
        class MockMitigation:
            status: str
            note: str = "Verified false positive"
            reviewer: str = "auditor"
            reviewed_at: str = "2026-10-30T10:00:00Z"
            stale: bool = True

        finding = _make_finding(fingerprint="sha256:strstatus")
        mock = MockMitigation(status="accepted")
        data = json.loads(render_raw_json(DiscoveryResult(), [finding], {"sha256:strstatus": mock}))

        item = data["findings"][0]
        assert item["mitigation"]["status"] == "accepted"
        assert item["mitigation"]["stale"] is True

    def test_unmatched_findings_omit_mitigation(self) -> None:
        matched = _make_finding(fingerprint="sha256:matched")
        unmatched = _make_finding(fingerprint="sha256:unmatched", line=80)
        mitigation = MitigationEntry(
            fingerprint="sha256:matched",
            status=MitigationStatus.FALSE_POSITIVE,
            note="Internal utility script only",
            reviewer="dev",
            reviewed_at="2026-11-02T10:00:00Z",
        )
        sidecar_matches = {"sha256:matched": mitigation}

        data = json.loads(render_raw_json(DiscoveryResult(), [matched, unmatched], sidecar_matches))
        assert "mitigation" in data["findings"][0]
        assert "mitigation" not in data["findings"][1]

    def test_empty_fingerprint_never_matches_sidecar(self) -> None:
        finding = _make_finding(fingerprint="")
        mitigation = MitigationEntry(
            fingerprint="",
            status=MitigationStatus.UNMITIGATED,
            note="Empty fingerprint fallback",
        )
        sidecar_matches = {"": mitigation}

        data = json.loads(render_raw_json(DiscoveryResult(), [finding], sidecar_matches))
        assert "mitigation" not in data["findings"][0]


class TestRawJsonAssets:
    """Entry point and data store serialization tests."""

    def test_entry_points_serialization(self) -> None:
        ep = DiscoveredEntryPoint(
            kind=EntryPointKind.HTTP_ROUTE,
            name="authenticate_user",
            framework="fastapi",
            http_method="POST",
            route_path="/auth/login",
            location=Location(file="src/routes/auth.py", line=15, column=1, end_line=25, end_column=10),
            has_auth_decorator=True,
            language="python",
            source_query="python.entry_point.fastapi_route",
        )
        result = DiscoveryResult(entry_points=[ep])
        data = json.loads(render_raw_json(result, [], {}))

        assert len(data["entry_points"]) == 1
        item = data["entry_points"][0]
        assert item == {
            "kind": "http_route",
            "framework": "fastapi",
            "http_method": "POST",
            "route_path": "/auth/login",
            "name": "authenticate_user",
            "file": "src/routes/auth.py",
            "line": 15,
            "has_auth_decorator": True,
        }

    def test_data_stores_serialization(self) -> None:
        ds = DiscoveredDataStore(
            technology="Redis",
            kind=DataStoreKind.KEY_VALUE,
            import_evidence="import redis",
            dependency_manifest_evidence="redis-py",
            location=Location(file="src/cache.py", line=5, column=1, end_line=5, end_column=20),
            language="python",
            source_query="python.data_store.redis",
        )
        result = DiscoveryResult(data_stores=[ds])
        data = json.loads(render_raw_json(result, [], {}))

        assert len(data["data_stores"]) == 1
        item = data["data_stores"][0]
        assert item == {
            "technology": "Redis",
            "kind": "key_value",
            "import_evidence": "import redis",
            "file": "src/cache.py",
            "line": 5,
        }


class TestRawJsonFileScanStats:
    """File scan stats serialization tests."""

    def test_populated_file_scan_stats(self) -> None:
        stats = FileScanStats(
            total_files_seen=105,
            excluded_dir_count=15,
            unsupported_file_count=35,
            in_scope_files=70,
            by_language={"python": 50, "typescript": 20},
            shallow_mode=True,
            shallow_threshold=250,
        )
        result = DiscoveryResult(file_scan_stats=stats)
        data = json.loads(render_raw_json(result, [], {}))

        assert data["file_scan_stats"] == {
            "total_files_seen": 105,
            "excluded_dir_count": 15,
            "unsupported_file_count": 35,
            "in_scope_files": 70,
            "by_language": {"python": 50, "typescript": 20},
            "shallow_mode": True,
            "shallow_threshold": 250,
        }


class TestRawJsonFormatting:
    """Formatting and JSON syntax tests."""

    def test_valid_json_and_two_space_indentation(self) -> None:
        raw = render_raw_json(DiscoveryResult(), [], {})
        # Must be valid json
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
        # Must use two-space indentation
        assert '\n  "metadata": {' in raw
