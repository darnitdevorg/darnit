"""Tests for the EchoCheckAdapter."""

from pathlib import Path

from darnit.core.models import CheckStatus
from darnit_plugins.adapters.echo import EchoCheckAdapter


class TestEchoAdapterBasics:
    """Basic adapter functionality tests."""

    def test_adapter_name(self):
        """Should return correct name."""
        adapter = EchoCheckAdapter()
        assert adapter.name() == "echo"

    def test_adapter_capabilities(self):
        """Should support any control (wildcard)."""
        adapter = EchoCheckAdapter()
        caps = adapter.capabilities()

        assert "*" in caps.control_ids
        assert caps.supports_batch is True

    def test_supports_any_control(self):
        """Should handle any control ID."""
        adapter = EchoCheckAdapter()

        assert adapter.supports_control("ANY-CTRL-01")
        assert adapter.supports_control("OSPS-VM-05.02")
        assert adapter.supports_control("CUSTOM-TEST-123")


class TestEchoAdapterCheck:
    """Tests for check() method."""

    def test_default_pass(self, temp_repo: Path):
        """Should return PASS by default."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {})

        assert result.control_id == "TEST-001"
        assert result.status == CheckStatus.PASS
        assert result.source == "echo"

    def test_configured_pass(self, temp_repo: Path):
        """Should return PASS when configured."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {
            "status": "PASS",
            "message": "All good!",
        })

        assert result.status == CheckStatus.PASS
        assert result.message == "All good!"

    def test_configured_fail(self, temp_repo: Path):
        """Should return FAIL when configured."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {
            "status": "FAIL",
            "message": "Something wrong",
        })

        assert result.status == CheckStatus.FAIL
        assert result.message == "Something wrong"

    def test_configured_error(self, temp_repo: Path):
        """Should return ERROR when configured."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {
            "status": "ERROR",
        })

        assert result.status == CheckStatus.ERROR

    def test_configured_warn(self, temp_repo: Path):
        """Should return WARN when configured."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {
            "status": "WARN",
        })

        assert result.status == CheckStatus.WARN

    def test_configured_na(self, temp_repo: Path):
        """Should return NA when configured."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {
            "status": "NA",
        })

        assert result.status == CheckStatus.NA

    def test_invalid_status(self, temp_repo: Path):
        """Should return ERROR for invalid status."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {
            "status": "INVALID",
        })

        assert result.status == CheckStatus.ERROR

    def test_custom_level(self, temp_repo: Path):
        """Should use configured level."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {
            "level": 3,
        })

        assert result.level == 3

    def test_default_level(self, temp_repo: Path):
        """Should default to level 1."""
        adapter = EchoCheckAdapter()
        result = adapter.check("TEST-001", "", "", str(temp_repo), {})

        assert result.level == 1

    def test_custom_default_status(self, temp_repo: Path):
        """Should use custom default status."""
        adapter = EchoCheckAdapter(default_status="FAIL")
        result = adapter.check("TEST-001", "", "", str(temp_repo), {})

        assert result.status == CheckStatus.FAIL


class TestEchoAdapterBatch:
    """Tests for check_batch() method."""

    def test_batch_check(self, temp_repo: Path):
        """Should check multiple controls."""
        adapter = EchoCheckAdapter()
        results = adapter.check_batch(
            ["TEST-001", "TEST-002", "TEST-003"],
            "",
            "",
            str(temp_repo),
            {"status": "PASS"},
        )

        assert len(results) == 3
        assert all(r.status == CheckStatus.PASS for r in results)
        assert [r.control_id for r in results] == ["TEST-001", "TEST-002", "TEST-003"]

    def test_batch_empty(self, temp_repo: Path):
        """Should handle empty control list."""
        adapter = EchoCheckAdapter()
        results = adapter.check_batch([], "", "", str(temp_repo), {})

        assert len(results) == 0
