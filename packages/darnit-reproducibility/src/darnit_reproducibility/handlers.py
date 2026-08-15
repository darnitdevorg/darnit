"""Reproducibility sieve handlers.

Each function checks one specific aspect of build reproducibility.
They are deliberately conservative — when in doubt, return INCONCLUSIVE
rather than falsely passing or failing.
"""

from pathlib import Path
from typing import Any, Literal

from darnit.core.logging import get_logger
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus

from .witness_attestation import WitnessCheckResult, check_witness_attestation

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


def _strip_comment(line: str) -> str:
    """Strip # comments from a shell/YAML/Makefile line (best-effort).

    Handles full-line comments (``# …``) and inline suffixes (`` # …``).
    Not quote-aware, but accurate enough for the suspicious-pattern heuristic.
    """
    stripped = line.strip()
    if stripped.startswith("#"):
        return ""
    idx = line.find(" #")
    if idx != -1:
        return line[:idx]
    return line


# Patterns that suggest live network fetches during a build step
_SUSPICIOUS_PATTERNS: tuple[str, ...] = (
    "curl ",
    "wget ",
    "pip install ",
    "npm install",
    "yarn install",
    "apt-get install",
    "brew install",
)

# Known-safe: lock-file-based installs that do not fetch live deps
_SAFE_PATTERNS: tuple[str, ...] = (
    "uv sync",
    "uv pip install",
    "pip install --no-index",
    "pip install -e ",  # editable install of local source
    "npm ci",  # uses package-lock.json
    "yarn --frozen-lockfile",
    "pnpm install --frozen-lockfile",
)

# Inside a Dockerfile/Containerfile, system-package installs build the *image*
# environment (not the software artifact), so they are DEFERRED rather than
# violations.
_DOCKERFILE_DEFERRED_PATTERNS: tuple[str, ...] = (
    "apt-get install",
    "apt install",
    "apk add",
    "yum install",
    "dnf install",
    "zypper install",
)


_ScanKind = Literal["safe", "deferred", "violation"]


def _scan_line(line: str, *, is_dockerfile: bool = False) -> tuple[str | None, _ScanKind]:
    """Classify one line for hermeticity-relevant patterns.

    Strips comments first, then returns ``(pattern, kind)`` where *kind* is:

    - ``"safe"``      — known-good pattern, blank line, or comment; ignore
    - ``"deferred"``  — acceptable in this file type (e.g. apt-get in Dockerfile)
    - ``"violation"`` — suspicious live network fetch
    """
    clean = _strip_comment(line)
    if not clean.strip():
        return None, "safe"

    if any(s in clean for s in _SAFE_PATTERNS):
        return None, "safe"

    if is_dockerfile:
        for pat in _DOCKERFILE_DEFERRED_PATTERNS:
            if pat in clean:
                return pat.strip(), "deferred"

    for pat in _SUSPICIOUS_PATTERNS:
        if pat in clean:
            return pat.strip(), "violation"

    return None, "safe"


# Directories whose contents must never be scanned (vendored / generated code)
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "vendor",
        "node_modules",
        ".venv",
        "venv",
        ".git",
        "__pycache__",
        ".tox",
        "dist",
        "build",
    }
)

# Bounds per-repo scan cost — monorepos can have hundreds of Makefiles/Dockerfiles.
_FILE_SCAN_LIMIT = 30


def _iter_workflow_files(path: Path) -> list[Path]:
    """GitHub Actions workflow files under .github/workflows/."""
    wf_dir = path / ".github" / "workflows"
    if not wf_dir.exists():
        return []
    return list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))


def _iter_composite_action_files(path: Path) -> list[Path]:
    """Composite action.yml files under .github/actions/*/."""
    actions_dir = path / ".github" / "actions"
    if not actions_dir.exists():
        return []
    results: list[Path] = []
    for entry in actions_dir.iterdir():
        if not entry.is_dir():
            continue
        for name in ("action.yml", "action.yaml"):
            f = entry / name
            if f.exists():
                results.append(f)
    return results


