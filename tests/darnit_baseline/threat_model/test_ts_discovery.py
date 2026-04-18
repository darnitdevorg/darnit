"""End-to-end tests for the tree-sitter discovery pipeline.

These tests exercise ``ts_discovery.discover_all`` against hand-authored
fixture repositories. They are the core regression suite for the
010-threat-model-ast rewrite: red-herring fixtures MUST produce zero
findings (SC-001), and real-risk fixtures MUST produce the seeded
findings (SC-002).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit_baseline.threat_model.discovery_models import (
    DataStoreKind,
    EntryPointKind,
    FindingSource,
)
from darnit_baseline.threat_model.models import StrideCategory
from darnit_baseline.threat_model.opengrep_runner import OpengrepResult
from darnit_baseline.threat_model.ts_discovery import DiscoveryConfig, discover_all

FIXTURES = Path(__file__).parent / "fixtures"


class TestNoqaSuppression:
    def test_suppressed_findings_filtered(self, tmp_path: Path) -> None:
        """Verify that Findings annotated with `# noqa` are completely removed."""
        (tmp_path / "app.py").write_text(
            "import subprocess\n"
            "subprocess.run('ls', shell=True)\n"  # line 2: unsuppressed
            "subprocess.run('ls', shell=True)  # noqa\n"  # line 3: suppressed (all)
            "subprocess.run('ls', shell=True)  # noqa: irrelevant_rule\n"  # line 4: unsuppressed
            "subprocess.run('ls', shell=True)  # noqa: python.sink.dangerous_attr\n"  # line 5: suppressed
            "subprocess.run('ls', shell=True)  # noqa: other, python.sink.dangerous_attr, more\n"  # line 6: suppressed (in list)
        )

        result = discover_all(tmp_path)

        # We expect findings from lines 2 and 4 to survive.
        # Noting that subprocess.run produces 2 findings (command injection & dos timeout)
        assert len(result.findings) == 4
        lines = [f.primary_location.line for f in result.findings]
        # Findings order isn't strictly guaranteed, so sort before compare
        assert sorted(set(lines)) == [2, 4]


# ---------------------------------------------------------------------------
# US1 fixture tests
# ---------------------------------------------------------------------------


class TestFastApiFixture:
    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "fastapi_minimal")

    def test_finds_exactly_two_entry_points(self, result) -> None:
        assert len(result.entry_points) == 2

    def test_both_entry_points_are_http_routes(self, result) -> None:
        for ep in result.entry_points:
            assert ep.kind == EntryPointKind.HTTP_ROUTE
            assert ep.framework == "fastapi"
            assert ep.language == "python"

    def test_route_paths_and_methods(self, result) -> None:
        routes = {(ep.route_path, ep.http_method): ep.name for ep in result.entry_points}
        assert routes == {
            ("/healthz", "GET"): "healthz",
            ("/users", "POST"): "create_user",
        }

    def test_no_data_stores(self, result) -> None:
        assert len(result.data_stores) == 0

    def test_spoofing_findings_for_unauthenticated_routes(self, result) -> None:
        """Each entry point without an auth decorator should produce a
        Spoofing candidate finding."""
        spoofing = [f for f in result.findings if f.category == StrideCategory.SPOOFING]
        assert len(spoofing) == 2  # both FastAPI routes are unauthenticated


class TestFlaskFixture:
    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "flask_minimal")

    def test_finds_two_flask_routes(self, result) -> None:
        assert len(result.entry_points) == 2
        for ep in result.entry_points:
            assert ep.kind == EntryPointKind.HTTP_ROUTE
            assert ep.framework == "flask"

    def test_route_paths(self, result) -> None:
        paths = {ep.route_path for ep in result.entry_points}
        assert paths == {"/", "/submit"}


class TestMcpServerFixture:
    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "mcp_server_minimal")

    def test_finds_two_mcp_tools(self, result) -> None:
        assert len(result.entry_points) == 2
        for ep in result.entry_points:
            assert ep.kind == EntryPointKind.MCP_TOOL
            assert ep.framework == "mcp"

    def test_mcp_tool_names(self, result) -> None:
        names = {ep.name for ep in result.entry_points}
        assert names == {"greet", "echo"}


class TestMcpServerImperativeFixture:
    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "mcp_server_imperative")

    def test_finds_two_mcp_tools(self, result) -> None:
        assert len(result.entry_points) == 2
        for ep in result.entry_points:
            assert ep.kind == EntryPointKind.MCP_TOOL
            assert ep.framework == "mcp"

    def test_mcp_tool_names(self, result) -> None:
        names = {ep.name for ep in result.entry_points}
        assert names == {"greet", "echo"}

    def test_source_query_is_imperative(self, result) -> None:
        for ep in result.entry_points:
            assert ep.source_query == "python.entry.mcp_tool_imperative"


class TestImperativeHttpRouteDetected:
    def test_add_url_rule_detected(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "from flask import Flask\n"
            "\n"
            "app = Flask(__name__)\n"
            "\n"
            "def foo_handler():\n"
            "    return 'foo'\n"
            "\n"
            'app.add_url_rule("/foo", "foo", foo_handler)\n'
        )
        result = discover_all(tmp_path)
        imperative_eps = [ep for ep in result.entry_points if ep.source_query == "python.entry.http_route_imperative"]
        assert len(imperative_eps) == 1
        ep = imperative_eps[0]
        assert ep.kind == EntryPointKind.HTTP_ROUTE
        assert ep.route_path == "/foo"
        assert ep.framework == "flask"

    def test_add_route_detected(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "from starlette.applications import Starlette\n"
            "\n"
            "app = Starlette()\n"
            "\n"
            "def homepage(request):\n"
            "    return Response('hi')\n"
            "\n"
            'app.add_route("/home", homepage)\n'
        )
        result = discover_all(tmp_path)
        imperative_eps = [ep for ep in result.entry_points if ep.source_query == "python.entry.http_route_imperative"]
        assert len(imperative_eps) == 1
        ep = imperative_eps[0]
        assert ep.kind == EntryPointKind.HTTP_ROUTE
        assert ep.route_path == "/home"


class TestSubprocessTaintedFixture:
    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "subprocess_tainted")

    def test_finds_entry_point_and_subprocess_finding(self, result) -> None:
        assert len(result.entry_points) == 1
        assert result.entry_points[0].route_path == "/run"

        tampering = [f for f in result.findings if f.category == StrideCategory.TAMPERING]
        assert len(tampering) == 1
        finding = tampering[0]
        assert finding.source == FindingSource.TREE_SITTER_STRUCTURAL
        assert "subprocess.run" in finding.title
        assert finding.primary_location.file == "app.py"
        assert finding.primary_location.line == 21

    def test_spoofing_finding_for_unauthenticated_route(self, result) -> None:
        """The /run endpoint has no auth decorator → Spoofing finding."""
        spoofing = [f for f in result.findings if f.category == StrideCategory.SPOOFING]
        assert len(spoofing) == 1
        assert "/run" in spoofing[0].title

    def test_finding_snippet_marker_matches_location(self, result) -> None:
        finding = result.findings[0]
        assert finding.code_snippet.marker_line == finding.primary_location.line


class TestDatastoreBareImportFixture:
    """H1 regression: bare-call constructors after ``from X import Y``."""

    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "datastore_bare_import")

    def test_finds_three_datastores_via_bare_call(self, result) -> None:
        assert len(result.data_stores) == 3

    def test_all_bare_call_source_query(self, result) -> None:
        for ds in result.data_stores:
            assert ds.source_query == "python.datastore.bare_call"

    def test_technologies_match_expected(self, result) -> None:
        techs = {ds.technology for ds in result.data_stores}
        assert techs == {"redis", "mongodb", "sqlalchemy"}

    def test_import_evidence_is_populated(self, result) -> None:
        for ds in result.data_stores:
            assert ds.import_evidence is not None

    def test_info_disclosure_findings_for_each_store(self, result) -> None:
        info_findings = [f for f in result.findings if f.category == StrideCategory.INFORMATION_DISCLOSURE]
        assert len(info_findings) == 3  # one per data store


class TestSubprocessTieredClassification:
    """Subprocess calls are classified into four tiers (static, parameterized,
    dynamic, shell) with tier-specific severity and confidence scores.
    Static literal-list calls are kept but scored very low.
    """

    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "subprocess_literal_list")

    def test_all_four_calls_produce_findings(self, result) -> None:
        # All subprocess calls produce Tampering findings (4) plus DoS
        # findings for calls without timeout (4).
        tampering = [f for f in result.findings if f.category.value == "tampering"]
        assert len(tampering) == 4
        dos = [f for f in result.findings if f.category.value == "denial_of_service"]
        assert len(dos) == 4

    def test_static_findings_have_lowest_scores(self, result) -> None:
        # Static literal-list calls get severity=1, confidence=0.2.
        static_findings = [f for f in result.findings if "subprocess/static" in f.rationale]
        assert len(static_findings) == 2
        for f in static_findings:
            assert f.severity == 1
            assert f.confidence == 0.2

    def test_dynamic_finding_scores_higher(self, result) -> None:
        dynamic_findings = [f for f in result.findings if "subprocess/dynamic" in f.rationale]
        assert len(dynamic_findings) == 1
        f = dynamic_findings[0]
        assert f.severity == 6
        assert f.confidence == 0.8

    def test_shell_finding_scores_highest(self, result) -> None:
        shell_findings = [f for f in result.findings if "subprocess/shell" in f.rationale]
        assert len(shell_findings) == 1
        f = shell_findings[0]
        assert f.severity == 8
        assert f.confidence == 0.9

    def test_variable_arg_call_is_kept(self, result) -> None:
        # Line 24 uses ``subprocess.run(cmd, ...)`` with a variable.
        kept_lines = {f.primary_location.line for f in result.findings}
        assert 24 in kept_lines

    def test_shell_true_call_is_kept(self, result) -> None:
        # Line 29 uses ``shell=True`` with a literal string.
        kept_lines = {f.primary_location.line for f in result.findings}
        assert 29 in kept_lines


class TestConfigDrivenSubprocess:
    """Config-driven subprocess calls should get elevated confidence (0.9)
    because the command argument originates from a dict/config lookup,
    matching the TOML-driven command construction attack surface.
    """

    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "config_driven_subprocess")

    def test_finds_at_least_one_finding(self, result) -> None:
        assert len(result.findings) >= 1

    def test_config_driven_elevated_confidence(self, result) -> None:
        # The fixture's subprocess.run(full_cmd, ...) should be detected as
        # config-driven because full_cmd is built from config["command"] and
        # config.get("args", []) within the same function scope.
        config_findings = [f for f in result.findings if f.confidence >= 0.9]
        assert len(config_findings) >= 1

    def test_rationale_mentions_configuration(self, result) -> None:
        config_findings = [f for f in result.findings if f.confidence >= 0.9]
        assert len(config_findings) >= 1
        for f in config_findings:
            assert "configuration" in f.rationale.lower() or "config" in f.rationale.lower()


class TestGoHttpHandlerFixture:
    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "go_http_handler")

    def test_finds_http_handlefunc_entry_point(self, result) -> None:
        assert len(result.entry_points) == 1
        ep = result.entry_points[0]
        assert ep.kind == EntryPointKind.HTTP_ROUTE
        assert ep.language == "go"
        assert ep.route_path == "/api"

    def test_finds_postgres_data_store(self, result) -> None:
        assert len(result.data_stores) == 1
        ds = result.data_stores[0]
        assert ds.technology == "postgresql"
        assert ds.kind == DataStoreKind.RELATIONAL_DB
        assert ds.language == "go"
        assert ds.import_evidence is not None

    def test_spoofing_and_info_disclosure_findings(self, result) -> None:
        """The Go fixture has one unauthenticated HTTP route → Spoofing,
        and one data store → Information Disclosure."""
        categories = {f.category for f in result.findings}
        assert StrideCategory.SPOOFING in categories
        assert StrideCategory.INFORMATION_DISCLOSURE in categories


# ---------------------------------------------------------------------------
# SC-001 regression: red herrings MUST produce zero findings
# ---------------------------------------------------------------------------


class TestRedHerringsRegression:
    @pytest.fixture
    def result(self):
        return discover_all(FIXTURES / "red_herrings")

    def test_zero_entry_points(self, result) -> None:
        assert result.entry_points == []

    def test_zero_data_stores(self, result) -> None:
        assert result.data_stores == []

    def test_zero_findings(self, result) -> None:
        assert result.findings == []

    def test_specifically_no_postgres_finding(self, result) -> None:
        """The docstring_postgres.py file mentions postgres-adjacent
        keywords inside a module docstring. The old pipeline flagged it.
        The new pipeline MUST ignore it because tree-sitter queries
        structurally skip comment/string nodes."""
        postgres_stores = [ds for ds in result.data_stores if ds.technology == "postgresql"]
        assert postgres_stores == []

    def test_specifically_no_pii_email_finding(self, result) -> None:
        """metadata_email.py assigns to `email=data.get('email', '')` in
        config-metadata parsing. The old pipeline flagged it as PII
        handling. The new pipeline emits zero findings for this file."""
        # Since we don't emit PII findings at all in v1 (data stores and
        # subprocess only), the red_herrings result has no findings; this
        # is really a doc-assertion test that we didn't regress.
        assert result.findings == []


# ---------------------------------------------------------------------------
# Dogfood: run against darnit itself (SC-001)
# ---------------------------------------------------------------------------


class TestDogfoodAgainstDarnit:
    """Run discover_all against the darnit repo root itself and assert the
    false-positive patterns from the old pipeline do not appear."""

    @pytest.fixture(scope="class")
    def result(self):
        repo_root = Path(__file__).resolve().parents[3]
        return discover_all(repo_root)

    def test_gpg_ssh_file_does_not_produce_postgres_finding(self, result) -> None:
        """The phantom postgresql finding from the old pipeline fired on
        handlers.py line 84 (the `gpg.ssh.allowedSignersFile` docstring).
        The new pipeline MUST NOT produce any postgresql finding from
        that file."""
        phantom = [
            ds for ds in result.data_stores if ds.technology == "postgresql" and "darnit-gittuf" in ds.location.file
        ]
        assert phantom == [], (
            f"Expected no phantom postgresql from darnit-gittuf, got: "
            f"{[(d.location.file, d.location.line) for d in phantom]}"
        )

    def test_metadata_email_does_not_produce_pii_finding(self, result) -> None:
        """The old pipeline flagged maintainer-metadata parsing in
        dot_project.py as PII handling. The new pipeline should have no
        PII findings at all in v1, so this is a doc-assertion check."""
        pii_findings = [f for f in result.findings if "pii" in f.title.lower() or "email" in f.title.lower()]
        assert pii_findings == []

    def test_darnit_literal_list_subprocess_calls_are_filtered(self, result) -> None:
        """H3 regression: darnit's tests use ``subprocess.run(["darnit", ...])``
        with hardcoded string-literal lists. After the literal-list filter,
        none of those should appear as findings.

        This is effectively a negative assertion on the new pipeline: the
        rewrite shouldn't over-flag safe subprocess calls that the old
        regex pipeline's heuristics also (sometimes) caught.
        """
        literal_list_findings = [
            f for f in result.findings if "subprocess.run" in f.title and "conftest.py" in f.primary_location.file
        ]
        assert literal_list_findings == [], (
            f"Expected literal-list subprocess.run calls to be filtered "
            f"out of darnit's conftest.py; got: "
            f"{[(f.primary_location.file, f.primary_location.line) for f in literal_list_findings]}"
        )

    def test_darnit_os_system_calls_remain_low_confidence(self, result) -> None:
        """Positive check with low-confidence assertion: ``os.system``
        calls with f-string interpolation stay as findings but at
        confidence 0.3 so the top-N cap deprioritizes them.
        """
        os_system_findings = [f for f in result.findings if "os.system" in f.title]
        # May be zero in a future version of darnit; if present, verify
        # they're low-confidence so the top-N cap filters them.
        for f in os_system_findings:
            assert f.confidence == 0.3, (
                f"Expected os.system findings at confidence 0.3, "
                f"got {f.confidence} at {f.primary_location.file}:{f.primary_location.line}"
            )


# ---------------------------------------------------------------------------
# DiscoveryConfig and general orchestrator tests
# ---------------------------------------------------------------------------


class TestFrameworkInferenceH2Regression:
    """H2 regression: framework inference must come from AST-resolved imports,
    not from a substring search over the raw source bytes.
    """

    def test_docstring_mentioning_fastapi_does_not_set_framework(self, tmp_path: Path) -> None:
        """A file containing 'from fastapi' inside a docstring but no actual
        import MUST NOT be tagged as using the fastapi framework."""
        (tmp_path / "main.py").write_text(
            '"""Consider migrating from fastapi to litestar in v2."""\n'
            "\n"
            "class FakeApp:\n"
            "    def get(self, path):\n"
            "        def decorator(func):\n"
            "            return func\n"
            "        return decorator\n"
            "\n"
            "app = FakeApp()\n"
            "\n"
            '@app.get("/healthz")\n'
            "def healthz():\n"
            "    return {}\n"
        )
        result = discover_all(tmp_path)
        # The structural query still matches @app.get(...) — it's a valid
        # decorated call. What changed is the framework inference.
        assert len(result.entry_points) == 1
        ep = result.entry_points[0]
        assert ep.framework == "http", (
            f"Framework should be the generic 'http' default when "
            f"no real fastapi import is present; got {ep.framework!r}"
        )

    def test_real_fastapi_import_sets_framework(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text(
            'from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get("/")\ndef root():\n    return {}\n'
        )
        result = discover_all(tmp_path)
        assert len(result.entry_points) == 1
        assert result.entry_points[0].framework == "fastapi"

    def test_real_flask_import_sets_framework(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text(
            "from flask import Flask\n"
            "\n"
            "app = Flask(__name__)\n"
            "\n"
            '@app.route("/", methods=["GET"])\n'
            "def index():\n"
            "    return 'hi'\n"
        )
        result = discover_all(tmp_path)
        assert len(result.entry_points) == 1
        assert result.entry_points[0].framework == "flask"


class TestOpengrepEnrichment:
    """Phase 6 tests: Opengrep finding normalization and merge behavior.

    These tests mock the Opengrep subprocess to inject synthetic findings
    rather than requiring the real binary. The ``real_opengrep`` marker
    is used only for the integration smoke test that verifies the actual
    binary invocation.
    """

    def _fake_opengrep_result(
        self,
        findings: list[dict] | None = None,
        rule_errors: list[dict] | None = None,
    ) -> OpengrepResult:

        return OpengrepResult(
            available=True,
            findings=findings or [],
            rule_errors=rule_errors or [],
            degraded_reason=(f"{len(rule_errors)} rule-schema error(s)" if rule_errors else None),
            binary_used="opengrep",
            version="1.6.0",
            scan_duration_s=0.1,
        )

    def _synthetic_taint_finding(self, *, file: str = "app.py", line: int = 21) -> dict:
        """A synthetic Opengrep JSON entry mimicking a taint finding from
        ``darnit.taint.external-input-to-subprocess``."""
        return {
            "check_id": "darnit.taint.external-input-to-subprocess",
            "path": file,
            "start": {"line": line, "col": 14, "offset": 200},
            "end": {"line": line, "col": 66, "offset": 252},
            "extra": {
                "message": "External input flows to subprocess execution",
                "severity": "ERROR",
                "metadata": {"stride": "tampering"},
                "lines": "    result = subprocess.run(user_cmd, shell=True)",
                "dataflow_trace": {
                    "taint_source": {
                        "location": {
                            "start": {"line": 19, "col": 14},
                            "end": {"line": 19, "col": 50},
                        },
                        "content": "request.query_params.get('cmd', '')",
                    },
                    "intermediate_vars": [
                        {
                            "location": {
                                "start": {"line": 20, "col": 4},
                                "end": {"line": 20, "col": 12},
                            },
                            "content": "user_cmd",
                        }
                    ],
                    "taint_sink": {
                        "location": {
                            "start": {"line": line, "col": 14},
                            "end": {"line": line, "col": 66},
                        },
                        "content": "subprocess.run(user_cmd, shell=True)",
                    },
                },
            },
        }

    def test_opengrep_taint_finding_replaces_tree_sitter_structural(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When Opengrep produces a taint finding at the same (file, line)
        as an existing tree-sitter structural finding, the Opengrep finding
        wins because it includes a data-flow trace."""

        og_result = self._fake_opengrep_result(findings=[self._synthetic_taint_finding(file="app.py", line=21)])
        monkeypatch.setattr(
            "darnit_baseline.threat_model.ts_discovery._run_opengrep_enrichment",
            lambda repo_root: og_result,
        )

        result = discover_all(FIXTURES / "subprocess_tainted")
        tampering = [f for f in result.findings if f.category == StrideCategory.TAMPERING]
        # Should have exactly one Tampering finding (the Opengrep one
        # replaced the tree-sitter structural one at the same line).
        assert len(tampering) == 1
        finding = tampering[0]
        assert finding.source == FindingSource.OPENGREP_TAINT
        assert finding.data_flow is not None
        assert finding.confidence == 1.0  # taint = full confidence
        assert finding.primary_location.line == 21

    def test_opengrep_unavailable_produces_subset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SC-007 regression: when Opengrep is unavailable, the finding
        set must be a strict subset of what Opengrep would produce —
        meaning no NEW findings appear from the absence."""

        # Run without Opengrep (the default mock in conftest does this)
        result_without = discover_all(FIXTURES / "subprocess_tainted")

        # Run with Opengrep returning a taint finding
        og_result = self._fake_opengrep_result(findings=[self._synthetic_taint_finding(file="app.py", line=21)])
        monkeypatch.setattr(
            "darnit_baseline.threat_model.ts_discovery._run_opengrep_enrichment",
            lambda repo_root: og_result,
        )
        result_with = discover_all(FIXTURES / "subprocess_tainted")

        # "without" finding locations must be a subset of "with" locations
        locations_without = {(f.primary_location.file, f.primary_location.line) for f in result_without.findings}
        locations_with = {(f.primary_location.file, f.primary_location.line) for f in result_with.findings}
        assert locations_without <= locations_with, (
            f"Opengrep-absent produced locations not in Opengrep-present: {locations_without - locations_with}"
        )

    def test_opengrep_evidence_reflects_availability(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The DiscoveryResult must reflect whether Opengrep was available."""

        og_result = self._fake_opengrep_result(findings=[])
        monkeypatch.setattr(
            "darnit_baseline.threat_model.ts_discovery._run_opengrep_enrichment",
            lambda repo_root: og_result,
        )
        result = discover_all(FIXTURES / "fastapi_minimal")
        assert result.opengrep_available is True
        assert result.opengrep_degraded_reason is None

    def test_opengrep_rule_errors_surfaced_in_result(self, monkeypatch: pytest.MonkeyPatch) -> None:

        og_result = self._fake_opengrep_result(
            findings=[],
            rule_errors=[{"type": "InvalidRuleSchemaError", "long_msg": "bad rule"}],
        )
        monkeypatch.setattr(
            "darnit_baseline.threat_model.ts_discovery._run_opengrep_enrichment",
            lambda repo_root: og_result,
        )
        result = discover_all(FIXTURES / "fastapi_minimal")
        assert result.opengrep_available is True
        assert "rule-schema error" in (result.opengrep_degraded_reason or "")


