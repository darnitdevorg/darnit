"""Backend tests for `local-fs` outside-repo store variants (feature 034).

Phase 3 T009 covers `LocalFsAttestationStore`. Phase 4 T018/T019 append
`TestLocalFsReport` and `TestLocalFsAuditCache` to this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.stores.defaults.local_fs import (
    LocalFsAttestationStore,
    LocalFsAuditCacheStore,
    LocalFsReportStore,
)
from darnit.stores.errors import StoreOperationError


class TestLocalFsAttestation:
    """T009 cases (a)..(e). Verifies the write path, sanitization, error
    surface shape (SC-008), and construction-time failure on missing envvar.
    """

    def test_round_trip_write_and_read_back(self, tmp_path: Path) -> None:
        store = LocalFsAttestationStore(root=tmp_path)
        payload = b'{"foo": 1}'
        store.write("acme-widget", payload, "application/vnd.in-toto+json")
        target = tmp_path / "acme-widget.intoto.json"
        assert target.exists()
        assert target.read_bytes() == payload

    def test_content_type_to_extension_mapping(self, tmp_path: Path) -> None:
        store = LocalFsAttestationStore(root=tmp_path)
        store.write("a", b"x", "application/vnd.in-toto+json")
        store.write("b", b"x", "application/vnd.dev.sigstore.bundle+json")
        store.write("c", b"x", "application/octet-stream")  # unknown -> .bin
        assert (tmp_path / "a.intoto.json").exists()
        assert (tmp_path / "b.sigstore.json").exists()
        assert (tmp_path / "c.bin").exists()

    def test_path_traversal_sanitization_stays_under_root(
        self, tmp_path: Path
    ) -> None:
        """SC-005: `bundle_id = "../../etc/foo"` MUST NOT escape `root`.

        Assertion is two-part per F2 remediation: the on-disk file is a
        direct child of `resolved_root`, and `resolved_root` is a parent
        of the actual path when both are resolved.
        """
        store = LocalFsAttestationStore(root=tmp_path)
        malicious = "../../etc/foo"
        store.write(malicious, b"payload", "application/vnd.in-toto+json")

        # Sanitized filename must have no path separators.
        expected_name = ".._.._etc_foo.intoto.json"
        target = tmp_path / expected_name
        assert target.exists(), (
            f"expected file at {target}; got: {list(tmp_path.iterdir())}"
        )

        # Escape-parent check: the actual file lives INSIDE the resolved root.
        resolved_root = tmp_path.resolve()
        actual = target.resolve()
        assert resolved_root in actual.parents or resolved_root == actual.parent, (
            f"path traversal: {actual} escaped {resolved_root}"
        )

    def test_unwritable_root_raises_with_full_error_context(
        self, tmp_path: Path
    ) -> None:
        """SC-008 (per F2 remediation): the raised StoreOperationError's
        message MUST contain the backend name, the artifact kind, and
        the resolved absolute path. Not just "some OSError happened"."""
        # Make root unwritable by creating a read-only parent dir and
        # pointing root inside a subdirectory that doesn't exist yet
        # (so mkdir(parents=True) triggers PermissionError).
        readonly_parent = tmp_path / "readonly"
        readonly_parent.mkdir()
        readonly_parent.chmod(0o500)  # r-x -- no write

        target_root = readonly_parent / "attestations"
        store = LocalFsAttestationStore(root=str(target_root))

        try:
            with pytest.raises(StoreOperationError) as exc_info:
                store.write(
                    "acme-widget",
                    b"{}",
                    "application/vnd.in-toto+json",
                )
            msg = str(exc_info.value)
            # SC-008: backend name, artifact kind, and resolved path
            assert "local-fs" in msg, f"missing backend in error: {msg!r}"
            assert "attestation" in msg, f"missing kind in error: {msg!r}"
            # Resolved path -- either the store root or the target file.
            # We include the target file in the wrapper, so assert that.
            assert str(target_root.resolve()) in msg, (
                f"missing resolved path in error: {msg!r}"
            )
        finally:
            # Restore perms so pytest can clean up.
            readonly_parent.chmod(0o700)

    def test_missing_env_var_raises_at_construction_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Case (e): env-var typo raises KeyError at __init__, not lazily
        at write time. Fail-fast contract from research R-003."""
        monkeypatch.delenv("DARNIT_TEST_MISSING_ROOT", raising=False)
        with pytest.raises(KeyError):
            LocalFsAttestationStore(root="$DARNIT_TEST_MISSING_ROOT/x")

    def test_env_var_present_resolves_correctly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("DARNIT_TEST_ATT_ROOT", str(tmp_path))
        store = LocalFsAttestationStore(root="$DARNIT_TEST_ATT_ROOT/atts")
        store.write("id-1", b"payload", "application/vnd.in-toto+json")
        assert (tmp_path / "atts" / "id-1.intoto.json").exists()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        store = LocalFsAttestationStore(root=tmp_path)
        store.close()
        store.close()


