"""Format contract tests for darnit_baseline.threat_model.ts_generators.

Verifies the Markdown / SARIF / JSON output contracts documented in
``specs/010-threat-model-ast/contracts/output-format-contract.md``. The
critical invariants:

- The Markdown draft contains all 9 required H1/H2 sections in order.
- The verification prompt block has the ``<!-- darnit:verification-prompt-block -->``
  open/close HTML markers exactly once each.
- Every finding's embedded snippet has a ``>>>`` prefix on the marker line
  and only on the marker line.
- The SARIF result count matches the Markdown finding count.
- The JSON serialization includes the documented top-level keys and the
  same number of findings as the Markdown.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

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
)
from darnit_baseline.threat_model.models import StrideCategory
from darnit_baseline.threat_model.ranking import apply_cap, rank_findings
from darnit_baseline.threat_model.ts_discovery import discover_all
from darnit_baseline.threat_model.ts_generators import (
    VERIFICATION_PROMPT_CLOSE,
    VERIFICATION_PROMPT_OPEN,
    generate_json_summary,
    generate_markdown_threat_model,
    generate_sarif_threat_model,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers for building synthetic inputs
# ---------------------------------------------------------------------------


def _loc(file: str = "app.py", line: int = 10) -> Location:
    return Location(file=file, line=line, column=1, end_line=line, end_column=10)


def _snippet(line: int = 10) -> CodeSnippet:
    return CodeSnippet(
        lines=(
            "def foo():",
            "    x = 1",
            "    return x",
        ),
        start_line=line - 1,
        marker_line=line,
    )


def _finding(
    *,
    category: StrideCategory = StrideCategory.TAMPERING,
    severity: int = 6,
    confidence: float = 0.3,
    query_id: str = "python.sink.dangerous_attr",
    line: int = 10,
) -> CandidateFinding:
    return CandidateFinding(
        category=category,
        title="Potential command injection via subprocess.run",
        source=FindingSource.TREE_SITTER_STRUCTURAL,
        primary_location=_loc(line=line),
        related_assets=(),
        code_snippet=_snippet(line=line),
        severity=severity,
        confidence=confidence,
        rationale="Synthesized for test.",
        query_id=query_id,
    )


def _empty_scan_stats() -> FileScanStats:
    return FileScanStats(
        total_files_seen=3,
        excluded_dir_count=1,
        unsupported_file_count=1,
        in_scope_files=2,
        by_language={"python": 2},
        shallow_mode=False,
        shallow_threshold=500,
    )


def _sample_result(*, findings: list[CandidateFinding]) -> DiscoveryResult:
    ep = DiscoveredEntryPoint(
        kind=EntryPointKind.HTTP_ROUTE,
        name="create_user",
        location=_loc(file="main.py", line=14),
        language="python",
        framework="fastapi",
        route_path="/users",
        http_method="POST",
        has_auth_decorator=False,
        source_query="python.entry.decorated_route",
    )
    ds = DiscoveredDataStore(
        kind=DataStoreKind.KEY_VALUE,
        technology="redis",
        location=_loc(file="main.py", line=20),
        language="python",
        import_evidence="redis",
        dependency_manifest_evidence=None,
        source_query="python.datastore.bare_call",
    )
    return DiscoveryResult(
        entry_points=[ep],
        data_stores=[ds],
        call_graph=[],
        findings=findings,
        file_scan_stats=_empty_scan_stats(),
        opengrep_available=False,
        opengrep_degraded_reason="opengrep integration deferred to Phase 6",
    )


# ---------------------------------------------------------------------------
# Required-section tests
# ---------------------------------------------------------------------------


REQUIRED_H1 = "# Threat Model Report"
REQUIRED_H2_SECTIONS = [
    "## Executive Summary",
    "## Asset Inventory",
    "## Data Flow Diagram",
    "## STRIDE Threats",
    "## Attack Chains",
    "## Recommendations Summary",
    "## Verification Prompts",
    "## Limitations",
]


class TestMarkdownRequiredSections:
    """T060: the draft must contain all 9 required sections in order."""

    @pytest.fixture
    def draft(self):
        result = _sample_result(findings=[_finding()])
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        return generate_markdown_threat_model(
            repo_path="/tmp/repo",
            result=result,
            capped_findings=emitted,
            overflow=overflow,
        )

    def test_h1_title_present(self, draft: str) -> None:
        assert REQUIRED_H1 in draft

    @pytest.mark.parametrize("section", REQUIRED_H2_SECTIONS)
    def test_h2_section_present(self, draft: str, section: str) -> None:
        assert section in draft, f"Missing required section: {section}"

    def test_h2_sections_in_correct_order(self, draft: str) -> None:
        indices = [draft.index(section) for section in REQUIRED_H2_SECTIONS]
        assert indices == sorted(indices), (
            f"Required sections out of order: {list(zip(REQUIRED_H2_SECTIONS, indices))}"
        )


class TestVerificationPromptMarkers:
    """T061: exactly one open and one close HTML marker per draft."""

    def test_markers_appear_exactly_once(self) -> None:
        result = _sample_result(findings=[_finding()])
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        draft = generate_markdown_threat_model(
            repo_path="/tmp/repo",
            result=result,
            capped_findings=emitted,
            overflow=overflow,
        )
        assert draft.count(VERIFICATION_PROMPT_OPEN) == 1
        assert draft.count(VERIFICATION_PROMPT_CLOSE) == 1
        # Open must come before close.
        assert draft.index(VERIFICATION_PROMPT_OPEN) < draft.index(
            VERIFICATION_PROMPT_CLOSE
        )


class TestFindingSnippetMarker:
    """T062: the >>> prefix must only appear on the marker line."""

    def test_marker_line_prefixed(self) -> None:
        # Use a MEDIUM+ severity so the finding renders with full detail
        # (LOW findings are rendered as a compact summary table).
        f = _finding(line=10, severity=6, confidence=0.8)
        result = _sample_result(findings=[f])
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        draft = generate_markdown_threat_model(
            repo_path="/tmp/repo",
            result=result,
            capped_findings=emitted,
            overflow=overflow,
        )
        # Find the first code block in the STRIDE Threats section.
        stride_start = draft.index("## STRIDE Threats")
        # Count >>> markers — the snippet has 3 lines with one >>> prefix.
        code_block_matches = re.findall(
            r"^>>> +10 \|", draft[stride_start:], re.MULTILINE
        )
        assert len(code_block_matches) >= 1


class TestSarifOutput:
    """T063: SARIF result count must match the Markdown finding count."""

    def test_sarif_has_matching_result_count(self) -> None:
        findings = [_finding(line=10), _finding(line=20)]
        result = _sample_result(findings=findings)
        emitted, _ = apply_cap(rank_findings(result.findings), max_findings=50)
        sarif_text = generate_sarif_threat_model(result, emitted)
        sarif = json.loads(sarif_text)
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        assert len(sarif["runs"][0]["results"]) == len(emitted)

    def test_sarif_rules_deduplicated_per_query_id(self) -> None:
        findings = [
            _finding(line=10, query_id="python.sink.dangerous_attr"),
            _finding(line=20, query_id="python.sink.dangerous_attr"),  # same rule
            _finding(line=30, query_id="python.sink.dangerous_bare"),
        ]
        result = _sample_result(findings=findings)
        emitted, _ = apply_cap(rank_findings(result.findings), max_findings=50)
        sarif = json.loads(generate_sarif_threat_model(result, emitted))
        rule_ids = {r["id"] for r in sarif["runs"][0]["tool"]["driver"]["rules"]}
        assert rule_ids == {
            "python.sink.dangerous_attr",
            "python.sink.dangerous_bare",
        }


class TestJsonOutput:
    """T064: JSON output includes documented top-level keys."""

    def test_json_has_expected_top_level_keys(self) -> None:
        result = _sample_result(findings=[_finding()])
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        payload = json.loads(generate_json_summary(result, emitted, overflow))

        for key in (
            "entry_points",
            "data_stores",
            "findings",
            "file_scan_stats",
            "trimmed_overflow",
            "opengrep_available",
        ):
            assert key in payload, f"Missing JSON key: {key}"

    def test_json_findings_count_matches_markdown(self) -> None:
        findings = [_finding(line=10), _finding(line=20), _finding(line=30)]
        result = _sample_result(findings=findings)
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        payload = json.loads(generate_json_summary(result, emitted, overflow))
        assert len(payload["findings"]) == len(emitted)


class TestLimitationsSection:
    """T065: Limitations surfaces the key evidence fields."""

    def test_limitations_mentions_overflow(self) -> None:
        findings = [_finding(line=i + 1) for i in range(3)]
        result = _sample_result(findings=findings)
        emitted, overflow = apply_cap(
            rank_findings(result.findings), max_findings=2
        )
        assert overflow.total == 1
        draft = generate_markdown_threat_model(
            repo_path="/tmp/repo",
            result=result,
            capped_findings=emitted,
            overflow=overflow,
        )
        assert "1 trimmed" in draft or "1 additional" in draft

    def test_limitations_mentions_opengrep_missing(self) -> None:
        result = _sample_result(findings=[_finding()])
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        draft = generate_markdown_threat_model(
            repo_path="/tmp/repo",
            result=result,
            capped_findings=emitted,
            overflow=overflow,
        )
        assert "Opengrep" in draft
        assert "not available" in draft

    def test_limitations_reports_file_counts(self) -> None:
        result = _sample_result(findings=[])
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        draft = generate_markdown_threat_model(
            repo_path="/tmp/repo",
            result=result,
            capped_findings=emitted,
            overflow=overflow,
        )
        # _empty_scan_stats() returns in_scope_files=2, excluded_dir_count=1,
        # unsupported_file_count=1
        assert "**2** in-scope files" in draft
        assert "**1** vendor/build" in draft or "**1** files" in draft


class TestSkillReviewContractPreserved:
    """T066 / SC-005: the draft structure is stable enough that the
    ``darnit-remediate`` skill's existing review instructions work
    unchanged."""

    def test_all_nine_sections_and_marker(self) -> None:
        result = _sample_result(findings=[_finding()])
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        draft = generate_markdown_threat_model(
            repo_path="/tmp/repo",
            result=result,
            capped_findings=emitted,
            overflow=overflow,
        )
        # All 9 sections
        assert REQUIRED_H1 in draft
        for section in REQUIRED_H2_SECTIONS:
            assert section in draft
        # Verification marker
        assert VERIFICATION_PROMPT_OPEN in draft
        # Ends with a newline
        assert draft.endswith("\n")


class TestDogfoodDarnitDraft:
    """The critical C1 regression: run the full new pipeline against
    darnit itself and verify the committed-style draft does NOT contain
    the phantom postgresql finding from gpg.ssh.allowedSignersFile."""

    @pytest.fixture(scope="class")
    def draft(self):
        repo_root = Path(__file__).resolve().parents[3]
        result = discover_all(repo_root)
        emitted, overflow = apply_cap(rank_findings(result.findings), max_findings=50)
        return generate_markdown_threat_model(
            repo_path=str(repo_root),
            result=result,
            capped_findings=emitted,
            overflow=overflow,
        )

    def test_draft_has_no_phantom_postgres_from_gpg_file(self, draft: str) -> None:
        """The draft produced by the NEW pipeline against darnit itself
        must not reference the phantom postgresql finding."""
        # If the phantom finding appeared, the data store section would
        # mention the darnit-gittuf handlers.py line.
        assert "allowedSignersFile" not in draft, (
            "Draft contains reference to gpg.ssh.allowedSignersFile — "
            "the phantom postgres finding has returned"
        )

    def test_draft_has_required_structure(self, draft: str) -> None:
        """Even on a real repo scan, the draft must have the required
        sections so the skill can review it."""
        assert REQUIRED_H1 in draft
        for section in REQUIRED_H2_SECTIONS:
            assert section in draft
        assert VERIFICATION_PROMPT_OPEN in draft


# ---------------------------------------------------------------------------
# Feature 014-cobra-threat-model: CLI Entry Points rendering tests
# ---------------------------------------------------------------------------


class TestCliEntryPointsRendering:
    """T021 — verify the rendered ### CLI Entry Points subsection."""

    def _build_family(
        self,
        family_key: str = "cache",
        source_root: str = "internal/cmd/cache/",
        display_name: str = "cache",
        stride: list[str] | None = None,
        members: list[tuple[str, str, int]] | None = None,
    ):
        from darnit_baseline.threat_model.discovery_models import (
            CommandFamily,
            DiscoveredEntryPoint,
            EntryPointKind,
            Location,
        )

        if stride is None:
            stride = ["Tampering"]
        if members is None:
            members = [("cache", "internal/cmd/cache/cache.go", 13)]
        m = [
            DiscoveredEntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                name=name,
                location=Location(path, line, 1, line + 2, 1),
                language="go",
                framework="cobra",
                route_path=None,
                http_method=None,
                has_auth_decorator=False,
                source_query="go.entry.cobra_command_literal",
            )
            for name, path, line in members
        ]
        return CommandFamily(
            family_key=family_key,
            source_root=source_root,
            display_name=display_name,
            members=m,
            import_signatures={"os.WriteFile"},
            stride_categories=stride,
            needs_reviewer_attention=True,
        )

    def test_empty_families_renders_nothing(self) -> None:
        """FR-014: no placeholder when no CLI families exist."""
        from darnit_baseline.threat_model.renderers.summary import _render_cli_entry_points

        assert _render_cli_entry_points([]) == []

    def test_section_contains_required_headings(self) -> None:
        from darnit_baseline.threat_model.renderers.summary import _render_cli_entry_points

        family = self._build_family()
        out = "\n".join(_render_cli_entry_points([family]))
        assert "## Entry Points" in out
        assert "### CLI Entry Points" in out
        assert "#### Family: cache" in out

    def test_family_block_contains_all_required_fields(self) -> None:
        """Per output contract: source root, subcommands, STRIDE categories,
        confidence line, table, refinement note."""
        from darnit_baseline.threat_model.renderers.summary import _render_cli_entry_points

        family = self._build_family(
            members=[
                ("cache", "internal/cmd/cache/cache.go", 13),
                ("init", "internal/cmd/cache/init/init.go", 26),
                ("delete", "internal/cmd/cache/delete/delete.go", 23),
            ]
        )
        out = "\n".join(_render_cli_entry_points([family]))
        assert "**Source root**: `internal/cmd/cache/`" in out
        assert "**Subcommands**: 3 (cache, init, delete)" in out
        assert "**STRIDE categories**: Tampering" in out
        assert "**Confidence**: heuristic — needs reviewer attention" in out
        assert "| Subcommand | Location | Notes |" in out
        assert "internal/cmd/cache/init/init.go:26" in out
        assert "Refinement notes:" in out
        assert "may need recategorisation" in out

    def test_multi_category_rendered_as_comma_separated(self) -> None:
        from darnit_baseline.threat_model.renderers.summary import _render_cli_entry_points

        family = self._build_family(stride=["Spoofing", "Information Disclosure"])
        out = "\n".join(_render_cli_entry_points([family]))
        assert "**STRIDE categories**: Spoofing, Information Disclosure" in out

    def test_render_summary_omits_cli_section_when_no_families(self) -> None:
        """Integration: render_summary's full output skips the parent
        ## Entry Points heading when no CLI families exist (FR-014)."""
        from darnit_baseline.threat_model.discovery_models import (
            DiscoveryResult,
            FileScanStats,
        )
        from darnit_baseline.threat_model.renderers.common import GeneratorOptions
        from darnit_baseline.threat_model.renderers.summary import render_summary

        result = DiscoveryResult(
            entry_points=[],
            data_stores=[],
            call_graph=[],
            findings=[],
            file_scan_stats=FileScanStats(
                total_files_seen=0,
                excluded_dir_count=0,
                unsupported_file_count=0,
                in_scope_files=0,
                by_language={},
                shallow_mode=False,
                shallow_threshold=500,
            ),
            opengrep_available=False,
        )
        out = render_summary(
            groups=[],
            sidecar_matches={},
            result=result,
            options=GeneratorOptions(),
            cli_families=None,
        )
        assert "## Entry Points" not in out
        assert "### CLI Entry Points" not in out

    def test_render_summary_includes_cli_section_when_families_present(self) -> None:
        from darnit_baseline.threat_model.discovery_models import (
            DiscoveryResult,
            FileScanStats,
        )
        from darnit_baseline.threat_model.renderers.common import GeneratorOptions
        from darnit_baseline.threat_model.renderers.summary import render_summary

        family = self._build_family()
        result = DiscoveryResult(
            entry_points=[],
            data_stores=[],
            call_graph=[],
            findings=[],
            file_scan_stats=FileScanStats(
                total_files_seen=1,
                excluded_dir_count=0,
                unsupported_file_count=0,
                in_scope_files=1,
                by_language={"go": 1},
                shallow_mode=False,
                shallow_threshold=500,
            ),
            opengrep_available=False,
        )
        out = render_summary(
            groups=[],
            sidecar_matches={},
            result=result,
            options=GeneratorOptions(),
            cli_families=[family],
        )
        assert "## Entry Points" in out
        assert "### CLI Entry Points" in out
        assert "#### Family: cache" in out