def _iter_other_ci_files(path: Path) -> list[Path]:
    """CI config files from non-GitHub systems."""
    candidates = [
        ".gitlab-ci.yml",
        ".circleci/config.yml",
        ".circleci/config.yaml",
        "Jenkinsfile",
        "azure-pipelines.yml",
        "azure-pipelines.yaml",
        ".drone.yml",
        ".drone.yaml",
        ".buildkite/pipeline.yml",
        ".buildkite/pipeline.yaml",
    ]
    return [path / c for c in candidates if (path / c).exists()]


def _iter_build_files(path: Path) -> list[Path]:
    """Makefiles, build scripts, and setup.py (limited-depth scan)."""
    results: list[Path] = []

    for name in ("Makefile", "GNUmakefile", "makefile", "setup.py"):
        p = path / name
        if p.exists():
            results.append(p)

    def _find_nested(directory: Path, depth: int) -> None:
        if depth > 3 or len(results) >= _FILE_SCAN_LIMIT:
            return
        try:
            for entry in directory.iterdir():
                if entry.name in _SKIP_DIRS:
                    continue
                if entry.is_dir():
                    _find_nested(entry, depth + 1)
                elif entry.name in ("Makefile", "GNUmakefile", "makefile") and entry not in results:
                    results.append(entry)
        except PermissionError:
            pass

    _find_nested(path, 0)

    for scripts_dir in (path / "scripts", path / "script"):
        if not scripts_dir.is_dir():
            continue
        for f in scripts_dir.iterdir():
            if not f.is_file():
                continue
            lower = f.name.lower()
            if any(lower.startswith(pfx) for pfx in ("build", "install", "setup", "deps", "bootstrap")):
                results.append(f)

    return results[:_FILE_SCAN_LIMIT]


def _iter_container_files(path: Path) -> list[Path]:
    """Dockerfile and Containerfile paths, including common subdirectories."""
    results: list[Path] = []
    for name in ("Dockerfile", "Containerfile"):
        p = path / name
        if p.exists():
            results.append(p)
    for subdir in ("docker", "containers", ".docker"):
        d = path / subdir
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file() and (f.name.startswith("Dockerfile") or f.name.startswith("Containerfile")):
                results.append(f)
    return results[:_FILE_SCAN_LIMIT]



# Bazel network sandbox flags — current name, negated shorthand, and the
# deprecated pre-rename name (still honored by Bazel as an alias).
_BAZEL_NETWORK_BLOCK_FLAGS: tuple[str, ...] = (
    "--sandbox_default_allow_network=false",
    "--nosandbox_default_allow_network",
    "--experimental_sandbox_default_allow_network=false",
)


def _maybe_check_witness_attestation(
    ctx: HandlerContext,
    config: dict[str, Any],
) -> WitnessCheckResult:
    """Call check_witness_attestation() unless disabled via config.

    ``verify_witness_attestations = false`` in the TOML pass config opts out
    of the network round-trip entirely — for air-gapped audits or
    environments without a usable `gh` login for the audited repo. There is
    deliberately no automatic "skip if CI text doesn't mention witness"
    heuristic: that would reintroduce exactly the kind of unreliable text-only
    guess this real verification replaced (e.g. a reusable/composite workflow
    can produce a valid attestation without the calling repo's own CI files
    ever spelling out "witness").
    """
    if not config.get("verify_witness_attestations", True):
        return WitnessCheckResult(attempted=False, detail="witness attestation verification disabled via config")

    return check_witness_attestation(ctx)


