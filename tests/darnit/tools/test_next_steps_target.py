"""Tests verifying Next Steps receives and forwards target and repository identity (#664)."""

from unittest.mock import patch

from darnit.tools.audit import _get_next_steps_section, format_results_markdown, summarize_results


def test_get_next_steps_section_forwards_target():
    with patch("darnit.config.context_storage.get_pending_context") as mock_get_pending:
        mock_get_pending.return_value = []
        _get_next_steps_section(
            "/path/to/repo", {"FAIL": 1}, owner="acme", repo="widget", target="github.com/acme/widget"
        )
        mock_get_pending.assert_called_once_with(
            "/path/to/repo", owner="acme", repo="widget", target="github.com/acme/widget"
        )


def test_get_next_steps_section_derives_target_from_owner_repo():
    with patch("darnit.config.context_storage.get_pending_context") as mock_get_pending:
        mock_get_pending.return_value = []
        _get_next_steps_section("/path/to/repo", {"FAIL": 1}, owner="acme", repo="widget")
        mock_get_pending.assert_called_once_with(
            "/path/to/repo", owner="acme", repo="widget", target="github.com/acme/widget"
        )


def test_format_results_markdown_forwards_target_to_next_steps():
    with patch("darnit.tools.audit._get_next_steps_section") as mock_next_steps:
        mock_next_steps.return_value = ["## Next Steps", "Do something"]
        summary = summarize_results([])
        summary["FAIL"] = 1
        format_results_markdown(
            owner="acme",
            repo="widget",
            results=[],
            summary=summary,
            compliance={1: False},
            level=1,
            local_path="/path/to/repo",
            target="github.com/acme/widget",
        )
        mock_next_steps.assert_called_once_with(
            "/path/to/repo", summary, owner="acme", repo="widget", target="github.com/acme/widget"
        )


def test_format_results_markdown_derives_target_from_audit_metadata():
    with patch("darnit.tools.audit._get_next_steps_section") as mock_next_steps:
        mock_next_steps.return_value = []
        summary = summarize_results([])
        format_results_markdown(
            owner="",
            repo="",
            results=[],
            summary=summary,
            compliance={1: True},
            level=1,
            local_path="/path/to/repo",
            audit_metadata={"trust": {"repository": "gitlab.example.com/team/app"}},
        )
        mock_next_steps.assert_called_once_with(
            "/path/to/repo", summary, owner="", repo="", target="gitlab.example.com/team/app"
        )
