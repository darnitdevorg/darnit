"""Unit tests for the Best Practices Badge output formatter.

Tests cover:
- Control ID key transform
- Status mapping for all known statuses
- URL generation structure and params
- Auto-detection fallback (no project URL)
- No justification for inconclusive / N/A results
- Total URL budget cap
"""

from darnit_baseline.formatters import (
    BADGE_BASE_URL as _BADGE_BASE_URL,
)
from darnit_baseline.formatters import (
    control_id_to_key as _ctk,
)
from darnit_baseline.formatters import (
    generate_badge_url as _gbu,
)
from darnit_baseline.formatters import (
    status_to_badge_status as _stbs,
)
from darnit_baseline.formatters.badge import (
    BADGE_BASE_URL,
    control_id_to_key,
    generate_badge_url,
    status_to_badge_status,
)

# ---------------------------------------------------------------------------
# control_id_to_key
# ---------------------------------------------------------------------------


class TestControlIdToKey:
    """Tests for the OSPS control ID → badge key transform."""

    def test_basic_transform(self):
        assert control_id_to_key("OSPS-AC-01.01") == "osps_ac_01_01"

    def test_vm_domain(self):
        assert control_id_to_key("OSPS-VM-03.02") == "osps_vm_03_02"

    def test_br_domain(self):
        assert control_id_to_key("OSPS-BR-02.01") == "osps_br_02_01"

    def test_do_domain(self):
        assert control_id_to_key("OSPS-DO-01.01") == "osps_do_01_01"

    def test_qa_domain(self):
        assert control_id_to_key("OSPS-QA-07.01") == "osps_qa_07_01"

    def test_all_hyphens_and_dots_replaced(self):
        key = control_id_to_key("OSPS-GV-02.01")
        assert "-" not in key
        assert "." not in key

    def test_result_is_lowercase(self):
        key = control_id_to_key("OSPS-AC-01.01")
        assert key == key.lower()


# ---------------------------------------------------------------------------
# status_to_badge_status
# ---------------------------------------------------------------------------


class TestStatusToBadgeStatus:
    """Tests for the darnit status → badge status mapping."""

    def test_pass_maps_to_met(self):
        assert status_to_badge_status("PASS") == "Met"

    def test_fail_maps_to_unmet(self):
        assert status_to_badge_status("FAIL") == "Unmet"

    def test_warn_maps_to_question_mark(self):
        # WARN = inconclusive; cannot assert Met or Unmet
        assert status_to_badge_status("WARN") == "?"

    def test_na_maps_to_na(self):
        assert status_to_badge_status("NA") == "N/A"

    def test_na_with_slash_maps_to_na(self):
        assert status_to_badge_status("N/A") == "N/A"

    def test_unknown_status_maps_to_question_mark(self):
        # Any unrecognised status is treated as inconclusive
        assert status_to_badge_status("WHATEVER") == "?"


# ---------------------------------------------------------------------------
# generate_badge_url
# ---------------------------------------------------------------------------


