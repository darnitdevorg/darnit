"""Canonical repository identity (feature 040, research R3).

An identity is ``host/namespace/name``. The host is always lowercased; the
path is lowercased only for hosts known (or declared by the operator) to treat
repository paths case-insensitively. Inputs that cannot be parsed yield
``None`` so callers fail closed.

Which *source* an identity came from matters for trust: remotes read from the
audited checkout are repository content and can only ever be a hint.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

CASE_INSENSITIVE_HOSTS = frozenset({"github.com", "gitlab.com"})

_SCP_LIKE = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[^:/\s]+):(?P<path>[^/\s].*)$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]+$")
_HOSTNAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class IdentitySource(str, Enum):
    OPERATOR_TARGET = "operator_target"
    CI_METADATA = "ci_metadata"
    CHECKOUT_HINT = "checkout_hint"


@dataclass(frozen=True)
class RepositoryIdentity:
    canonical: str
    source: IdentitySource

    @property
    def trusted_eligible(self) -> bool:
        return self.source in (IdentitySource.OPERATOR_TARGET, IdentitySource.CI_METADATA)


def _split(url: str) -> tuple[str, str] | None:
    url = url.strip()
    if not url:
        return None
    if "://" in url:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https", "ssh", "git"):
            return None
        host = parts.hostname or ""
        return host, parts.path
    match = _SCP_LIKE.match(url)
    if match:
        return match.group("host"), match.group("path")
    # Bare "host/namespace/name".
    host, _, path = url.partition("/")
    return host, path


def canonical_identity(url: str, case_insensitive_hosts: Iterable[str] = ()) -> str | None:
    """Normalize a repository URL or bare identity to ``host/namespace/name``."""
    split = _split(url)
    if split is None:
        return None
    host, path = split
    host = host.lower()
    if not _HOSTNAME.match(host):
        return None

    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    segments = path.split("/")
    if len(segments) < 2 or not all(_SEGMENT.match(seg) and seg not in (".", "..") for seg in segments):
        return None

    folded_hosts = CASE_INSENSITIVE_HOSTS | {h.lower() for h in case_insensitive_hosts}
    if host in folded_hosts:
        segments = [seg.lower() for seg in segments]
    return "/".join([host, *segments])
