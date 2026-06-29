"""Reproducibility sieve handlers.

Each function checks one specific aspect of build reproducibility.
They are deliberately conservative — when in doubt, return INCONCLUSIVE
rather than falsely passing or failing.
"""

from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus

logger = get_logger("darnit_reproducibility.handlers")


def repro_deps_pinned_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check that dependencies are pinned to exact versions.

    Looks for lock files — the most reliable signal that deps are pinned.
    PASS if a lock file exists, FAIL if only a loose manifest exists,
    INCONCLUSIVE if no dependency files found at all.
    """
    path = Path(ctx.local_path)

    # Lock files — strong signal that deps are pinned
    lock_files = {
        "uv.lock": "uv (Python)",
        "poetry.lock": "Poetry (Python)",
        "Pipfile.lock": "Pipenv (Python)",
        "package-lock.json": "npm (Node)",
        "yarn.lock": "Yarn (Node)",
        "Cargo.lock": "Cargo (Rust)",
        "go.sum": "Go modules",
        "Gemfile.lock": "Bundler (Ruby)",
        "composer.lock": "Composer (PHP)",
    }

    # Loose manifests without lock files — weak signal
    loose_manifests = {
        "requirements.txt": "pip requirements",
        "setup.py": "setuptools",
        "package.json": "npm package",
        "Cargo.toml": "Cargo manifest",
        "go.mod": "Go module",
    }

    found_locks = []
    for filename, label in lock_files.items():
        if (path / filename).exists():
            found_locks.append(f"{filename} ({label})")

    found_loose = []
    for filename, label in loose_manifests.items():
        if (path / filename).exists():
            # Only flag loose if no corresponding lock exists
            found_loose.append(f"{filename} ({label})")

    evidence = {
        "lock_files_found": found_locks,
        "loose_manifests_found": found_loose,
    }

    if found_locks:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Lock file(s) found: {', '.join(found_locks)}",
            confidence=0.8,  # a lock file proves deps were pinned once, not that it is current
            evidence=evidence,
        )

    if found_loose:
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"Dependency manifests found but no lock files: {', '.join(found_loose)}",
            confidence=0.8,
            evidence=evidence,
        )

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="No dependency files found — cannot determine if deps are pinned",
        confidence=0.0,
        evidence=evidence,
    )


def repro_build_env_declared_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check that the build environment is explicitly declared.

    Looks for Dockerfile, Nix flake, devcontainer, or similar.
    PASS if found, INCONCLUSIVE if not.
    """
    path = Path(ctx.local_path)

    env_files = {
        "Dockerfile": "Docker",
        "flake.nix": "Nix flake",
        "shell.nix": "Nix shell",
        ".devcontainer": "Dev container",
        "Vagrantfile": "Vagrant",
        ".tool-versions": "asdf version manager",
        ".nvmrc": "Node version manager",
        ".python-version": "pyenv",
    }

    found = []
    for name, label in env_files.items():
        if (path / name).exists():
            found.append(f"{name} ({label})")

    evidence = {"env_files_found": found}

    if found:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Build environment declared via: {', '.join(found)}",
            confidence=0.85,
            evidence=evidence,
        )

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="No build environment declaration found",
        confidence=0.0,
        evidence=evidence,
    )


