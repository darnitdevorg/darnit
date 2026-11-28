"""Audit evidence retained only across context-confirmation writes."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from darnit.core.audit_cache import _is_working_tree_dirty, invalidate_audit_cache, read_audit_cache
from darnit.tools.audit import _full_audit_cache_location


def checkout_digest(local_path: str) -> str:
    """Hash tracked and untracked files, excluding the confirmation file."""
    paths = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=local_path, check=True, capture_output=True, timeout=10,
    ).stdout.split(b"\0")
    digest = hashlib.sha256()
    for name in sorted(set(paths) - {b"", b".project/darnit.yaml"}):
        path = Path(local_path) / os.fsdecode(name)
        digest.update(name + b"\0")
        if path.is_symlink():
            digest.update(b"symlink:" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            # Refuse links through a parent directory outside the checkout.
            if not path.resolve().is_relative_to(Path(local_path).resolve()):
                raise ValueError("Question audit path leaves the checkout")
            digest.update(path.read_bytes())
            digest.update(str(path.stat().st_mode).encode())
        else:
            digest.update(b"missing")
        digest.update(b"\0")
    return digest.hexdigest()


def confirmation_digest(local_path: str, target: str) -> str:
    """Bind retained evidence to the exact confirmed values and project claims."""
    from darnit.config.context_resolve import resolve_context
    from darnit.config.context_storage import get_context_definitions

    resolved = resolve_context(
        local_path, get_context_definitions(local_path), target=target, detect=False,
    )
    digest = hashlib.sha256(json.dumps(resolved.usable(), sort_keys=True, default=str).encode())
    path = Path(local_path) / ".project/darnit.yaml"
    if not path.resolve().is_relative_to(Path(local_path).resolve()):
        raise ValueError("Confirmation path leaves the checkout")
    if path.is_file():
        digest.update(path.read_bytes())
    return digest.hexdigest()


def question_audit(local_path: str, target: str | None) -> dict | None:
    """Read a full audit or the narrower evidence retained by confirmation."""
    from darnit.tools.audit import read_full_audit_cache

    cached: dict | None = read_full_audit_cache(local_path, "openssf-baseline", level=3, target=target)
    full_audit = cached
    stores, key = _full_audit_cache_location(local_path, "openssf-baseline", None)
    try:
        cached = read_audit_cache(
            local_path, expected_framework="openssf-baseline", expected_level=3,
            expected_target=target, store=stores.cache, cache_key=key + ":pending-data",
        )
        if (
            cached
            and cached.get("checkout_digest") == checkout_digest(local_path)
            and target is not None
            and cached.get("confirmation_digest") == confirmation_digest(local_path, target)
            and (full_audit is None or cached["timestamp"] >= full_audit["timestamp"])
        ):
            return cached
        return full_audit
    finally:
        stores.close_all()


def retain_question_audit(local_path: str, target: str, cached: dict, changed_keys: set[str]) -> None:
    """Keep unaffected results for question filtering, with the original expiry."""
    from darnit.config.context_storage import get_context_definitions

    definitions = get_context_definitions(local_path)
    if changed_keys - definitions.keys():
        return
    affected = {control for key in changed_keys for control in definitions[key].affects}
    retained = {
        **cached,
        "commit_dirty": _is_working_tree_dirty(local_path),
        "checkout_digest": checkout_digest(local_path),
        "confirmation_digest": confirmation_digest(local_path, target),
        "results": [result for result in cached["results"] if result["id"] not in affected],
    }
    stores, key = _full_audit_cache_location(local_path, "openssf-baseline", None)
    try:
        # This is a collection snapshot, never a reusable full audit.
        stores.cache.write(key + ":pending-data", retained)
        invalidate_audit_cache(local_path, store=stores.cache, cache_key=key)
    finally:
        stores.close_all()
