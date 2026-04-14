"""Tests for the mitigation sidecar module."""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit_baseline.threat_model.discovery_models import (
    CandidateFinding,
    CodeSnippet,
    FindingSource,
    Location,
    MitigationEntry,
    MitigationSidecar,
    MitigationStatus,
)
from darnit_baseline.threat_model.models import StrideCategory
from darnit_baseline.threat_model.sidecar import (
    compute_fingerprint,
    detect_stale,
    load_sidecar,
    match_findings,
    save_sidecar,
)


def _make_finding(
    query_id: str = "python.sink.dangerous_attr",
    file: str = "src/app.py",
    line: int = 10,
    snippet_lines: tuple[str, ...] = ("x = dangerous_call(input)",),
) -> CandidateFinding:
    return CandidateFinding(
        category=StrideCategory.TAMPERING,
        title="Test finding",
        source=FindingSource.TREE_SITTER_STRUCTURAL,
        primary_location=Location(file=file, line=line, column=1, end_line=line, end_column=20),
        related_assets=(),
        code_snippet=CodeSnippet(lines=snippet_lines, start_line=line, marker_line=line),
        severity=5,
        confidence=0.8,
        rationale="test",
        query_id=query_id,
    )


class TestComputeFingerprint:
    def test_deterministic(self, tmp_path: Path) -> None:
        f = _make_finding()
        fp1 = compute_fingerprint(f, tmp_path)
        fp2 = compute_fingerprint(f, tmp_path)
        assert fp1 == fp2

    def test_starts_with_sha256_prefix(self, tmp_path: Path) -> None:
        fp = compute_fingerprint(_make_finding(), tmp_path)
        assert fp.startswith("sha256:")
        assert len(fp) == len("sha256:") + 16

    def test_changes_with_file_path(self, tmp_path: Path) -> None:
        f1 = _make_finding(file="src/a.py")
        f2 = _make_finding(file="src/b.py")
        assert compute_fingerprint(f1, tmp_path) != compute_fingerprint(f2, tmp_path)

    def test_changes_with_snippet(self, tmp_path: Path) -> None:
        f1 = _make_finding(snippet_lines=("x = foo()",))
        f2 = _make_finding(snippet_lines=("x = bar()",))
        assert compute_fingerprint(f1, tmp_path) != compute_fingerprint(f2, tmp_path)

    def test_stable_across_whitespace_reformatting(self, tmp_path: Path) -> None:
        f1 = _make_finding(snippet_lines=("  x = foo()",))
        f2 = _make_finding(snippet_lines=("x = foo()",))
        assert compute_fingerprint(f1, tmp_path) == compute_fingerprint(f2, tmp_path)

    def test_changes_with_query_id(self, tmp_path: Path) -> None:
        f1 = _make_finding(query_id="python.sink.a")
        f2 = _make_finding(query_id="python.sink.b")
        assert compute_fingerprint(f1, tmp_path) != compute_fingerprint(f2, tmp_path)


class TestLoadSidecar:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert load_sidecar(tmp_path) is None

    def test_loads_valid_yaml(self, tmp_path: Path) -> None:
        sidecar_path = tmp_path / ".project" / "threatmodel" / "mitigations.yaml"
        sidecar_path.parent.mkdir(parents=True)
        sidecar_path.write_text(
            'version: "1"\n'
            "entries:\n"
            '  - fingerprint: "sha256:abcdef0123456789"\n'
            "    status: mitigated\n"
            '    note: "Input validated upstream"\n'
            '    reviewer: "@alice"\n'
        )
        result = load_sidecar(tmp_path)
        assert result is not None
        assert len(result.entries) == 1
        assert result.entries[0].status == MitigationStatus.MITIGATED
        assert result.entries[0].note == "Input validated upstream"

    def test_raises_on_malformed_yaml(self, tmp_path: Path) -> None:
        sidecar_path = tmp_path / ".project" / "threatmodel" / "mitigations.yaml"
        sidecar_path.parent.mkdir(parents=True)
        sidecar_path.write_text("{{{{not valid yaml")
        with pytest.raises(ValueError, match="Malformed sidecar"):
            load_sidecar(tmp_path)

    def test_raises_on_wrong_version(self, tmp_path: Path) -> None:
        sidecar_path = tmp_path / ".project" / "threatmodel" / "mitigations.yaml"
        sidecar_path.parent.mkdir(parents=True)
        sidecar_path.write_text('version: "2"\nentries: []\n')
        with pytest.raises(ValueError, match="Unsupported sidecar version"):
            load_sidecar(tmp_path)

    def test_raises_on_duplicate_fingerprint(self, tmp_path: Path) -> None:
        sidecar_path = tmp_path / ".project" / "threatmodel" / "mitigations.yaml"
        sidecar_path.parent.mkdir(parents=True)
        sidecar_path.write_text(
            'version: "1"\n'
            "entries:\n"
            '  - fingerprint: "sha256:abcdef0123456789"\n'
            "    status: mitigated\n"
            '  - fingerprint: "sha256:abcdef0123456789"\n'
            "    status: accepted\n"
        )
        with pytest.raises(ValueError, match="Duplicate fingerprint"):
            load_sidecar(tmp_path)

    def test_raises_on_invalid_status(self, tmp_path: Path) -> None:
        sidecar_path = tmp_path / ".project" / "threatmodel" / "mitigations.yaml"
        sidecar_path.parent.mkdir(parents=True)
        sidecar_path.write_text(
            'version: "1"\nentries:\n  - fingerprint: "sha256:abcdef0123456789"\n    status: invalid_status\n'
        )
        with pytest.raises(ValueError, match="Invalid or missing status"):
            load_sidecar(tmp_path)


