"""``user-local`` outside-repo store variants (feature 034 T025).

Extends the ``local-fs`` backends with platform-conventional root
resolution: XDG on Linux, Apple support/cache directories on macOS,
LOCALAPPDATA on Windows. Operators write::

    [stores.attestation]
    backend = "user-local"

and no ``root`` field is required. If they DO pass a ``root``, the
backend emits a warning and ignores it (per data-model E-002 warn-and-
ignore semantics, chosen over hard-error to reduce friction for
operators who copied a snippet from a ``local-fs`` example).

`user-local` is deliberately NOT registered under
`darnit.stores.project` (FR-009): `.project/project.yaml` stays in the
repo. `resolve_stores` raises `StoreNotInstalled` if the operator
writes `[stores.project] backend = "user-local"`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger

from .local_fs import (
    LocalFsAttestationStore,
    LocalFsAuditCacheStore,
    LocalFsReportStore,
    _log_wrote,
)
from .platform_paths import user_cache_root, user_data_root

logger = get_logger("stores.local")


def _warn_and_ignore_root(kwargs: dict[str, Any], resolved_root: Path) -> None:
    """If the caller passed a `root` kwarg, log a warning; the resolved
    platform root wins regardless."""
    if kwargs.get("root"):
        logger.warning(
            "user-local backend ignores `root = %r`; using platform default: %s",
            kwargs["root"],
            resolved_root,
        )


class UserLocalAttestationStore(LocalFsAttestationStore):
    """`user-local` attestation store: root resolved via
    :func:`~darnit.stores.defaults.platform_paths.user_data_root`."""

    _BACKEND_NAME = "user-local"

    def __init__(self, **kwargs: Any) -> None:
        root = user_data_root() / "attestations"
        _warn_and_ignore_root(kwargs, root)
        super().__init__(root=root)

    def write(
        self, bundle_id: str, bundle_bytes: bytes, content_type: str
    ) -> None:
        # Compute target BEFORE delegating so we log with the right backend
        # name even after the parent's log call runs.
        target = self._target_for(bundle_id, content_type)
        # Delegate to grandparent (Filesystem*Store), skipping LocalFs*'s
        # own info log. We emit our own with backend="user-local".
        try:
            self._delegate.write(bundle_id, bundle_bytes, content_type)
        except Exception as err:
            from darnit.stores.errors import StoreOperationError

            raise StoreOperationError(
                f"[{self._BACKEND_NAME} attestation @ {target}] {err}"
            ) from err
        _log_wrote("attestation", self._BACKEND_NAME, target)


class UserLocalReportStore(LocalFsReportStore):
    """`user-local` report store."""

    _BACKEND_NAME = "user-local"

    def __init__(self, **kwargs: Any) -> None:
        root = user_data_root() / "reports"
        _warn_and_ignore_root(kwargs, root)
        super().__init__(root=root)

    def _write(self, report_id: str, ext: str, content: str, tag: str) -> None:
        target = self._target_for(report_id, ext)
        try:
            self._delegate._write(report_id, ext, content)
        except Exception as err:
            from darnit.stores.errors import StoreOperationError

            raise StoreOperationError(
                f"[{self._BACKEND_NAME} {tag} @ {target}] {err}"
            ) from err
        _log_wrote(tag, self._BACKEND_NAME, target)


class UserLocalAuditCacheStore(LocalFsAuditCacheStore):
    """`user-local` audit-cache store."""

    _BACKEND_NAME = "user-local"

    def __init__(self, **kwargs: Any) -> None:
        root = user_cache_root() / "audit-cache"
        _warn_and_ignore_root(kwargs, root)
        super().__init__(root=root)

    def write(self, cache_key: str, envelope: dict[str, Any]) -> None:
        target = self._target_for(cache_key)
        self._delegate.write(cache_key, envelope)
        if target.exists():
            _log_wrote(self._KIND_TAG, self._BACKEND_NAME, target)


__all__ = [
    "UserLocalAttestationStore",
    "UserLocalAuditCacheStore",
    "UserLocalReportStore",
]