def _detect_strong_hermeticity_signal(
    path: Path,
    ci_files: list[Path],
    dependency_results: dict[str, Any],
    ctx: HandlerContext,
    config: dict[str, Any],
) -> tuple[str | None, WitnessCheckResult]:
    """Return (signal description, witness check result). Signal is None if no
    build-system-enforced hermeticity guarantee was found.

    Checks in priority order:
    1. Witness runtime attestation — a Sigstore-verified DSSE envelope from the
       repo's latest CI run, bound to its GitHub Actions OIDC identity, asserting
       no network access occurred during the build (see witness_attestation.py).
       Merely mentioning "witness run" in CI text is NOT sufficient — that only
       proves the tool ran, not what it observed, so text mentions alone are no
       longer treated as a strong signal.
    2. Nix flake used in CI — fixed-output derivations run network-isolated by default.
       Gated on RE-01.02 (BuildEnvDeclared) having PASSED: a bare flake.nix that isn't
       the project's confirmed, declared build environment isn't a strong signal on its
       own. If RE-01.02 hasn't run (e.g. this control invoked standalone), the signal is
       withheld rather than assumed — conservative-by-default.
    3. Bazel with explicit network sandbox — Bazel allows network by default, so the
       blocking flag must be present to count as a strong signal. Checked in both CI
       files (where "bazel" must also appear, to avoid matching an unrelated tool that
       happens to share a flag name) and .bazelrc (the canonical place to set it, where
       the file itself is the bazel signal).

    Comments are stripped before matching (same as ``_scan_line``) so a
    commented-out reference (e.g. ``# TODO: add witness run``) can't be
    mistaken for the real thing.
    """
    witness_result = _maybe_check_witness_attestation(ctx, config)
    if witness_result.verified and witness_result.network_clean is True:
        return f"Witness attestation verified — {witness_result.detail}", witness_result

    ci_content: dict[str, str] = {}
    for f in ci_files:
        try:
            raw = f.read_text(encoding="utf-8")
        except Exception:
            continue
        ci_content[f.name] = "\n".join(_strip_comment(line) for line in raw.splitlines())

    if (path / "flake.nix").exists() and dependency_results.get("RE-01.02") == "PASS":
        nix_hits = sorted(
            name
            for name, content in ci_content.items()
            if any(cmd in content for cmd in ("nix build", "nix develop", "nix run", "nix flake"))
        )
        if nix_hits:
            return f"Nix flake build in CI ({', '.join(nix_hits)})", witness_result

    has_bazel = any((path / f).exists() for f in ("WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel", "BUILD.bazel"))
    if has_bazel:
        bazel_hits: list[str] = [
            name
            for name, content in ci_content.items()
            if "bazel" in content.lower() and any(flag in content for flag in _BAZEL_NETWORK_BLOCK_FLAGS)
        ]

        bazelrc = path / ".bazelrc"
        if bazelrc.exists():
            try:
                raw = bazelrc.read_text(encoding="utf-8")
            except Exception:
                raw = ""
            bazelrc_content = "\n".join(_strip_comment(line) for line in raw.splitlines())
            if any(flag in bazelrc_content for flag in _BAZEL_NETWORK_BLOCK_FLAGS):
                bazel_hits.append(".bazelrc")

        if bazel_hits:
            return f"Bazel with network sandbox ({', '.join(sorted(bazel_hits))})", witness_result

    return None, witness_result


