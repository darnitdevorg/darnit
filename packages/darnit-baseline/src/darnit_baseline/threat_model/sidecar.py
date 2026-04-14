"""Mitigation sidecar: load, save, fingerprint, match, stale detection.

The sidecar file at ``.project/threatmodel/mitigations.yaml`` stores
reviewer decisions about threat model findings.  It is human-edited;
the generator only reads it and sets stale flags.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

from .discovery_models import (
    CandidateFinding,
    MitigationEntry,
    MitigationSidecar,
    MitigationStatus,
)

SIDECAR_REL_PATH = os.path.join(".project", "threatmodel", "mitigations.yaml")


def compute_fingerprint(finding: CandidateFinding, repo_root: Path) -> str:
    """Compute a stable fingerprint for a finding.

    The fingerprint incorporates the query ID, the repository-relative file
    path, and a whitespace-normalized representation of the code snippet.
    This means file renames invalidate the fingerprint (by design — see
    spec FR-009).

    Returns a string like ``sha256:a1b2c3d4e5f6g7h8`` (16 hex chars).
    """
    rel_path = os.path.relpath(finding.primary_location.file, repo_root)
    # Normalize snippet: strip leading whitespace per line, drop blank lines.
    normalized = "\n".join(line.strip() for line in finding.code_snippet.lines if line.strip())
    payload = f"{finding.query_id}\n{rel_path}\n{normalized}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"sha256:{digest}"


def load_sidecar(repo_root: Path) -> MitigationSidecar | None:
    """Load the mitigation sidecar from ``.project/threatmodel/mitigations.yaml``.

    Returns ``None`` if the file does not exist (first run — not an error).
    Raises ``ValueError`` if the file exists but is malformed (FR-018).
    """
    sidecar_path = repo_root / SIDECAR_REL_PATH
    if not sidecar_path.exists():
        return None

    try:
        raw = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed sidecar file at {sidecar_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"Sidecar file at {sidecar_path} must be a YAML mapping, got {type(raw).__name__}")

    version = raw.get("version")
    if version != "1":
        raise ValueError(f"Unsupported sidecar version {version!r} at {sidecar_path}; expected '1'")

    entries: list[MitigationEntry] = []
    seen_fingerprints: set[str] = set()
    for item in raw.get("entries", []):
        if not isinstance(item, dict):
            raise ValueError(f"Sidecar entry must be a mapping, got {type(item).__name__}")
        fp = item.get("fingerprint", "")
        if fp in seen_fingerprints:
            raise ValueError(f"Duplicate fingerprint {fp!r} in sidecar at {sidecar_path}")
        seen_fingerprints.add(fp)

        try:
            status = MitigationStatus(item["status"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid or missing status in sidecar entry (fingerprint={fp!r}): {exc}") from exc

        entries.append(
            MitigationEntry(
                fingerprint=fp,
                status=status,
                note=item.get("note", ""),
                reviewer=item.get("reviewer", ""),
                reviewed_at=item.get("reviewed_at", ""),
                query_id=item.get("query_id", ""),
                file_hint=item.get("file_hint", ""),
                stale=item.get("stale", False),
            )
        )

    return MitigationSidecar(entries=entries)


def save_sidecar(repo_root: Path, sidecar: MitigationSidecar) -> None:
    """Write the sidecar back to disk, preserving entry ordering."""
    sidecar_path = repo_root / SIDECAR_REL_PATH
    os.makedirs(sidecar_path.parent, exist_ok=True)

    header = (
        "# .project/threatmodel/mitigations.yaml\n"
        "#\n"
        "# Mitigation decisions for threat model findings.\n"
        "# This file is hand-edited by reviewers and read by the threat model generator.\n"
        "# The generator NEVER creates or deletes entries — only sets the `stale` flag.\n"
        "#\n"
        "# Fingerprints include the file path. Renaming a file will make its entries stale.\n"
        "# Re-record decisions against the new path after a deliberate rename.\n"
        "\n"
    )

    data: dict[str, Any] = {"version": "1", "entries": []}
    for entry in sidecar.entries:
        item: dict[str, Any] = {
            "fingerprint": entry.fingerprint,
            "status": entry.status.value,
        }
        if entry.note:
            item["note"] = entry.note
        if entry.reviewer:
            item["reviewer"] = entry.reviewer
        if entry.reviewed_at:
            item["reviewed_at"] = entry.reviewed_at
        if entry.query_id:
            item["query_id"] = entry.query_id
        if entry.file_hint:
            item["file_hint"] = entry.file_hint
        if entry.stale:
            item["stale"] = True
        data["entries"].append(item)

    yaml_content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    sidecar_path.write_text(header + yaml_content, encoding="utf-8")


def match_findings(
    findings: list[CandidateFinding],
    sidecar: MitigationSidecar,
) -> dict[str, MitigationEntry]:
    """Match finding fingerprints against sidecar entries.

    Returns a dict mapping ``fingerprint → MitigationEntry`` for every
    finding that has a matching sidecar entry.
    """
    lookup = {e.fingerprint: e for e in sidecar.entries}
    matches: dict[str, MitigationEntry] = {}
    for f in findings:
        if f.fingerprint and f.fingerprint in lookup:
            matches[f.fingerprint] = lookup[f.fingerprint]
    return matches


def detect_stale(
    sidecar: MitigationSidecar,
    active_fingerprints: set[str],
) -> bool:
    """Mark sidecar entries as stale if their fingerprint is not in the active set.

    Also clears the stale flag if a previously stale entry's fingerprint
    reappears.

    Returns ``True`` if any stale flags changed (caller should save).
    """
    changed = False
    new_entries: list[MitigationEntry] = []
    for entry in sidecar.entries:
        is_active = entry.fingerprint in active_fingerprints
        if is_active and entry.stale:
            # Fingerprint reappeared — clear stale flag.
            new_entries.append(
                MitigationEntry(
                    fingerprint=entry.fingerprint,
                    status=entry.status,
                    note=entry.note,
                    reviewer=entry.reviewer,
                    reviewed_at=entry.reviewed_at,
                    query_id=entry.query_id,
                    file_hint=entry.file_hint,
                    stale=False,
                )
            )
            changed = True
        elif not is_active and not entry.stale:
            # Fingerprint no longer present — mark stale.
            new_entries.append(
                MitigationEntry(
                    fingerprint=entry.fingerprint,
                    status=entry.status,
                    note=entry.note,
                    reviewer=entry.reviewer,
                    reviewed_at=entry.reviewed_at,
                    query_id=entry.query_id,
                    file_hint=entry.file_hint,
                    stale=True,
                )
            )
            changed = True
        else:
            new_entries.append(entry)

    if changed:
        sidecar.entries = new_entries
    return changed