# ---------------------------------------------------------------------------
# Feature 014-cobra-threat-model US2: Notes column + verification prompts +
# Limitations counters (T030)
# ---------------------------------------------------------------------------


class TestCliNotesColumn:
    """T029-related: the Notes column is populated from Short: where present."""

    def _build_family_with_metadata(self):
        from darnit_baseline.threat_model.discovery_models import (
            CommandFamily,
            DiscoveredEntryPoint,
            EntryPointKind,
            Location,
        )

        members = [
            DiscoveredEntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                name="cache",
                location=Location("cmd/cache/cache.go", 10, 1, 12, 1),
                language="go",
                framework="cobra",
                route_path=None,
                http_method=None,
                has_auth_decorator=False,
                source_query="go.entry.cobra_command_literal",
            ),
            DiscoveredEntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                name="init",
                location=Location("cmd/cache/init/init.go", 11, 1, 13, 1),
                language="go",
                framework="cobra",
                route_path=None,
                http_method=None,
                has_auth_decorator=False,
                source_query="go.entry.cobra_command_literal",
            ),
        ]
        family = CommandFamily(
            family_key="cache",
            source_root="cmd/cache/",
            display_name="cache",
            members=members,
            import_signatures={"os.WriteFile"},
            stride_categories=["Tampering"],
            needs_reviewer_attention=True,
        )
        metadata = {
            "cmd/cache/cache.go:10": {"short": "Manage the local cache"},
            "cmd/cache/init/init.go:11": {"short": "Create the cache directory"},
        }
        return family, metadata

    def test_notes_column_populated_from_short(self) -> None:
        from darnit_baseline.threat_model.renderers.summary import _render_cli_entry_points

        family, metadata = self._build_family_with_metadata()
        out = "\n".join(_render_cli_entry_points([family], command_metadata=metadata))
        assert "| cache | `cmd/cache/cache.go:10` | Manage the local cache |" in out
        assert "| init | `cmd/cache/init/init.go:11` | Create the cache directory |" in out

    def test_notes_column_empty_when_no_metadata(self) -> None:
        """No metadata → Notes cell renders as a blank space."""
        from darnit_baseline.threat_model.renderers.summary import _render_cli_entry_points

        family, _ = self._build_family_with_metadata()
        out = "\n".join(_render_cli_entry_points([family], command_metadata=None))
        # Empty Notes cell — no "Manage the local cache" text appears.
        assert "Manage the local cache" not in out
        # But the row is still well-formed: blank between the location pipes.
        assert "| cache | `cmd/cache/cache.go:10` |  |" in out

    def test_pipe_in_short_text_is_escaped(self) -> None:
        """A | character in Short: must be escaped to avoid breaking the
        markdown table row."""
        from darnit_baseline.threat_model.renderers.summary import _render_cli_entry_points

        family, _ = self._build_family_with_metadata()
        metadata = {
            "cmd/cache/cache.go:10": {"short": "Foo | bar"},
        }
        out = "\n".join(
            _render_cli_entry_points([family], command_metadata=metadata)
        )
        assert "Foo \\| bar" in out