class TestDiscoverAllOrchestrator:
    def test_reports_file_scan_stats(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("pass\n")
        (tmp_path / "b.md").write_text("# readme\n")
        result = discover_all(tmp_path)
        assert result.file_scan_stats is not None
        assert result.file_scan_stats.in_scope_files == 1
        assert result.file_scan_stats.unsupported_file_count == 1

    def test_opengrep_evidence_populated(self, tmp_path: Path) -> None:
        """Whether Opengrep is installed or not, the evidence fields must
        be populated. If installed, ``opengrep_available`` is True (even
        if the scan produced errors); if not, it's False with a reason."""
        (tmp_path / "a.py").write_text("pass\n")
        result = discover_all(tmp_path)
        # opengrep_available is a bool; degraded_reason is str | None
        assert isinstance(result.opengrep_available, bool)
        if not result.opengrep_available:
            assert result.opengrep_degraded_reason is not None

    def test_custom_shallow_threshold(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("pass\n")
        result = discover_all(tmp_path, config=DiscoveryConfig(shallow_threshold=3))
        assert result.file_scan_stats.shallow_mode is True

    def test_empty_inventory_warning_on_large_repo(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """When a repo has many in-scope files but no entry points, a warning
        should be logged indicating likely missing query coverage."""
        import logging
        from unittest.mock import patch

        from darnit_baseline.threat_model.discovery_models import FileScanStats

        fake_stats = FileScanStats(
            total_files_seen=80,
            excluded_dir_count=2,
            unsupported_file_count=5,
            in_scope_files=75,
            by_language={"python": 75},
            shallow_mode=False,
            shallow_threshold=500,
        )
        # Return no scanned files so no entry points are discovered.
        with (
            patch(
                "darnit_baseline.threat_model.ts_discovery.walk_repo",
                return_value=([], fake_stats),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = discover_all(tmp_path)

        assert result.entry_points == []
        assert any("zero entry points found" in msg and "75" in msg for msg in caplog.messages), (
            f"Expected warning about zero entry points; got: {caplog.messages}"
        )

    def test_extra_excludes_applied(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "a.py").parent.mkdir()
        (tmp_path / "src" / "a.py").write_text("pass\n")
        (tmp_path / "generated" / "big.py").parent.mkdir()
        (tmp_path / "generated" / "big.py").write_text("pass\n")
        result = discover_all(tmp_path, config=DiscoveryConfig(extra_excludes=("generated",)))
        in_scope = {Path(p.location.file).name for p in result.call_graph}
        assert "big.py" not in in_scope


# ---------------------------------------------------------------------------
# Phase 9: Self-scan dogfood validation (SC-001a, SC-001b, SC-009, SC-002a)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]  # baseline-mcp root


class TestSelfScanDogfood:
    """Run discovery against the actual darnit repository.

    These are the tests that would have caught the v1 gaps: empty asset
    inventory, identical subprocess scores, and single-category STRIDE
    output. They validate FR-001a, FR-004a, SC-001a, SC-001b, and SC-009.

    We scope the scan to ``packages/`` (the production source) and raise
    the shallow threshold to avoid shallow mode skipping subprocess queries.
    The full repo root triggers shallow mode (>500 in-scope files from
    docs/examples) which skips subprocess/call-graph analysis entirely.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return discover_all(
            REPO_ROOT / "packages",
            config=DiscoveryConfig(shallow_threshold=2000),
        )

    def test_finds_entry_points_sc001a(self, result) -> None:
        """SC-001a: self-scan must find MCP tool entry points.

        Darnit registers tools via server.add_tool() in factory.py.
        There are 2 static call sites (one for framework tools, one for
        implementation tools). Both must be detected.
        """
        assert len(result.entry_points) >= 2, (
            f"Expected at least 2 entry points from server.add_tool() calls; "
            f"got {len(result.entry_points)}: {result.entry_points}"
        )
        mcp_tools = [ep for ep in result.entry_points if ep.kind == EntryPointKind.MCP_TOOL]
        assert len(mcp_tools) >= 2, f"Expected at least 2 MCP_TOOL entry points; got {len(mcp_tools)}"

    def test_subprocess_scores_differentiated_sc001b(self, result) -> None:
        """SC-001b: subprocess findings must NOT all have identical scores.

        Static literal calls (e.g., ["git", "init"]) must score lower than
        dynamic calls (e.g., resolved_cmd from config).
        """
        tampering_findings = [f for f in result.findings if f.category == StrideCategory.TAMPERING]
        subprocess_findings = [
            f for f in tampering_findings if "subprocess" in f.title.lower() or "command injection" in f.title.lower()
        ]
        assert len(subprocess_findings) >= 5, (
            f"Expected at least 5 subprocess findings; "
            f"got {len(subprocess_findings)} (of {len(tampering_findings)} tampering, "
            f"{len(result.findings)} total). "
            f"Tampering titles: {[f.title for f in tampering_findings[:5]]}"
        )
        scores = [f.severity * f.confidence for f in subprocess_findings]
        assert max(scores) > min(scores), (
            f"All subprocess findings have identical score {scores[0]:.2f}. "
            f"Expected differentiation between static/parameterized/dynamic tiers."
        )

    def test_stride_coverage_sc009(self, result) -> None:
        """SC-009: self-scan must populate at least 2 STRIDE categories.

        With entry points detected, Spoofing should be populated alongside
        Tampering from subprocess findings.
        """
        categories_with_findings = {f.category for f in result.findings}
        assert len(categories_with_findings) >= 2, (
            f"Expected findings in at least 2 STRIDE categories; "
            f"got {len(categories_with_findings)}: "
            f"{[c.value for c in categories_with_findings]}"
        )

    def test_imperative_fixture_in_curated_suite_sc002a(self) -> None:
        """SC-002a: imperative registration fixture must produce entry points."""
        result = discover_all(FIXTURES / "mcp_server_imperative")
        assert len(result.entry_points) >= 2
        assert all(ep.source_query == "python.entry.mcp_tool_imperative" for ep in result.entry_points)
