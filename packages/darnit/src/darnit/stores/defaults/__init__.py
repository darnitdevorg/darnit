"""Filesystem-backed default implementations of the store Protocols.

Feature 033 T016. Each default reproduces the pre-feature on-disk layout
exactly (SC-003), so an audit with no ``[stores.*]`` block behaves
identically to how darnit did before this feature landed.
"""

from __future__ import annotations

from darnit.stores.defaults.attestation import FilesystemAttestationStore
from darnit.stores.defaults.cache import FilesystemAuditCacheStore
from darnit.stores.defaults.project import FilesystemProjectStateStore
from darnit.stores.defaults.report import FilesystemReportStore

__all__ = [
    "FilesystemAttestationStore",
    "FilesystemAuditCacheStore",
    "FilesystemProjectStateStore",
    "FilesystemReportStore",
]
