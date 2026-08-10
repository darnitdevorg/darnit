"""parity.toml metadata parser for feature 028 fixtures (T005).

Per contract parity-toml-schema.md (PT-1..PT-19). TOML-parsed via stdlib
tomllib; no code execution at load time.
"""

from __future__ import annotations

import tomllib
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Category = Literal["all_pass", "all_fail", "mixed", "pending_llm"]
VALID_CATEGORIES: tuple[Category, ...] = (
    "all_pass",
    "all_fail",
    "mixed",
    "pending_llm",
)

_KNOWN_COUNT_KEYS = {"pass", "fail", "warn", "error", "n_a", "pending_llm"}
_KNOWN_EXPECTED_KEYS = {
    "category",
    "has_pending_llm",
    "strict",
    "counts",
    "controls",
    "control_ids",
}


@dataclass(frozen=True)
class ExpectedControl:
    id: str
    status: str


@dataclass(frozen=True)
class ParityMetadata:
    category: Category
    has_pending_llm: bool
    strict: bool = False
    counts: dict[str, int] = field(default_factory=dict)
    controls: tuple[ExpectedControl, ...] = ()
    # Optional per-fixture filter: if non-empty, the parity comparison
    # only considers these control IDs from both paths' outputs. If empty,
    # all controls (which will be every OSPS control since neither path
    # auto-applies audit_profiles from .baseline.toml today) are compared.
    control_ids: tuple[str, ...] = ()


def load_parity_metadata(fixture_dir: Path) -> ParityMetadata | None:
    """Load a fixture's parity.toml, if present.

    Returns None when the file is absent (PT-2). Raises ValueError on
    malformed TOML (PT-4) or schema violations (PT-5, PT-6, PT-8).
    Unknown keys log a warning but do not fail (PT-9).
    """
    parity_path = fixture_dir / "parity.toml"
    if not parity_path.exists():
        return None

    try:
        with parity_path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"malformed parity.toml at {parity_path}: {exc}",
        ) from exc

    expected = raw.get("expected")
    if not isinstance(expected, dict):
        raise ValueError(
            f"parity.toml at {parity_path} is missing [expected] section",
        )

    # Forward-compat: unknown [expected] keys warn but don't fail (PT-9).
    for key in expected:
        if key not in _KNOWN_EXPECTED_KEYS:
            warnings.warn(
                f"parity.toml at {parity_path}: unknown [expected] key {key!r}",
                stacklevel=2,
            )

    # Validate category (PT-5).
    category = expected.get("category")
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"parity.toml at {parity_path}: `category` must be one of {VALID_CATEGORIES}, got {category!r}",
        )

    # Validate counts (PT-8).
    counts_raw = expected.get("counts", {}) or {}
    if not isinstance(counts_raw, dict):
        raise ValueError(
            f"parity.toml at {parity_path}: [expected.counts] must be a table",
        )
    counts: dict[str, int] = {}
    for k, v in counts_raw.items():
        if k not in _KNOWN_COUNT_KEYS:
            warnings.warn(
                f"parity.toml at {parity_path}: unknown counts key {k!r}",
                stacklevel=2,
            )
            continue
        if not isinstance(v, int) or v < 0:
            raise ValueError(
                f"parity.toml at {parity_path}: counts.{k} must be a non-negative integer, got {v!r}",
            )
        counts[k] = v

    # Derive / validate has_pending_llm (PT-6).
    pending_count = counts.get("pending_llm", 0)
    if "has_pending_llm" in expected:
        has_pending_llm = expected["has_pending_llm"]
        if not isinstance(has_pending_llm, bool):
            raise ValueError(
                f"parity.toml at {parity_path}: has_pending_llm must be bool",
            )
        if bool(pending_count > 0) != has_pending_llm:
            raise ValueError(
                f"parity.toml at {parity_path}: has_pending_llm="
                f"{has_pending_llm} disagrees with counts.pending_llm="
                f"{pending_count}",
            )
    else:
        has_pending_llm = pending_count > 0

    strict = bool(expected.get("strict", False))

    # Optional per-control expectations.
    controls_raw = expected.get("controls", []) or []
    if not isinstance(controls_raw, list):
        raise ValueError(
            f"parity.toml at {parity_path}: [[expected.controls]] must be an array",
        )
    controls: list[ExpectedControl] = []
    for entry in controls_raw:
        if not isinstance(entry, dict):
            raise ValueError(
                f"parity.toml at {parity_path}: control entry must be a table",
            )
        cid = entry.get("id")
        status = entry.get("status")
        if not isinstance(cid, str) or not cid:
            raise ValueError(
                f"parity.toml at {parity_path}: control entry needs non-empty `id`",
            )
        if not isinstance(status, str) or not status:
            raise ValueError(
                f"parity.toml at {parity_path}: control entry needs non-empty `status`",
            )
        controls.append(ExpectedControl(id=cid, status=status))

    control_ids_raw = expected.get("control_ids", []) or []
    if not isinstance(control_ids_raw, list) or not all(isinstance(x, str) for x in control_ids_raw):
        raise ValueError(
            f"parity.toml at {parity_path}: control_ids must be a list of strings",
        )

    return ParityMetadata(
        category=category,
        has_pending_llm=has_pending_llm,
        strict=strict,
        counts=counts,
        controls=tuple(controls),
        control_ids=tuple(control_ids_raw),
    )


__all__ = (
    "Category",
    "VALID_CATEGORIES",
    "ExpectedControl",
    "ParityMetadata",
    "load_parity_metadata",
)
