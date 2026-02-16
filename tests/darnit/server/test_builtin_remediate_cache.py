"""Tests for builtin_remediate audit cache integration.

Verifies that builtin_remediate:
- Uses cached audit results when available (cache hit)
- Falls back to running audit when cache is missing (cache miss)
- Excludes PASS controls from remediation plan
- Preserves cache on dry run
- Invalidates cache after non-dry-run remediation
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def cached_results():
    """Cache envelope with mixed PASS/FAIL results."""
    return {
        "version": 1,
        "timestamp": "2026-02-16T12:00:00Z",
        "commit": "abc123",
        "commit_dirty": False,
        "level": 3,
        "framework": "openssf-baseline",
        "results": [
            {"id": "OSPS-AC-01.01", "status": "PASS", "details": "OK", "level": 1},
            {"id": "OSPS-DO-02.01", "status": "FAIL", "details": "Missing", "level": 1},
            {"id": "OSPS-GV-01.01", "status": "FAIL", "details": "Missing", "level": 1},
            {"id": "OSPS-VM-01.01", "status": "WARN", "details": "Manual", "level": 1},
        ],
        "summary": {"PASS": 1, "FAIL": 2, "WARN": 1, "N/A": 0, "ERROR": 0, "total": 4},
    }


def _make_mock_control(control_id: str):
    ctrl = MagicMock()
    ctrl.control_id = control_id
    ctrl.name = f"Control {control_id}"
    ctrl.description = f"Description for {control_id}"
    return ctrl


def _make_common_patches(cache_return, controls):
    """Return a dict of patches for the function's lazy imports."""
    mock_fw = MagicMock()
    mock_fw.controls = {}
    mock_fw.templates = {}

    mock_config = MagicMock()
    mock_config.framework = mock_fw

    mock_impl = MagicMock()
    mock_impl.name = "openssf-baseline"
    mock_impl.get_framework_config_path.return_value = None

    return {
        # Patch at the source module since builtin_remediate uses lazy imports
        "darnit.core.audit_cache.read_audit_cache": MagicMock(return_value=cache_return),
        "darnit.core.audit_cache.invalidate_audit_cache": MagicMock(),
        "darnit.config.load_effective_config_by_name": MagicMock(return_value=mock_config),
        "darnit.config.load_controls_from_effective": MagicMock(return_value=controls),
        "darnit.core.discovery.get_implementation": MagicMock(return_value=mock_impl),
        "darnit.sieve.registry.get_control_registry": MagicMock(
            return_value=MagicMock(get_all_specs=MagicMock(return_value=[]))
        ),
        "darnit.core.utils.detect_owner_repo": MagicMock(return_value=("testorg", "testrepo")),
    }


class TestCacheHit:

    @pytest.mark.asyncio
    async def test_cache_hit_skips_audit(self, tmp_path, cached_results):
        """With a cache hit, SieveOrchestrator.verify() should NOT be called."""
        controls = [_make_mock_control("OSPS-DO-02.01")]
        patches = _make_common_patches(cached_results, controls)

        mock_orchestrator = MagicMock()
        patches["darnit.sieve.SieveOrchestrator"] = MagicMock(return_value=mock_orchestrator)

        with patch.dict("sys.modules", {}):  # clear stale module cache
            pass

        patchers = [patch(k, v) for k, v in patches.items()]
        for p in patchers:
            p.start()
        try:
            from darnit.server.tools.builtin_remediate import builtin_remediate

            await builtin_remediate(
                local_path=str(tmp_path),
                dry_run=True,
                _framework_name="openssf-baseline",
            )
            # SieveOrchestrator should NOT have been called (cache hit path)
            mock_orchestrator.verify.assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_pass_controls_excluded(self, tmp_path, cached_results):
        """PASS controls from cache should NOT appear in remediation output."""
        controls = [
            _make_mock_control("OSPS-AC-01.01"),
            _make_mock_control("OSPS-DO-02.01"),
        ]
        patches = _make_common_patches(cached_results, controls)
        patchers = [patch(k, v) for k, v in patches.items()]
        for p in patchers:
            p.start()
        try:
            from darnit.server.tools.builtin_remediate import builtin_remediate

            result = await builtin_remediate(
                local_path=str(tmp_path),
                dry_run=True,
                _framework_name="openssf-baseline",
            )
            # OSPS-AC-01.01 is PASS — should NOT appear in remediation
            assert "OSPS-AC-01.01" not in result
        finally:
            for p in patchers:
                p.stop()


