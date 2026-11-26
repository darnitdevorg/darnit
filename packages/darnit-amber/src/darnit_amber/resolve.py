"""
Stub: finding install steps for the files a run's lock could not name (its `unresolved`). Not built yet.

The plan, kept conservative (a model's answer is a candidate until a check confirms it):

  1. build the lock's image: the unresolved files it already has, at the run's digest, need nothing
  2. ask a model (darnit's LLM configuration) for install steps for the files left
  3. check each step in its own build: keep it only if a file it names then has the run's digest
  4. ask again about what is left, with what failed, a few times

Confirmed steps would be stored next to the run, unsigned, each marked with the model that proposed it,
and a rerun would show them before running them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve(bundle: Path, run_id: str) -> dict[str, Any]:
    """Install steps for the run's unresolved files, each confirmed by a build. Not implemented."""
    raise NotImplementedError("resolving unresolved files is planned, not built (see this module's docstring)")