def repro_hermetic_build_handler(
    config: dict[str, Any],
    ctx: HandlerContext,
) -> HandlerResult:
    """Check that CI and build files do not fetch dependencies at build time.

    v0.2: Scans GitHub Actions workflows, composite actions, non-GitHub CI
    files (GitLab CI, CircleCI, Jenkins, Azure Pipelines, Drone, Buildkite),
    Makefiles, build scripts, and Dockerfiles/Containerfiles.  Strips comments
    before pattern matching to reduce false positives.  System-package installs
    inside Dockerfiles are DEFERRED — building the image environment is fine;
    fetching application dependencies at build time is not.

    v0.3: Adds a Sigstore-verified Witness/runtime-trace attestation check
    (see witness_attestation.py) — fetches attestation artifacts from the
    repo's latest successful CI run via the `gh` CLI, cryptographically
    verifies them against the repo's GitHub Actions OIDC identity, and only
    treats an empty, verified network log as a strong PASS signal. A verified
    attestation that *does* record network activity is fed into the violation
    list — stronger evidence than the CI-text grep below it. Requires the
    `gh` CLI and `darnit-core[attestation]`; any missing prerequisite (no gh,
    not authenticated, no matching CI run/artifact, sigstore not installed,
    verification failure) degrades to a specific "no attestation evidence"
    reason in ``evidence["strong_signal"]``/the witness result's ``detail``,
    never to failing the audit. Set ``verify_witness_attestations = false`` in
    the TOML pass config to skip the network round-trip entirely (air-gapped
    audits, or repos with no usable `gh` login).

    Result semantics (conservative-by-default):
    - PASS:           strong hermeticity signal (verified Witness attestation,
                      Nix flake CI, Bazel sandbox)
    - FAIL:           suspicious live network-fetch pattern in any scanned file,
                      or a verified Witness attestation that recorded network activity
    - INCONCLUSIVE:   files scanned, no violations, no strong signal
                      (grep absence ≠ proof of hermeticity)
    - INCONCLUSIVE
      (confidence 0): no CI or build files found at all
    """
    path = Path(ctx.local_path)

    workflow_files = _iter_workflow_files(path)
    composite_files = _iter_composite_action_files(path)
    other_ci_files = _iter_other_ci_files(path)
    build_files = _iter_build_files(path)
    container_files = _iter_container_files(path)

    all_ci_files = workflow_files + composite_files + other_ci_files
    all_files = all_ci_files + build_files + container_files

    if not all_files:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No CI or build files found to check",
            confidence=0.0,
            evidence={
                "files_scanned": [],
                "violations_found": [],
                "deferred_found": [],
                "strong_signal": None,
            },
        )

    strong_signal, witness_result = _detect_strong_hermeticity_signal(
        path, all_ci_files, ctx.dependency_results, ctx, config
    )
    if strong_signal:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Strong hermeticity signal detected: {strong_signal}",
            confidence=0.9,
            evidence={
                "files_scanned": [str(f.relative_to(path)) for f in all_files],
                "violations_found": [],
                "deferred_found": [],
                "strong_signal": strong_signal,
            },
        )

    container_file_set = set(container_files)
    violations: list[str] = []
    deferred: list[str] = []
    files_scanned: list[str] = []

    # A verified Witness attestation that positively recorded network activity
    # is stronger evidence than the grep heuristic below — surface it as a
    # violation on its own rather than waiting for a matching CI-text pattern.
    if witness_result.verified and witness_result.network_clean is False:
        violations.append(f"witness attestation ({witness_result.evidence.get('artifact', '?')}): {witness_result.detail}")

    for f in all_files:
        is_dockerfile = f in container_file_set
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            rel = str(f.relative_to(path))
        except Exception as exc:
            logger.debug("skipped %s: %s", f, exc)
            continue

        files_scanned.append(rel)
        file_violation: str | None = None
        for line in lines:
            pattern, kind = _scan_line(line, is_dockerfile=is_dockerfile)
            if kind == "violation":
                file_violation = f"{rel}: '{pattern}'"
                break  # one violation per file is enough to flag it
            elif kind == "deferred" and pattern:
                deferred.append(f"{rel}: '{pattern}' (image build context)")

        if file_violation:
            violations.append(file_violation)

    evidence = {
        "files_scanned": files_scanned,
        "violations_found": violations,
        "deferred_found": deferred,
        "strong_signal": None,
    }

    if violations:
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"Possible live network fetches in build files: {'; '.join(violations)}",
            confidence=0.7,
            evidence=evidence,
        )

    # Clean scan but no strong signal. Per the conservative-by-default principle,
    # grep absence is not proof of hermeticity — INCONCLUSIVE until a strong signal
    # or manual review confirms the build is hermetic.
    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message=(
            f"No suspicious patterns found in {len(files_scanned)} scanned file(s) — "
            "grep absence alone cannot confirm hermeticity; "
            "a strong signal (Witness, Nix, Bazel sandbox) or manual review is needed"
        ),
        confidence=0.4,
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
        "SOURCE_DATE_EPOCH",  # Normalizes timestamps — required for repro builds
        "reprotest",  # Tool that builds twice and compares
        "diffoscope",  # Tool that diffs build artifacts
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
