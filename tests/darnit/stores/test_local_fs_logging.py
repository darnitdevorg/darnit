"""FR-015 / SC-009 log-line assertions for outside-repo backends.

Every successful outside-repo write emits exactly one info-level line
to logger `darnit.stores.local` naming the kind, backend, and resolved
path. The in-repo `Filesystem*Store` classes emit ZERO lines to this
logger (zero-config exemption).
"""

from __future__ import annotations

import logging
from pathlib import Path

from darnit.stores.defaults.attestation import FilesystemAttestationStore
from darnit.stores.defaults.cache import FilesystemAuditCacheStore
from darnit.stores.defaults.local_fs import (
    LocalFsAttestationStore,
    LocalFsAuditCacheStore,
    LocalFsReportStore,
)
from darnit.stores.defaults.report import FilesystemReportStore

_LOGGER = "darnit.stores.local"


class TestAttestationLogging:
    def test_one_info_line_per_write(
        self, tmp_path: Path, caplog
    ) -> None:
        store = LocalFsAttestationStore(root=tmp_path)
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            store.write("acme", b'{"x":1}', "application/vnd.in-toto+json")
        records = [r for r in caplog.records if r.name == _LOGGER]
        assert len(records) == 1
        assert records[0].levelno == logging.INFO

    def test_message_shape_names_kind_backend_and_path(
        self, tmp_path: Path, caplog
    ) -> None:
        store = LocalFsAttestationStore(root=tmp_path)
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            store.write("acme", b'{"x":1}', "application/vnd.in-toto+json")
        # Format is: "wrote {kind} ({backend}): {path}"
        msg = caplog.records[-1].getMessage()
        assert msg.startswith("wrote attestation (local-fs): ")
        # The resolved path in the message must be inside tmp_path.
        expected_target = str((tmp_path / "acme.intoto.json").resolve())
        assert expected_target in msg

    def test_filesystem_default_emits_zero_lines_to_local_logger(
        self, tmp_path: Path, caplog
    ) -> None:
        """SC-009 exemption: the pre-feature `FilesystemAttestationStore`
        must NOT emit to `darnit.stores.local`. Zero-config audits stay
        log-silent."""
        store = FilesystemAttestationStore(tmp_path)
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            store.write("acme", b'{"x":1}', "application/vnd.in-toto+json")
        records = [r for r in caplog.records if r.name == _LOGGER]
        assert records == []


class TestReportLogging:
    """T020: one info line per format written; three formats = three lines."""

    def test_each_format_emits_one_line(
        self, tmp_path: Path, caplog
    ) -> None:
        store = LocalFsReportStore(root=tmp_path)
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            store.write_markdown("run", "# a")
            store.write_json("run", "{}")
            store.write_sarif("run", "{}")
        records = [r for r in caplog.records if r.name == _LOGGER]
        tags = [r.getMessage().split(" ")[1] for r in records]
        assert tags == ["report:markdown", "report:json", "report:sarif"]

    def test_filesystem_default_report_zero_local_lines(
        self, tmp_path: Path, caplog
    ) -> None:
        store = FilesystemReportStore(tmp_path)
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            store.write_markdown("run", "# a")
        assert [r for r in caplog.records if r.name == _LOGGER] == []


class TestCacheLogging:
    """T020: cache write emits one info line on success, zero on best-
    effort failure (delegate's warning still fires but not to
    `darnit.stores.local`)."""

    def test_successful_write_emits_one_line(
        self, tmp_path: Path, caplog
    ) -> None:
        store = LocalFsAuditCacheStore(root=tmp_path)
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            store.write("k", {"x": 1})
        records = [r for r in caplog.records if r.name == _LOGGER]
        assert len(records) == 1
        assert records[0].getMessage().startswith("wrote cache (local-fs): ")

    def test_failed_write_emits_zero_info_lines(
        self, tmp_path: Path, caplog
    ) -> None:
        """Best-effort: swallowed OSError means no target file lands, so
        LocalFsAuditCacheStore's post-write `target.exists()` check
        skips the info log. Zero lines at INFO level on `darnit.stores.local`."""
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        readonly.chmod(0o500)
        try:
            store = LocalFsAuditCacheStore(root=str(readonly / "cache"))
            with caplog.at_level(logging.INFO, logger=_LOGGER):
                store.write("k", {"x": 1})
            records = [r for r in caplog.records if r.name == _LOGGER]
            assert records == []
        finally:
            readonly.chmod(0o700)

    def test_filesystem_default_cache_zero_local_lines(
        self, tmp_path: Path, caplog
    ) -> None:
        store = FilesystemAuditCacheStore(tmp_path)
        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            store.write("k", {"x": 1})
        assert [r for r in caplog.records if r.name == _LOGGER] == []