class TestLocalFsReport:
    """T018: parametric per-format coverage for `LocalFsReportStore`."""

    def test_round_trip_markdown(self, tmp_path: Path) -> None:
        store = LocalFsReportStore(root=tmp_path)
        store.write_markdown("run-1", "# Title\n\nBody.")
        target = tmp_path / "run-1.md"
        assert target.exists()
        assert target.read_text() == "# Title\n\nBody."

    def test_round_trip_json(self, tmp_path: Path) -> None:
        store = LocalFsReportStore(root=tmp_path)
        store.write_json("run-1", '{"summary": {}}')
        target = tmp_path / "run-1.json"
        assert target.exists()
        assert target.read_text() == '{"summary": {}}'

    def test_round_trip_sarif(self, tmp_path: Path) -> None:
        store = LocalFsReportStore(root=tmp_path)
        store.write_sarif("run-1", '{"$schema":"sarif"}')
        target = tmp_path / "run-1.sarif"
        assert target.exists()

    def test_report_id_sanitized_no_directory_escape(
        self, tmp_path: Path
    ) -> None:
        """Same escape-parent shape as T009 (c)."""
        store = LocalFsReportStore(root=tmp_path)
        store.write_json("../../etc/foo", "{}")
        # Sanitized: forward slashes -> _, dots kept
        expected = tmp_path / ".._.._etc_foo.json"
        assert expected.exists()
        resolved_root = tmp_path.resolve()
        assert resolved_root == expected.resolve().parent

    def test_unwritable_root_raises_with_local_fs_context(
        self, tmp_path: Path
    ) -> None:
        readonly_parent = tmp_path / "readonly-r"
        readonly_parent.mkdir()
        readonly_parent.chmod(0o500)
        target_root = readonly_parent / "reports"
        store = LocalFsReportStore(root=str(target_root))
        try:
            with pytest.raises(StoreOperationError) as exc_info:
                store.write_markdown("r1", "# body")
            msg = str(exc_info.value)
            assert "local-fs" in msg
            assert "report:markdown" in msg
        finally:
            readonly_parent.chmod(0o700)


# T019: NOT parallelizable with T018 (same file). Serialized after T018.
class TestLocalFsAuditCache:
    """T019: cache round-trip, best-effort semantics, path safety."""

    def test_write_then_read_round_trip(self, tmp_path: Path) -> None:
        store = LocalFsAuditCacheStore(root=tmp_path)
        envelope = {"version": 1, "summary": {"PASS": 5}}
        store.write("acme-repo-hash", envelope)
        assert store.read("acme-repo-hash") == envelope

    def test_read_miss_returns_none_not_error(self, tmp_path: Path) -> None:
        store = LocalFsAuditCacheStore(root=tmp_path)
        assert store.read("does-not-exist") is None

    def test_write_to_unwritable_root_swallowed_best_effort(
        self, tmp_path: Path
    ) -> None:
        """Best-effort per Protocol: cache write MUST NOT raise. On
        failure, subsequent read returns None."""
        readonly_parent = tmp_path / "readonly-c"
        readonly_parent.mkdir()
        readonly_parent.chmod(0o500)
        target_root = readonly_parent / "cache"
        try:
            store = LocalFsAuditCacheStore(root=str(target_root))
            # Must not raise.
            store.write("k1", {"x": 1})
            # Read must return None (write didn't succeed).
            assert store.read("k1") is None
        finally:
            readonly_parent.chmod(0o700)

    def test_tempfile_lives_in_target_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cross-fs atomic write safety: `mkstemp` MUST use `dir=<target parent>`,
        not a system tempdir. Verified by capturing the dir arg."""
        import tempfile

        captured = {}
        original = tempfile.mkstemp

        def spy_mkstemp(*args, **kwargs):
            captured["dir"] = kwargs.get("dir")
            return original(*args, **kwargs)

        monkeypatch.setattr(tempfile, "mkstemp", spy_mkstemp)

        store = LocalFsAuditCacheStore(root=tmp_path)
        store.write("k", {"x": 1})
        # `dir` argument to mkstemp is `str(target.parent)` == str(tmp_path).
        assert captured["dir"] == str(tmp_path.resolve())