class TestSaveSidecar:
    def test_round_trip(self, tmp_path: Path) -> None:
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(
                    fingerprint="sha256:abcdef0123456789",
                    status=MitigationStatus.MITIGATED,
                    note="Fixed upstream",
                    reviewer="@bob",
                    reviewed_at="2026-04-13",
                    query_id="python.sink.dangerous_attr",
                    file_hint="src/app.py",
                ),
            ]
        )
        save_sidecar(tmp_path, sidecar)
        loaded = load_sidecar(tmp_path)
        assert loaded is not None
        assert len(loaded.entries) == 1
        assert loaded.entries[0].fingerprint == "sha256:abcdef0123456789"
        assert loaded.entries[0].status == MitigationStatus.MITIGATED
        assert loaded.entries[0].note == "Fixed upstream"

    def test_preserves_entry_ordering(self, tmp_path: Path) -> None:
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(fingerprint="sha256:cccc", status=MitigationStatus.ACCEPTED),
                MitigationEntry(fingerprint="sha256:aaaa", status=MitigationStatus.MITIGATED),
                MitigationEntry(fingerprint="sha256:bbbb", status=MitigationStatus.FALSE_POSITIVE),
            ]
        )
        save_sidecar(tmp_path, sidecar)
        loaded = load_sidecar(tmp_path)
        assert loaded is not None
        fps = [e.fingerprint for e in loaded.entries]
        assert fps == ["sha256:cccc", "sha256:aaaa", "sha256:bbbb"]

    def test_includes_header_comment(self, tmp_path: Path) -> None:
        save_sidecar(tmp_path, MitigationSidecar(entries=[]))
        path = tmp_path / ".project" / "threatmodel" / "mitigations.yaml"
        content = path.read_text()
        assert content.startswith("#")
        assert "hand-edited" in content


class TestMatchFindings:
    def test_matches_by_fingerprint(self) -> None:
        f = _make_finding()
        object.__setattr__(f, "fingerprint", "sha256:abcdef0123456789")
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(
                    fingerprint="sha256:abcdef0123456789",
                    status=MitigationStatus.MITIGATED,
                ),
            ]
        )
        matches = match_findings([f], sidecar)
        assert "sha256:abcdef0123456789" in matches
        assert matches["sha256:abcdef0123456789"].status == MitigationStatus.MITIGATED

    def test_no_match_returns_empty(self) -> None:
        f = _make_finding()
        object.__setattr__(f, "fingerprint", "sha256:0000000000000000")
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(
                    fingerprint="sha256:ffffffffffffffff",
                    status=MitigationStatus.ACCEPTED,
                ),
            ]
        )
        matches = match_findings([f], sidecar)
        assert len(matches) == 0

    def test_skips_findings_without_fingerprint(self) -> None:
        f = _make_finding()  # fingerprint is ""
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(
                    fingerprint="sha256:abcdef0123456789",
                    status=MitigationStatus.MITIGATED,
                ),
            ]
        )
        matches = match_findings([f], sidecar)
        assert len(matches) == 0


class TestDetectStale:
    def test_marks_missing_fingerprint_stale(self) -> None:
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(
                    fingerprint="sha256:gone",
                    status=MitigationStatus.MITIGATED,
                    stale=False,
                ),
            ]
        )
        changed = detect_stale(sidecar, active_fingerprints=set())
        assert changed is True
        assert sidecar.entries[0].stale is True

    def test_clears_stale_when_fingerprint_reappears(self) -> None:
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(
                    fingerprint="sha256:back",
                    status=MitigationStatus.MITIGATED,
                    stale=True,
                ),
            ]
        )
        changed = detect_stale(sidecar, active_fingerprints={"sha256:back"})
        assert changed is True
        assert sidecar.entries[0].stale is False

    def test_returns_false_when_no_change(self) -> None:
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(
                    fingerprint="sha256:active",
                    status=MitigationStatus.MITIGATED,
                    stale=False,
                ),
            ]
        )
        changed = detect_stale(sidecar, active_fingerprints={"sha256:active"})
        assert changed is False

    def test_never_deletes_entries(self) -> None:
        sidecar = MitigationSidecar(
            entries=[
                MitigationEntry(
                    fingerprint="sha256:gone1",
                    status=MitigationStatus.MITIGATED,
                ),
                MitigationEntry(
                    fingerprint="sha256:gone2",
                    status=MitigationStatus.ACCEPTED,
                ),
            ]
        )
        detect_stale(sidecar, active_fingerprints=set())
        assert len(sidecar.entries) == 2
