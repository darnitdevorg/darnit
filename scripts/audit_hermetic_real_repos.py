"""Manual integration test for repro_hermetic_build_handler against real repos.

Clone the repos you want to check into <repo-dir>/test-<name> (e.g.
<repo-dir>/test-requests for psf/requests), then run from the repo root:

    uv run python scripts/audit_hermetic_real_repos.py
    uv run python scripts/audit_hermetic_real_repos.py --repo-dir /path/to/clones

Repo dir resolution order: --repo-dir flag, DARNIT_HERMETIC_AUDIT_DIR env var,
then the system temp directory.
"""

import argparse
import os
import tempfile
from pathlib import Path

from darnit_reproducibility.handlers import repro_hermetic_build_handler

from darnit.sieve.handler_registry import HandlerContext

REPOS = [
    ("test-requests", "psf/requests (Python)"),
    ("test-hugo", "gohugoio/hugo (Go)"),
    ("test-redis", "redis/redis (C)"),
    ("test-ripgrep", "ripgrep (Rust)"),
    ("test-arrow", "apache/arrow (monorepo)"),
]


def audit(path: Path, label: str) -> None:
    if not path.exists():
        print(f"\n{label}")
        print(f"  SKIPPED — {path} not found (clone it first)")
        return

    ctx = HandlerContext(local_path=str(path), owner="", repo=path.name)
    r = repro_hermetic_build_handler({}, ctx)

    files = r.evidence.get("files_scanned", [])
    viols = r.evidence.get("violations_found", [])
    deferred = r.evidence.get("deferred_found", [])
    signal = r.evidence.get("strong_signal")

    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  status:        {r.status.value.upper()}  (confidence {r.confidence})")
    print(f"  files scanned: {len(files)}")

    if signal:
        print(f"  SIGNAL:    {signal}")
    for v in viols:
        print(f"  VIOLATION: {v}")
    for d in deferred:
        print(f"  DEFERRED:  {d}")

    print(f"\n  {r.message}")


def _default_repo_dir() -> Path:
    env_dir = os.environ.get("DARNIT_HERMETIC_AUDIT_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(tempfile.gettempdir())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-dir",
        type=Path,
        default=_default_repo_dir(),
        help="Directory containing test-<name> clones (default: $DARNIT_HERMETIC_AUDIT_DIR or the system temp dir)",
    )
    args = parser.parse_args()

    for dirname, repo_label in REPOS:
        audit(args.repo_dir / dirname, repo_label)
