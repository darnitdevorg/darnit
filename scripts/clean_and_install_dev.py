#!/usr/bin/env python3
"""Clean build artifacts and install development environment.

Flow brainstormed in the October 27, 2026 Darnit Community Meeting
(local and automated testing agenda by Mike Lieberman and Jaydeep Pokhariya).

Usage:
    uv run python scripts/clean_and_install_dev.py [--recreate-venv] [--skip-sync]

Steps:
1. Cleans stale cache files (.pytest_cache, .ruff_cache, dist/, *.pyc).
2. Optionally removes and recreates the virtual environment (--recreate-venv).
3. Synchronizes development environment with uv sync --all-extras (records installation time).
4. Verifies discovery of implementations and framework plugin registrations.
5. Runs sync validation (scripts/validate_sync.py).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("clean_and_install_dev")

REPO_ROOT = Path(__file__).resolve().parent.parent


def clean_artifacts(repo_root: Path, recreate_venv: bool = False) -> None:
    """Remove cache files, build directories, and optionally .venv."""
    logger.info("Cleaning build artifacts and caches...")
    dirs_to_clean = [
        repo_root / "dist",
        repo_root / "build",
        repo_root / ".pytest_cache",
        repo_root / ".ruff_cache",
    ]
    if recreate_venv:
        active_venv = Path(sys.prefix).resolve()
        target_venv = (repo_root / ".venv").resolve()
        if active_venv == target_venv:
            logger.warning(
                "Cannot delete active .venv while running from inside it. "
                "Run `rm -rf .venv && uv sync` directly from your shell to recreate it."
            )
        else:
            dirs_to_clean.append(repo_root / ".venv")

    for d in dirs_to_clean:
        if d.exists():
            logger.info("Removing %s", d)
            shutil.rmtree(d, ignore_errors=True)

    # Clean __pycache__ and .pyc
    for root, dirs, files in os.walk(repo_root):
        # Prune .git and .venv in-place so os.walk does not descend into them
        dirs[:] = [d for d in dirs if d not in {".git", ".venv"}]
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(Path(root) / d, ignore_errors=True)
                dirs.remove(d)
        for f in files:
            if f.endswith(".pyc"):
                try:
                    (Path(root) / f).unlink(missing_ok=True)
                except OSError:
                    pass


def sync_environment(repo_root: Path) -> float:
    """Synchronize development dependencies with uv and measure elapsed time."""
    logger.info("Synchronizing dependencies with `uv sync --all-extras`...")
    start_time = time.perf_counter()
    res = subprocess.run(
        ["uv", "sync", "--all-extras"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start_time
    if res.returncode != 0:
        logger.error("uv sync failed (exit %d):\n%s", res.returncode, res.stderr)
        sys.exit(res.returncode)

    logger.info("Installation completed in %.2fs", elapsed)
    return elapsed


def verify_environment(repo_root: Path) -> None:
    """Verify implementations discover cleanly and sync validation passes."""
    logger.info("Verifying framework discovery and imports...")
    verify_cmd = (
        "from darnit.core.discovery import discover_implementations\n"
        "from darnit_baseline import register\n"
        "impls = discover_implementations()\n"
        "reg = register()\n"
        "assert len(impls) > 0, 'No implementations discovered'\n"
        "assert reg is not None, 'Baseline registration failed'\n"
        "print(f'Verified: {len(impls)} implementations discovered.')\n"
    )
    res = subprocess.run(
        ["uv", "run", "python", "-c", verify_cmd],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        logger.error("Discovery verification failed:\n%s", res.stderr)
        sys.exit(res.returncode)
    logger.info(res.stdout.strip())

    logger.info("Running sync validation...")
    sync_res = subprocess.run(
        ["uv", "run", "python", "scripts/validate_sync.py", "--verbose"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if sync_res.returncode != 0:
        logger.error("validate_sync.py failed:\n%s", sync_res.stderr or sync_res.stdout)
        sys.exit(sync_res.returncode)
    logger.info("Sync validation passed cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recreate-venv", action="store_true", help="Delete and recreate .venv")
    parser.add_argument("--skip-sync", action="store_true", help="Skip uv sync step")
    args = parser.parse_args()

    clean_artifacts(REPO_ROOT, recreate_venv=args.recreate_venv)
    if not args.skip_sync:
        sync_environment(REPO_ROOT)
    verify_environment(REPO_ROOT)
    logger.info("Environment is clean, up to date, and verified.")


if __name__ == "__main__":
    main()
