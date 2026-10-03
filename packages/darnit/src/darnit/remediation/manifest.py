"""Operator-side record of what one remediation run wrote (feature 043, research R7).

A run manifest lists every file the executor wrote, with the digest of the
content it wrote, and every platform change set it applied. The git tools
commit only those files, and only while their content still matches. The
manifest lives under the darnit data root at
``remediation/<repository-identity>/<run_id>.json`` (mode 0600), never inside
the audited checkout, and is written only by an apply; a preview writes none.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from darnit.core.logging import get_logger
from darnit.remediation.plan import normalize_repo_path
from darnit.stores.defaults.platform_paths import user_data_root
from darnit.trust.identity import canonical_identity

logger = get_logger("remediation.manifest")

_FORBID = ConfigDict(extra="forbid")
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RUN_ID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
LOCAL_HOST = "local.invalid"
_ULID_LOCK = threading.Lock()
_last_ulid: tuple[int, int] = (0, 0)


class ManifestFile(BaseModel):
    model_config = _FORBID

    path: str
    after_digest: str

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        return normalize_repo_path(value)


class RunManifest(BaseModel):
    model_config = _FORBID

    schema_version: Literal[1] = 1
    run_id: str
    repository: str
    created_at: str
    files: list[ManifestFile] = Field(default_factory=list)
    change_sets: list[str] = Field(default_factory=list)
    branch: str | None = None
    base: str | None = None
    base_commit: str | None = None
    commit: str | None = None


def new_run_id() -> str:
    """A ULID: 48-bit millisecond time and 80 random bits, monotonic within this process."""
    global _last_ulid
    with _ULID_LOCK:
        millis = time.time_ns() // 1_000_000
        last_millis, last_random = _last_ulid
        if millis <= last_millis:
            millis, randomness = last_millis, last_random + 1
        else:
            randomness = secrets.randbits(80)
        _last_ulid = (millis, randomness)
    value = (millis << 80) | (randomness & ((1 << 80) - 1))
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def repository_identity(local_path: str | Path, owner: str | None = None, repo: str | None = None) -> str:
    """Identity a checkout's runs are recorded under.

    The operator-named ``owner``/``repo`` (on github.com) when given, else the
    checkout's ``origin`` remote, else a stable local identity derived from
    the checkout's real path. It names records only and is never a basis for
    trust.
    """
    from darnit.core.utils import detect_checkout_identity
    from darnit.trust.decision import target_from_owner_repo

    target = target_from_owner_repo(owner, repo)
    canonical = canonical_identity(target) if target else None
    if canonical is None:
        hint = detect_checkout_identity(str(local_path))
        canonical = hint.canonical if hint else None
    if canonical is None:
        real = os.path.realpath(local_path).encode("utf-8", "surrogateescape")
        canonical = f"{LOCAL_HOST}/checkout/{hashlib.sha256(real).hexdigest()[:32]}"
    return canonical


def _check_repository(repository: str) -> str:
    if canonical_identity(repository) != repository:
        raise ValueError(f"not a canonical repository identity: {repository!r}")
    return repository


def _check_run_id(run_id: str) -> str:
    if not _RUN_ID.match(run_id):
        raise ValueError(f"not a remediation run id: {run_id!r}")
    return run_id


def runs_dir(repository: str) -> Path:
    return user_data_root() / "remediation" / Path(*_check_repository(repository).split("/"))


def manifest_path(repository: str, run_id: str) -> Path:
    return runs_dir(repository) / f"{_check_run_id(run_id)}.json"


def _inside(path: Path, checkout: str | Path | None) -> bool:
    if checkout is None:
        return False
    return path.resolve().is_relative_to(Path(checkout).resolve())


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write(path: Path, run: RunManifest, checkout: str | Path | None) -> None:
    if _inside(path, checkout):
        raise ValueError(f"refusing to store a remediation run at {path}: it is inside the audited repository")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".run-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(run.model_dump(mode="json"), handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read(path: Path) -> RunManifest | None:
    try:
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning("Ignoring unreadable remediation run %s: %s", path, exc)
        return None


def start_run(
    repository: str,
    *,
    checkout: str | Path | None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> RunManifest:
    """Create the manifest of a new run (or of ``run_id``) and write it."""
    run = RunManifest(
        run_id=_check_run_id(run_id) if run_id else new_run_id(),
        repository=_check_repository(repository),
        created_at=_timestamp(now or datetime.now(UTC)),
    )
    _write(manifest_path(repository, run.run_id), run, checkout)
    return run


def _update(repository: str, run_id: str, checkout: str | Path | None, change) -> RunManifest:
    path = manifest_path(repository, run_id)
    if _inside(path, checkout):
        raise ValueError(f"refusing to store a remediation run at {path}: it is inside the audited repository")
    run = _read(path) if path.is_file() else None
    if run is None:
        raise LookupError(f"no remediation run {run_id} for {repository}")
    change(run)
    _write(path, run, checkout)
    return run


def record_file(
    repository: str, run_id: str, path: str, after_digest: str, *, checkout: str | Path | None
) -> RunManifest:
    """Record that the executor wrote ``path`` with content ``after_digest``."""
    entry = ManifestFile(path=path, after_digest=after_digest)

    def change(run: RunManifest) -> None:
        run.files = [f for f in run.files if f.path != entry.path] + [entry]

    return _update(repository, run_id, checkout, change)


def record_change_set(repository: str, run_id: str, digest: str, *, checkout: str | Path | None) -> RunManifest:
    """Record an applied platform change set by its digest."""

    def change(run: RunManifest) -> None:
        if digest not in run.change_sets:
            run.change_sets.append(digest)

    return _update(repository, run_id, checkout, change)


def set_branch(
    repository: str,
    run_id: str,
    branch: str,
    *,
    checkout: str | Path | None,
    base: str | None = None,
    base_commit: str | None = None,
) -> RunManifest:
    """Record the run's branch and the ref a pull request from it targets, with that ref's commit.

    A new branch replaces the recorded base (None when unresolved); the same
    branch keeps it unless ``base`` is given.
    """

    def change(run: RunManifest) -> None:
        if base is not None or run.branch != branch:
            run.base, run.base_commit = base, base_commit
        run.branch = branch

    return _update(repository, run_id, checkout, change)


def set_commit(repository: str, run_id: str, commit: str, *, checkout: str | Path | None) -> RunManifest:
    def change(run: RunManifest) -> None:
        run.commit = commit

    return _update(repository, run_id, checkout, change)


def load_run(
    repository: str, run_id: str | None = None, *, checkout: str | Path | None = None
) -> RunManifest | None:
    """The manifest of ``run_id``, or of the latest run for ``repository`` when None.

    A store that lies inside the audited checkout is repository content and is
    not read.
    """
    if run_id is not None:
        path = manifest_path(repository, run_id)
        if _inside(path, checkout) or not path.is_file():
            return None
        return _read(path)
    directory = runs_dir(repository)
    if _inside(directory, checkout) or not directory.is_dir():
        return None
    for candidate in sorted((p for p in directory.glob("*.json") if _RUN_ID.match(p.stem)), reverse=True):
        run = _read(candidate)
        if run is not None:
            return run
    return None


__all__ = [
    "LOCAL_HOST",
    "ManifestFile",
    "RunManifest",
    "load_run",
    "manifest_path",
    "new_run_id",
    "record_change_set",
    "record_file",
    "repository_identity",
    "runs_dir",
    "set_branch",
    "set_commit",
    "start_run",
]
