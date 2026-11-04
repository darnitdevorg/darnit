"""Unit tests for community-spec custom handlers (darnit_csl.handlers)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from darnit_csl.handlers import csl_llm_if_present, register_handlers

from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)


@pytest.fixture
def clean_registry():
    """Ensure registry state is restored after tests."""
    registry = get_sieve_handler_registry()
    yield registry
    registry.set_plugin_context(None)


@pytest.mark.unit
class TestCslLlmIfPresent:
    """Tests for csl_llm_if_present gating logic."""

    def test_missing_files_to_include_key_fails(self, tmp_path: Path) -> None:
        ctx = HandlerContext(local_path=str(tmp_path))
        result = csl_llm_if_present({}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.message == "Required file is missing."

    def test_empty_files_to_include_list_fails(self, tmp_path: Path) -> None:
        ctx = HandlerContext(local_path=str(tmp_path))
        result = csl_llm_if_present({"files_to_include": []}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.message == "Required file is missing."

    def test_nonexistent_files_fails(self, tmp_path: Path) -> None:
        ctx = HandlerContext(local_path=str(tmp_path))
        result = csl_llm_if_present({"files_to_include": ["GOVERNANCE.md", "docs/GOVERNANCE.md"]}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.message == "Required file is missing."

    def test_file_outside_repository_fails(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        outside_file = tmp_path / "outside.md"
        outside_file.write_text("outside contents", encoding="utf-8")

        ctx = HandlerContext(local_path=str(repo_dir))
        result = csl_llm_if_present({"files_to_include": [str(outside_file)]}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.message == "Required file is missing."

    def test_present_relative_file_delegates_to_llm_eval(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        gov_file = repo_dir / "GOVERNANCE.md"
        gov_file.write_text("# Governance\nRules", encoding="utf-8")

        ctx = HandlerContext(local_path=str(repo_dir))
        expected_result = HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="LLM consultation required",
            details={"consultation": "pending"},
        )

        with patch("darnit_csl.handlers.llm_eval_handler", return_value=expected_result) as mock_llm:
            config = {"files_to_include": ["MISSING.md", "GOVERNANCE.md"], "prompt": "Check governance"}
            result = csl_llm_if_present(config, ctx)

            assert result == expected_result
            mock_llm.assert_called_once_with(config, ctx)

    def test_present_absolute_file_delegates_to_llm_eval(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        gov_file = repo_dir / "GOVERNANCE.md"
        gov_file.write_text("# Governance\nRules", encoding="utf-8")

        ctx = HandlerContext(local_path=str(repo_dir))
        mock_result = MagicMock()

        with patch("darnit_csl.handlers.llm_eval_handler", return_value=mock_result) as mock_llm:
            config = {"files_to_include": [str(gov_file)]}
            result = csl_llm_if_present(config, ctx)

            assert result == mock_result
            mock_llm.assert_called_once_with(config, ctx)


@pytest.mark.unit
class TestRegisterHandlers:
    """Tests for handler registration metadata and attributes."""

    def test_register_handlers_sets_expected_metadata(self, clean_registry) -> None:
        register_handlers()
        entry = clean_registry.get("csl_llm_if_present")
        assert entry is not None
        assert entry.phase == "llm"
        assert entry.ceiling == {"fail"}
        assert entry.plugin == "community-spec"
        assert "prompt" in entry.settings
        assert "files_to_include" in entry.settings
        assert entry.fn is csl_llm_if_present