class TestCacheMiss:

    @pytest.mark.asyncio
    async def test_cache_miss_runs_audit(self, tmp_path):
        """With no cache, SieveOrchestrator.verify() should be called."""
        controls = [_make_mock_control("OSPS-DO-02.01")]
        patches = _make_common_patches(None, controls)  # None = cache miss

        mock_verify_result = MagicMock()
        mock_verify_result.status = "FAIL"
        mock_orchestrator = MagicMock()
        mock_orchestrator.verify.return_value = mock_verify_result
        patches["darnit.sieve.SieveOrchestrator"] = MagicMock(return_value=mock_orchestrator)

        patchers = [patch(k, v) for k, v in patches.items()]
        for p in patchers:
            p.start()
        try:
            from darnit.server.tools.builtin_remediate import builtin_remediate

            await builtin_remediate(
                local_path=str(tmp_path),
                dry_run=True,
                _framework_name="openssf-baseline",
            )
            mock_orchestrator.verify.assert_called()
        finally:
            for p in patchers:
                p.stop()


class TestCacheInvalidation:

    @pytest.mark.asyncio
    async def test_dry_run_preserves_cache(self, tmp_path, cached_results):
        """Dry run should NOT invalidate cache."""
        controls = [_make_mock_control("OSPS-DO-02.01")]
        patches = _make_common_patches(cached_results, controls)
        invalidate_mock = patches["darnit.core.audit_cache.invalidate_audit_cache"]

        patchers = [patch(k, v) for k, v in patches.items()]
        for p in patchers:
            p.start()
        try:
            from darnit.server.tools.builtin_remediate import builtin_remediate

            await builtin_remediate(
                local_path=str(tmp_path),
                dry_run=True,
                _framework_name="openssf-baseline",
            )
            invalidate_mock.assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_non_dry_run_invalidates_cache(self, tmp_path, cached_results):
        """Non-dry-run with applied remediations should invalidate cache."""
        controls = [_make_mock_control("OSPS-DO-02.01")]
        patches = _make_common_patches(cached_results, controls)

        # Set up executor to report success
        mock_exec_result = MagicMock()
        mock_exec_result.success = True
        mock_exec_result.control_id = "OSPS-DO-02.01"
        mock_exec_result.message = "Created file"

        mock_executor = MagicMock()
        mock_executor.execute.return_value = mock_exec_result
        patches["darnit.remediation.executor.RemediationExecutor"] = MagicMock(
            return_value=mock_executor
        )

        # Need fw.controls with a remediation config for DO-02.01
        mock_rem_cfg = MagicMock()
        mock_rem_cfg.file_create = [MagicMock()]
        mock_rem_cfg.exec = None
        mock_rem_cfg.api_call = None
        mock_rem_cfg.handler = None
        mock_rem_cfg.project_update = None

        mock_control_cfg = MagicMock()
        mock_control_cfg.remediation = mock_rem_cfg

        mock_fw = MagicMock()
        mock_fw.controls = {"OSPS-DO-02.01": mock_control_cfg}
        mock_fw.templates = {}

        mock_config = MagicMock()
        mock_config.framework = mock_fw
        patches["darnit.config.load_effective_config_by_name"] = MagicMock(
            return_value=mock_config
        )

        invalidate_mock = patches["darnit.core.audit_cache.invalidate_audit_cache"]

        patchers = [patch(k, v) for k, v in patches.items()]
        for p in patchers:
            p.start()
        try:
            from darnit.server.tools.builtin_remediate import builtin_remediate

            await builtin_remediate(
                local_path=str(tmp_path),
                dry_run=False,
                _framework_name="openssf-baseline",
            )
            invalidate_mock.assert_called_once()
        finally:
            for p in patchers:
                p.stop()
