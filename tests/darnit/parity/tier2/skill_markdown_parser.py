"""Best-effort parser for the /darnit-audit skill's final assistant message.

Feature 028 T016. The skill's output format is NOT a stable contract; this
parser is heuristic. A parse failure surfaces as `parseable=False` (a
distinct failure class from "skill and tool disagree"), never a crash.

See:
  - specs/028-audit-parity-tests/data-model.md section 6
  - specs/028-audit-parity-tests/research.md R6
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SkillControlClaim:
    id: str
    status: Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM"]


@dataclass(frozen=True)
class SkillReport:
    parseable: bool
    raw_markdown: str
    counts: dict[str, int] | None = None
    controls: tuple[SkillControlClaim, ...] | None = None
    parse_notes: tuple[str, ...] = ()

    @classmethod
    def parse(cls, markdown: str) -> SkillReport:
        """Best-effort regex parser. Never raises."""
        try:
            counts = _extract_counts(markdown)
            controls = _extract_controls(markdown)
            notes: list[str] = []

            if counts is None:
                notes.append("could not extract summary counts")
            if controls is None or not controls:
                notes.append("could not extract per-control claims")

            parseable = counts is not None and controls is not None and len(controls) > 0
            return cls(
                parseable=parseable,
                raw_markdown=markdown,
                counts=counts,
                controls=tuple(controls) if controls else None,
                parse_notes=tuple(notes),
            )
        except Exception as exc:  # noqa: BLE001
            return cls(
                parseable=False,
                raw_markdown=markdown,
                counts=None,
                controls=None,
                parse_notes=(f"parser exception: {type(exc).__name__}: {exc}",),
            )


_STATUS_LITERALS = ("PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM")


def _extract_counts(markdown: str) -> dict[str, int] | None:
    """Extract summary counts. Recognizes shapes like:
    - "Passed: 51", "Failed: 5", "Warned: 7" (verbose "- Passed: N" lines)
    - "PASS: 51, FAIL: 5" (colon form)
    - "51 PASS, 5 FAIL, 7 WARN" (adjacency form -- LAST because it can
      false-match a per-control line like "OSPS-DO-01.01 PASS")
    """
    counts: dict[str, int] = {}

    # Shape 3 (verbose) FIRST -- most specific, least prone to false matches.
    for verbose, canonical in [
        ("passed", "pass"),
        ("failed", "fail"),
        ("warned", "warn"),
        ("errored", "error"),
        ("na", "n_a"),
    ]:
        pattern = re.compile(rf"\b{verbose}\s*:\s*(\d+)\b", re.IGNORECASE)
        m = pattern.search(markdown)
        if m:
            counts[canonical] = int(m.group(1))

    # Shape 2: "STATUS: N" (still specific because of the colon).
    for status in _STATUS_LITERALS:
        key = status.lower().replace("/", "_")
        if key in counts:
            continue
        pattern = re.compile(
            rf"\b{re.escape(status)}\s*:\s*(\d+)\b",
            re.IGNORECASE,
        )
        m = pattern.search(markdown)
        if m:
            counts[key] = int(m.group(1))

    # Shape 1: "N STATUS" or "N/M STATUS" -- least specific, most prone to
    # false-match a per-control line. Only apply if the count wasn't found
    # via the more specific shapes above.
    for status in _STATUS_LITERALS:
        key = status.lower().replace("/", "_")
        if key in counts:
            continue
        # Prefer patterns with N/M or N followed by "STATUS," or the word
        # is followed by a comma / end-of-line to reduce false matches on
        # per-control lines that have "01 PASS (dispositive)" shapes.
        pattern = re.compile(
            rf"\b(\d+)/\d+\s+{re.escape(status)}\b",
            re.IGNORECASE,
        )
        m = pattern.search(markdown)
        if m:
            counts[key] = int(m.group(1))
            continue

        pattern = re.compile(
            rf"(?<!\.\d)\b(\d+)\s+{re.escape(status)}\b(?=[,\s]|$)",
            re.IGNORECASE,
        )
        m = pattern.search(markdown)
        if m:
            counts[key] = int(m.group(1))

    if not counts:
        return None
    return counts


def _extract_controls(markdown: str) -> list[SkillControlClaim] | None:
    """Extract per-control claims. Recognizes shapes like:
      - "**OSPS-GV-01.01**: PASS"
      - "- OSPS-GV-01.01 PASS"
      - "OSPS-GV-01.01: PASS"
    Returns None on total parse failure; empty list is a valid outcome when
    the skill's summary omits per-control detail.
    """
    control_id_pattern = r"(OSPS-[A-Z]{2}-\d{2}\.\d{2}|STAGE1-REF-[A-Z-]+-\d{2})"
    claims: list[SkillControlClaim] = []
    seen: set[str] = set()

    for line in markdown.splitlines():
        # Try to find a control ID + status on the same line.
        cid_match = re.search(control_id_pattern, line)
        if not cid_match:
            continue

        # Look for one of the status literals nearby (same line).
        # Sort by length descending so PENDING_LLM matches before PENDING.
        for status in sorted(_STATUS_LITERALS, key=len, reverse=True):
            # Whole-word status match (case-sensitive since these are literal
            # in darnit's output).
            if re.search(rf"\b{re.escape(status)}\b", line):
                cid = cid_match.group(1)
                if cid in seen:
                    break
                seen.add(cid)
                claims.append(SkillControlClaim(id=cid, status=status))
                break

    return claims


__all__ = ("SkillControlClaim", "SkillReport")