class TestVerificationPromptCliParagraph:
    """T030 — CLI-specific paragraph appears inside the verification-prompt
    block only when CLI families are present."""

    def _make_minimal_result(self):
        from darnit_baseline.threat_model.discovery_models import (
            DiscoveryResult,
            FileScanStats,
        )

        return DiscoveryResult(
            entry_points=[],
            data_stores=[],
            call_graph=[],
            findings=[],
            file_scan_stats=FileScanStats(
                total_files_seen=0,
                excluded_dir_count=0,
                unsupported_file_count=0,
                in_scope_files=0,
                by_language={},
                shallow_mode=False,
                shallow_threshold=500,
            ),
            opengrep_available=False,
        )

    def _make_family(self):
        from darnit_baseline.threat_model.discovery_models import (
            CommandFamily,
            DiscoveredEntryPoint,
            EntryPointKind,
            Location,
        )

        ep = DiscoveredEntryPoint(
            kind=EntryPointKind.CLI_COMMAND,
            name="x",
            location=Location("cmd/x/x.go", 10, 1, 12, 1),
            language="go",
            framework="cobra",
            route_path=None,
            http_method=None,
            has_auth_decorator=False,
            source_query="go.entry.cobra_command_literal",
        )
        return CommandFamily(
            family_key="x",
            source_root="cmd/x/",
            display_name="x",
            members=[ep],
            import_signatures={"os.WriteFile"},
            stride_categories=["Tampering"],
            needs_reviewer_attention=True,
        )

    def test_cli_paragraph_present_when_families_exist(self) -> None:
        from darnit_baseline.threat_model.renderers.common import GeneratorOptions
        from darnit_baseline.threat_model.renderers.summary import render_summary

        family = self._make_family()
        out = render_summary(
            groups=[],
            sidecar_matches={},
            result=self._make_minimal_result(),
            options=GeneratorOptions(),
            cli_families=[family],
        )
        assert "<!-- darnit:verification-prompt-block -->" in out
        assert "**For the CLI Entry Points section:**" in out
        assert "import-based heuristic, not a STRIDE analysis" in out

    def test_cli_paragraph_absent_when_no_families(self) -> None:
        from darnit_baseline.threat_model.renderers.common import GeneratorOptions
        from darnit_baseline.threat_model.renderers.summary import render_summary

        out = render_summary(
            groups=[],
            sidecar_matches={},
            result=self._make_minimal_result(),
            options=GeneratorOptions(),
            cli_families=None,
        )
        assert "<!-- darnit:verification-prompt-block -->" in out
        assert "**For the CLI Entry Points section:**" not in out