class TestGenerateBadgeUrl:
    """Tests for the full URL generation."""

    _SIMPLE_RESULTS = [
        {
            "id": "OSPS-AC-01.01",
            "status": "PASS",
            "details": "GitHub org enforces 2FA",
        },
        {
            "id": "OSPS-AC-03.01",
            "status": "FAIL",
            "details": "Branch protection not enabled on main",
        },
    ]

    def test_url_starts_with_badge_base(self):
        output = generate_badge_url(self._SIMPLE_RESULTS, "https://github.com/example/repo")
        assert BADGE_BASE_URL in output

    def test_url_contains_as_edit(self):
        output = generate_badge_url(self._SIMPLE_RESULTS, "https://github.com/example/repo")
        assert "as=edit" in output

    def test_url_contains_encoded_project_url(self):
        output = generate_badge_url(self._SIMPLE_RESULTS, "https://github.com/example/repo")
        assert "github.com" in output
        assert "example" in output

    def test_url_contains_status_params(self):
        output = generate_badge_url(self._SIMPLE_RESULTS, "https://github.com/example/repo")
        assert "osps_ac_01_01_status=Met" in output
        assert "osps_ac_03_01_status=Unmet" in output

    def test_url_contains_justification_for_pass(self):
        output = generate_badge_url(self._SIMPLE_RESULTS, "https://github.com/example/repo")
        assert "osps_ac_01_01_justification=" in output

    def test_url_contains_justification_for_fail(self):
        output = generate_badge_url(self._SIMPLE_RESULTS, "https://github.com/example/repo")
        assert "osps_ac_03_01_justification=" in output

    # --- Justification policy: only Met/Unmet get justification -------------

    def test_warn_result_has_no_justification(self):
        """WARN maps to ? and must never include a justification param."""
        results = [{"id": "OSPS-VM-01.01", "status": "WARN", "details": "Could not verify"}]
        output = generate_badge_url(results, "https://github.com/example/repo")
        assert "osps_vm_01_01_status=%3F" in output or "osps_vm_01_01_status=?" in output
        assert "osps_vm_01_01_justification" not in output

    def test_na_result_has_no_justification(self):
        """NA maps to N/A and must never include a justification param."""
        results = [{"id": "OSPS-BR-04.01", "status": "NA", "details": "Not applicable"}]
        output = generate_badge_url(results, "https://github.com/example/repo")
        assert "osps_br_04_01_justification" not in output

    def test_warn_status_string_na_has_no_justification(self):
        """N/A status also suppresses justification."""
        results = [{"id": "OSPS-BR-04.01", "status": "N/A", "details": "Not applicable"}]
        output = generate_badge_url(results, "https://github.com/example/repo")
        assert "osps_br_04_01_justification" not in output

    # --- URL budget cap ------------------------------------------------------

    def test_url_within_6kb_budget(self):
        """Total URL must never exceed the 6 KB budget."""
        many_results = [
            {
                "id": f"OSPS-AC-{i:02d}.01",
                "status": "FAIL",
                "details": "X" * 600,  # each detail is 600 chars before truncation
            }
            for i in range(1, 30)
        ]
        output = generate_badge_url(many_results, "https://github.com/example/repo")
        url_line = [line for line in output.splitlines() if line.startswith("https://")][-1]
        assert len(url_line.encode()) <= 6 * 1024

    def test_all_status_params_present_even_when_budget_exhausted(self):
        """Even when the budget is exhausted, every _status param must appear."""
        many_results = [
            {
                "id": f"OSPS-AC-{i:02d}.01",
                "status": "FAIL",
                "details": "X" * 600,
            }
            for i in range(1, 30)
        ]
        output = generate_badge_url(many_results, "https://github.com/example/repo")
        for i in range(1, 30):
            assert f"osps_ac_{i:02d}_01_status=Unmet" in output

    # --- Other edge cases ----------------------------------------------------

    def test_empty_results_still_returns_url(self):
        output = generate_badge_url([], "https://github.com/example/repo")
        assert BADGE_BASE_URL in output
        assert "as=edit" in output

    def test_no_project_url_shows_warning(self):
        output = generate_badge_url(self._SIMPLE_RESULTS, "")
        assert "⚠️" in output

    def test_no_project_url_no_url_param(self):
        """When project_url is empty, the url= query param should be absent."""
        output = generate_badge_url([], "")
        url_line = [line for line in output.splitlines() if line.startswith("https://")][-1]
        assert "as=edit" in url_line
        assert "url=" not in url_line

    def test_justification_truncated_at_500_chars(self):
        long_details = "A" * 600
        results = [{"id": "OSPS-AC-01.01", "status": "PASS", "details": long_details}]
        output = generate_badge_url(results, "https://github.com/example/repo")
        assert "…" in output or "%E2%80%A6" in output  # ellipsis or its URL-encoded form

    def test_result_missing_details_no_justification_param(self):
        results = [{"id": "OSPS-AC-01.01", "status": "PASS"}]
        output = generate_badge_url(results, "https://github.com/example/repo")
        assert "osps_ac_01_01_status=Met" in output
        assert "osps_ac_01_01_justification" not in output

    def test_result_with_empty_details_no_justification_param(self):
        results = [{"id": "OSPS-AC-01.01", "status": "PASS", "details": "  "}]
        output = generate_badge_url(results, "https://github.com/example/repo")
        assert "osps_ac_01_01_justification" not in output

    def test_markdown_header_present(self):
        output = generate_badge_url(self._SIMPLE_RESULTS, "https://github.com/example/repo")
        assert "Best Practices Badge" in output

    def test_result_with_missing_id_skipped(self):
        results = [
            {"status": "PASS", "details": "No ID"},
            {"id": "OSPS-AC-01.01", "status": "PASS", "details": "Has ID"},
        ]
        output = generate_badge_url(results, "https://github.com/example/repo")
        assert "osps_ac_01_01_status=Met" in output
        assert output.count("_status=") == 1

    def test_result_with_missing_status_skipped(self):
        results = [
            {"id": "OSPS-AC-01.01", "details": "No status"},
            {"id": "OSPS-AC-03.01", "status": "FAIL"},
        ]
        output = generate_badge_url(results, "https://github.com/example/repo")
        assert "osps_ac_03_01_status=Unmet" in output
        assert output.count("_status=") == 1


# ---------------------------------------------------------------------------
# Integration: import from package __init__
# ---------------------------------------------------------------------------


def test_badge_exports_available_from_formatters_package():
    """Ensure the badge symbols are re-exported from the formatters package."""
    assert callable(_gbu)
    assert callable(_ctk)
    assert callable(_stbs)
    assert isinstance(_BADGE_BASE_URL, str)
    assert "bestpractices.dev" in _BADGE_BASE_URL
