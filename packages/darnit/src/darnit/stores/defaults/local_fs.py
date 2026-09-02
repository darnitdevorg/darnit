"""Outside-repo filesystem-backed store variants (feature 034).

Complements the in-repo :mod:`~darnit.stores.defaults.attestation`,
:mod:`~darnit.stores.defaults.report`, :mod:`~darnit.stores.defaults.cache`,
and :mod:`~darnit.stores.defaults.project` defaults from feature 033.
Each ``LocalFs*Store`` here takes a config-driven ``root`` (absolute,
``~``-relative, or ``$VAR``-templated) and delegates I/O to the matching
in-repo class.

Concrete classes are defined in later phases; this module ships the
shared helpers first (T003):

* :func:`_resolve_root_config` -- runs the R-003 chain
  (``$VAR`` interpolation with ``missing="raise"``, ``~`` expansion,
  absolute ``resolve()``).
* :func:`_log_wrote` -- emits the one-line INFO message required by
  FR-015 for every successful outside-repo write.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from darnit.core.env_subst import substitute_dollar_vars
from darnit.core.logging import get_logger
from darnit.stores.errors import StoreOperationError

from .attestation import (
    _CONTENT_TYPE_EXT,
    FilesystemAttestationStore,
    _sanitize_filename,
)
from .cache import FilesystemAuditCacheStore
from .report import FilesystemReportStore

# `get_logger("stores.local")` prefixes with "darnit." internally,
# yielding the fully-qualified logger name `darnit.stores.local`.
_LOCAL_LOGGER_NAME = "darnit.stores.local"
logger = get_logger("stores.local")


def _resolve_root_config(root: str | Path) -> Path:
    """Turn a raw ``root`` config value into an absolute :class:`~pathlib.Path`.

    Applied in order (data-model E-001, research R-003):

    1. If ``root`` is already a :class:`~pathlib.Path`, return it as-is
       (test-only shortcut).
    2. ``substitute_dollar_vars(root, missing="raise")`` -- a typo in
       a ``$VAR`` reference is a hard :class:`KeyError` at construction,
       not a silent empty expansion (research R-003).
    3. :func:`os.path.expanduser` -- expand ``~`` and ``~user``.
    4. :meth:`~pathlib.Path.resolve` -- to canonical absolute form for
       I/O and for logging.

    Directory creation is deferred to first write (matches the
    in-repo defaults from feature 033).
    """
    if isinstance(root, Path):
        return root
    if not isinstance(root, str):
        raise TypeError(
            f"root must be str or pathlib.Path, got {type(root).__name__}"
        )
    substituted = substitute_dollar_vars(root, missing="raise")
    expanded = os.path.expanduser(substituted)
    return Path(expanded).resolve()


def _log_wrote(kind_tag: str, backend: str, resolved_path: Path) -> None:
    """Emit the FR-015 info log line for a successful outside-repo write.

    Args:
        kind_tag: ``"attestation"``, ``"report:markdown"`` |
            ``"report:json"`` | ``"report:sarif"``, or ``"cache"``.
        backend: ``"local-fs"`` or ``"user-local"``.
        resolved_path: The absolute on-disk path the artifact was written to.
    """
    logger.info("wrote %s (%s): %s", kind_tag, backend, str(resolved_path))


class LocalFsAttestationStore:
    """``AttestationStore`` variant writing to a config-driven ``root``.

    Delegates I/O to :class:`FilesystemAttestationStore` after resolving
    ``root`` via :func:`_resolve_root_config`. Wraps the delegate's
    ``StoreOperationError`` with additional context (backend name,
    artifact kind, resolved target path) so SC-008's error surface
    contract is satisfied. Emits the FR-015 info log line after every
    successful write.
    """

    _BACKEND_NAME = "local-fs"
    _KIND_TAG = "attestation"

    def __init__(self, root: str | Path, **_: object) -> None:
        self._root = _resolve_root_config(root)
        self._delegate = FilesystemAttestationStore(self._root)

    def _target_for(self, bundle_id: str, content_type: str) -> Path:
        ext = _CONTENT_TYPE_EXT.get(content_type, ".bin")
        return self._root / f"{_sanitize_filename(bundle_id)}{ext}"

    def write(
        self, bundle_id: str, bundle_bytes: bytes, content_type: str
    ) -> None:
        target = self._target_for(bundle_id, content_type)
        try:
            self._delegate.write(bundle_id, bundle_bytes, content_type)
        except StoreOperationError as err:
            raise StoreOperationError(
                f"[{self._BACKEND_NAME} {self._KIND_TAG} @ {target}] {err}"
            ) from err
        _log_wrote(self._KIND_TAG, self._BACKEND_NAME, target)

    def close(self) -> None:
        self._delegate.close()


class LocalFsReportStore:
    """``ReportStore`` variant writing to a config-driven ``root``.

    Delegates to :class:`FilesystemReportStore` after root resolution.
    Emits one FR-015 info log per format written (`report:markdown`,
    `report:json`, `report:sarif`) so multi-format audit runs are
    self-documenting.
    """

    _BACKEND_NAME = "local-fs"

    def __init__(self, root: str | Path, **_: object) -> None:
        self._root = _resolve_root_config(root)
        self._delegate = FilesystemReportStore(self._root)

    def _target_for(self, report_id: str, ext: str) -> Path:
        return self._root / f"{_sanitize_filename(report_id)}{ext}"

    def _write(self, report_id: str, ext: str, content: str, tag: str) -> None:
        target = self._target_for(report_id, ext)
        try:
            self._delegate._write(report_id, ext, content)
        except StoreOperationError as err:
            raise StoreOperationError(
                f"[{self._BACKEND_NAME} {tag} @ {target}] {err}"
            ) from err
        _log_wrote(tag, self._BACKEND_NAME, target)

    def write_markdown(self, report_id: str, content: str) -> None:
        self._write(report_id, ".md", content, "report:markdown")

    def write_json(self, report_id: str, content: str) -> None:
        self._write(report_id, ".json", content, "report:json")

    def write_sarif(self, report_id: str, content: str) -> None:
        self._write(report_id, ".sarif", content, "report:sarif")

    def close(self) -> None:
        self._delegate.close()


class LocalFsAuditCacheStore:
    """``AuditCacheStore`` variant writing to a config-driven ``root``.

    Delegates to :class:`FilesystemAuditCacheStore` after root resolution.
    Best-effort per the Protocol contract: `write` MUST NOT raise on
    backend failure. The info log line is only emitted when the write
    actually succeeded (i.e., the target file exists post-write); a
    swallowed failure produces no info-level log line, matching FR-015's
    "successful write" clause.
    """

    _BACKEND_NAME = "local-fs"
    _KIND_TAG = "cache"

    def __init__(self, root: str | Path, **_: object) -> None:
        self._root = _resolve_root_config(root)
        self._delegate = FilesystemAuditCacheStore(self._root)

    def _target_for(self, cache_key: str) -> Path:
        return self._root / f"{_sanitize_filename(cache_key)}.json"

    def read(self, cache_key: str) -> dict[str, Any] | None:
        return self._delegate.read(cache_key)

    def write(self, cache_key: str, envelope: dict[str, Any]) -> None:
        target = self._target_for(cache_key)
        self._delegate.write(cache_key, envelope)
        # FR-015: log only on successful write. Delegate swallows OSError
        # to a warning; check post-write whether the file actually landed.
        if target.exists():
            _log_wrote(self._KIND_TAG, self._BACKEND_NAME, target)

    def close(self) -> None:
        self._delegate.close()


__all__ = [
    "LocalFsAttestationStore",
    "LocalFsAuditCacheStore",
    "LocalFsReportStore",
]