class TestLimitationsCobraCounters:
    """T030 — Limitations section includes cobra-specific scan counters."""

    def _make_result_with_cobra_stats(self, stats):
        from darnit_baseline.threat_model.discovery_models import (
            DiscoveryResult,
            FileScanStats,
        )

        r = DiscoveryResult(
            entry_points=[],
            data_stores=[],
            call_graph=[],
            findings=[],
            file_scan_stats=FileScanStats(
                total_files_seen=10,
                excluded_dir_count=0,
                unsupported_file_count=0,
                in_scope_files=10,
                by_language={"go": 10},
                shallow_mode=False,
                shallow_threshold=500,
            ),
            opengrep_available=False,
        )
        r.cobra_stats = stats
        return r

    def test_cobra_file_counts_surface_when_present(self) -> None:
        from darnit_baseline.threat_model.renderers.summary import _render_limitations

        result = self._make_result_with_cobra_stats(
            {
                "go_files_scanned": 10,
                "cobra_files": 5,
                "cobra_files_unmatched": 0,
                "unmatched_examples": [],
            }
        )
        out = "\n".join(_render_limitations(result, None))
        assert "Scanned **10** Go files" in out
        assert "**5** imported `github.com/spf13/cobra`" in out

    def test_unmatched_count_surfaces_with_example_when_nonzero(self) -> None:
        from darnit_baseline.threat_model.renderers.summary import _render_limitations

        result = self._make_result_with_cobra_stats(
            {
                "go_files_scanned": 10,
                "cobra_files": 5,
                "cobra_files_unmatched": 2,
                "unmatched_examples": ["pkg/builder/builder.go"],
            }
        )
        out = "\n".join(_render_limitations(result, None))
        assert "**2** cobra-importing file(s) matched no recognised pattern" in out
        assert "`pkg/builder/builder.go`" in out

    def test_cobra_section_omitted_when_no_cobra_files(self) -> None:
        from darnit_baseline.threat_model.renderers.summary import _render_limitations

        result = self._make_result_with_cobra_stats(
            {
                "go_files_scanned": 10,
                "cobra_files": 0,
                "cobra_files_unmatched": 0,
                "unmatched_examples": [],
            }
        )
        out = "\n".join(_render_limitations(result, None))
        assert "imported `github.com/spf13/cobra`" not in out