def repro_hermetic_build_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check that CI workflows do not fetch dependencies at build time.

    Scans GitHub Actions workflow files for patterns that indicate
    live network fetches during the build step.
    PASS if no fetches found, FAIL if suspicious patterns found,
    INCONCLUSIVE if no CI files to check.

    v0.1 limitation: only .github/workflows/*.{yml,yaml} are scanned; network
    fetches from Makefile, setup.py, composite actions or Dockerfile are not
    detected. See https://github.com/kusari-oss/darnit/issues/227 for the roadmap.
    """
    path = Path(ctx.local_path)
    workflows_dir = path / ".github" / "workflows"

    if not workflows_dir.exists():
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No GitHub Actions workflows found to check",
            confidence=0.0,
            evidence={"workflows_checked": [], "violations_found": []},
        )

    # Patterns that suggest live network fetches during build
    suspicious_patterns = [
        "curl ",
        "wget ",
        "pip install ",
        "npm install",
        "yarn install",
        "apt-get install",
        "brew install",
    ]

    # Patterns that are fine — these are using the lock file
    safe_patterns = [
        "uv sync",
        "uv pip install",
        "pip install --no-index",
        "pip install -e ",  # editable install of local source, not a network fetch
        "npm ci",         # npm ci uses lock file
        "yarn --frozen-lockfile",
    ]

    violations = []
    workflow_files = list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))

    for wf_file in workflow_files:
        try:
            lines = wf_file.read_text(encoding="utf-8").splitlines()
            for line in lines:
                # Skip if this line contains a known-safe pattern
                if any(safe in line for safe in safe_patterns):
                    continue
                # Check if this line contains a suspicious pattern
                for pattern in suspicious_patterns:
                    if pattern in line:
                        violations.append(
                            f"{wf_file.name}: contains '{pattern.strip()}'"
                        )
                        break  # one violation per line is enough
        except Exception as exc:
            logger.debug("skipped workflow %s: %s", wf_file.name, exc)
            continue

    evidence = {
        "workflows_checked": [f.name for f in workflow_files],
        "violations_found": violations,
    }

    if violations:
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"Possible live network fetches in CI: {'; '.join(violations)}",
            confidence=0.7,
            evidence=evidence,
        )

    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=f"No suspicious network fetches found in {len(workflow_files)} workflow(s)",
        confidence=0.75,
        evidence=evidence,
    )


def repro_provenance_exists_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check that the project generates provenance attestations.

    Looks for sigstore/cosign or SLSA provenance steps in CI.
    PASS if found, INCONCLUSIVE if not.
    """
    path = Path(ctx.local_path)
    workflows_dir = path / ".github" / "workflows"

    provenance_signals = [
        "sigstore/cosign",
        "slsa-framework/slsa-github-generator",
        "actions/attest-build-provenance",
        "cosign sign",
        "cosign attest",
        ".intoto.jsonl",
    ]

    found_signals = []
    files_checked = []

    # Check workflow files
    if workflows_dir.exists():
        for wf_file in list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml")):
            files_checked.append(wf_file.name)
            try:
                content = wf_file.read_text(encoding="utf-8")
                for signal in provenance_signals:
                    if signal in content:
                        found_signals.append(f"{wf_file.name}: {signal}")
            except Exception as exc:
                logger.debug("skipped workflow %s: %s", wf_file.name, exc)
                continue

    evidence = {
        "files_checked": files_checked,
        "provenance_signals": found_signals,
    }

    if found_signals:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Provenance generation found: {'; '.join(found_signals)}",
            confidence=0.9,
            evidence=evidence,
        )

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="No provenance attestation steps found in CI workflows",
        confidence=0.0,
        evidence=evidence,
    )


def repro_bit_for_bit_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check for signals that the build is bit-for-bit reproducible.

    Looks for SOURCE_DATE_EPOCH in CI (normalizes timestamps in builds)
    and checks for reprotest or diffoscope configuration.
    These are the most reliable signals without actually running the build twice.
    """
    path = Path(ctx.local_path)
    workflows_dir = path / ".github" / "workflows"

    # Positive signals only. A workflow-only scan can confirm that good
    # reproducibility practices are present (PASS) but cannot prove that their
    # absence means a non-reproducible build, so we return INCONCLUSIVE rather
    # than FAIL when nothing is found. (Dropped __DATE__/__TIME__/"date +":
    # those are C-source macros / routine log timestamps that this
    # workflow-only scan can't attribute to build artifacts — they only ever
    # produced false signals.)
    good_signals = [
        "SOURCE_DATE_EPOCH",   # Normalizes timestamps — required for repro builds
        "reprotest",           # Tool that builds twice and compares
        "diffoscope",          # Tool that diffs build artifacts
    ]

    found_good = []
    files_checked = []

    if workflows_dir.exists():
        for wf_file in list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml")):
            files_checked.append(wf_file.name)
            try:
                content = wf_file.read_text(encoding="utf-8")
                for signal in good_signals:
                    if signal in content:
                        found_good.append(f"{wf_file.name}: {signal}")
            except Exception as exc:
                logger.debug("skipped workflow %s: %s", wf_file.name, exc)
                continue

    evidence = {
        "files_checked": files_checked,
        "reproducibility_signals": found_good,
    }

    if found_good:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Reproducibility signals found: {'; '.join(found_good)}",
            confidence=0.8,
            evidence=evidence,
        )

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="No reproducibility signals found — manual verification required",
        confidence=0.0,
        evidence=evidence,
    )
