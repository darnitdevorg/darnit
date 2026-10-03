"""Darnit CLI - Declarative compliance auditing.

A Terraform-like CLI for running compliance audits against repositories.

IMPORTANT: This CLI is primarily intended for debugging and development.
For production use, run darnit as an MCP server which enables full LLM
consultation capabilities for intelligent check analysis.

Usage:
    darnit serve [OPTIONS]              # Start MCP server (RECOMMENDED)
    darnit audit [OPTIONS] [REPO_PATH]  # Debug: Run audit without LLM
    darnit plan [OPTIONS] [REPO_PATH]   # Debug: Show execution plan
    darnit validate [OPTIONS] PATH      # Validate framework config
    darnit init [OPTIONS] [REPO_PATH]   # Explain project claims and operator config
    darnit list [OPTIONS]               # List available frameworks

Examples:
    # Start the MCP server (recommended for production)
    darnit serve
    darnit serve --framework <name>

    # Debug/development commands (no LLM consultation)
    darnit audit /path/to/repo
    darnit plan --tags level=1 /path/to/repo
"""

import argparse
import importlib.metadata
import json
import os
import re
import sys
from pathlib import Path

from darnit.core.logging import configure_logging, get_logger
from darnit.sieve.models import CheckResult

logger = get_logger("cli")


def _resolve_version() -> str:
    """Return the installed `darnit-core` version, or `"dev"` if unresolved.

    The PyPI distribution name is `darnit-core` (the import name and CLI
    command both remain `darnit`). When darnit is run from a source
    checkout without an editable install — or when a stale binary on
    PATH outside the workspace venv is invoked — the distribution
    metadata isn't on the import path. Fall back to `"dev"` so
    `darnit --version` never crashes on what is effectively a "no
    metadata available" condition.
    """
    try:
        return importlib.metadata.version("darnit-core")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


# Output Formatters


_PENDING_TAGS = {
    "llm_judgment": "awaiting a model judgment",
    "confirmation": "PASS candidate, not compliant until confirmed",
}


def format_result_text(result: dict) -> str:
    """Format a single result for text output."""
    status = result.get("status", "UNKNOWN")
    control_id = result.get("id", "?")
    details = result.get("details", "")

    # Status indicators
    status_icons = {
        "PASS": "✓",
        "FAIL": "✗",
        "WARN": "⚠",
        "ERROR": "!",
        "N/A": "-",
        "PENDING": "~",
    }
    icon = status_icons.get(status, "?")

    # Feature 036: annotate environmental failures so triage from this
    # output alone is possible -- "[auth]" means fix the token, an
    # unannotated FAIL means fix the repo.
    error_class = result.get("error_class")
    ec_tag = f" [{error_class}]" if error_class else ""
    pending_kind = (result.get("pending") or {}).get("kind")
    pending_tag = f" ({_PENDING_TAGS.get(pending_kind, pending_kind)})" if pending_kind else ""

    return f"  {icon} {control_id}: {status}{pending_tag}{ec_tag} - {details}"


def format_results_text(results: list[CheckResult], framework_name: str, show_all: bool = False) -> str:
    """Format all results for text output."""
    lines = [f"\n=== {framework_name} Audit Results ===\n"]

    # Group by status
    by_status = {}
    for r in results:
        status = r.get("status", "UNKNOWN")
        by_status.setdefault(status, []).append(r)

    # Summary
    total = len(results)
    passed = len(by_status.get("PASS", []))
    failed = len(by_status.get("FAIL", []))
    warned = len(by_status.get("WARN", []))
    na = len(by_status.get("N/A", []))
    errored = len(by_status.get("ERROR", []))
    pending = len(by_status.get("PENDING", []))

    lines.append(
        f"Total: {total} | Pass: {passed} | Fail: {failed} | Warn: {warned} | "
        f"N/A: {na} | Error: {errored} | Pending: {pending}\n"
    )

    # Show failures first
    if "FAIL" in by_status:
        lines.append("\n--- Failures ---")
        for r in by_status["FAIL"]:
            lines.append(format_result_text(r))

    # Show pending (model judgment or confirmation)
    if "PENDING" in by_status:
        lines.append(f"\n--- Pending ({len(by_status['PENDING'])}) ---")
        for r in by_status["PENDING"]:
            lines.append(format_result_text(r))

    # Show warnings
    if "WARN" in by_status:
        lines.append("\n--- Warnings ---")
        for r in by_status["WARN"]:
            lines.append(format_result_text(r))

    # Show errors
    if "ERROR" in by_status:
        lines.append(f"\n--- Errors ({len(by_status['ERROR'])}) ---")
        for r in by_status["ERROR"]:
            lines.append(format_result_text(r))

    # Show passes
    if "PASS" in by_status:
        lines.append(f"\n--- Passed ({len(by_status['PASS'])}) ---")
        passes = by_status["PASS"] if show_all else by_status["PASS"][:10]
        for r in passes:
            lines.append(format_result_text(r))
        if not show_all and len(by_status["PASS"]) > 10:
            lines.append(
                f"  ... and {len(by_status['PASS']) - 10} more "
                "(use --show-all to list every check)"
            )

    # With --show-all, list every remaining status (e.g. N/A) so the output
    # documents every check for conformance evidence.
    if show_all:
        for status, group in by_status.items():
            if status in ("FAIL", "WARN", "PASS", "ERROR", "PENDING"):
                continue
            lines.append(f"\n--- {status} ({len(group)}) ---")
            for r in group:
                lines.append(format_result_text(r))

    return "\n".join(lines)


def format_results_json(
    results: list[CheckResult], framework_name: str, metadata: dict | None = None
) -> str:
    """Format results as JSON."""
    output = {
        "framework": framework_name,
        **(metadata or {}),
        "results": results,
        "summary": {
            "total": len(results),
            "pass": len([r for r in results if r.get("status") == "PASS"]),
            "fail": len([r for r in results if r.get("status") == "FAIL"]),
            "warn": len([r for r in results if r.get("status") == "WARN"]),
            "na": len([r for r in results if r.get("status") == "N/A"]),
            "error": len([r for r in results if r.get("status") == "ERROR"]),
            "pending": len([r for r in results if r.get("status") == "PENDING"]),
        },
    }
    return json.dumps(output, indent=2)


def format_audit_metadata_text(metadata: dict) -> str:
    """Format the operator configuration and ignored repository settings for text output."""
    operator = metadata["operator_config"]
    digest = f" (sha256 {operator['digest']})" if operator.get("digest") else ""
    lines = [
        f"Operator configuration: {operator['source']}{digest}, "
        f"permission check: {operator['permission_check']}"
    ]
    trust = metadata.get("trust")
    if trust:
        from darnit.trust.decision import format_trust

        lines.append(f"Trust: {format_trust(trust)}")
        lines.extend(f"  warning: {w}" for w in trust.get("warnings", []))
    lines.extend(f"Warning: {w}" for w in metadata.get("warnings", []))
    ignored = metadata.get("ignored_repository_settings") or []
    if ignored:
        lines.append(f"Ignored repository settings ({len(ignored)}):")
        lines.extend(f"  {s['file']}: {s['key']} (belongs in {s['new_home']})" for s in ignored)
    unknown = metadata.get("unknown_assertions") or []
    if unknown:
        lines.append(f"Claims about unknown controls, ignored ({len(unknown)}):")
        lines.extend(f"  {a['location']}: {a['control_id']}" for a in unknown)
    return "\n".join(lines)


# Commands


def _load_operator_config(args: argparse.Namespace, audit_target: Path | None):
    """Record the launch options and load operator configuration, or log why not."""
    from darnit.config.operator.loader import (
        OperatorConfigError,
        load_operator_config,
        set_launch_options,
    )

    path = getattr(args, "operator_config", None)
    strict = getattr(args, "strict_operator_config", False)
    set_launch_options(path, strict=strict)
    try:
        return load_operator_config(path, audit_target=audit_target, strict=strict)
    except OperatorConfigError as e:
        logger.error(str(e))
        return None


def _operator_target(args: argparse.Namespace, operator) -> tuple[bool, str | None]:
    """Canonical ``--repo`` identity; ``(False, None)`` after logging when it cannot be parsed."""
    from darnit.trust.identity import canonical_identity

    raw = getattr(args, "repo", None)
    if not raw:
        return True, None
    canonical = canonical_identity(raw, operator.trust.case_insensitive_hosts)
    if canonical is None:
        logger.error(f"--repo {raw!r} is not a repository identity; expected HOST/NAMESPACE/NAME")
        return False, None
    return True, canonical


def cmd_audit(args: argparse.Namespace) -> int:
    """Run compliance audit against a repository.

    NOTE: This command runs without LLM consultation. Checks requiring
    LLM analysis will return WARN/inconclusive. For full capabilities,
    use 'darnit serve' and connect via MCP.
    """
    from darnit.config import (
        load_controls_from_effective,
        load_effective_config,
        load_effective_config_auto,
        load_effective_config_by_name,
    )
    from darnit.filtering import filter_controls, parse_tags_arg

    # Warn about limited functionality in terminal mode
    logger.warning(
        "Running in terminal mode (no LLM consultation). "
        "For full capabilities, use 'darnit serve' with an MCP client."
    )

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        logger.error(f"Repository path not found: {repo_path}")
        return 1

    operator_config = _load_operator_config(args, repo_path)
    if operator_config is None:
        return 1
    operator = operator_config.config
    ok, target = _operator_target(args, operator)
    if not ok:
        return 1

    # Load configuration
    try:
        if args.framework:
            framework_path = Path(args.framework)
            if framework_path.exists():
                config = load_effective_config(framework_path, repo_path, operator=operator)
            else:
                # Try as framework name
                config = load_effective_config_by_name(args.framework, repo_path, operator=operator)
        else:
            config = load_effective_config_auto(repo_path, operator=operator)
    except ValueError as e:
        logger.error(f"Failed to load framework: {e}")
        return 1
    except FileNotFoundError as e:
        logger.error(f"Framework not found: {e}")
        return 1

    # Load controls
    controls = load_controls_from_effective(config)
    if not controls:
        logger.warning("No controls loaded from configuration")
        return 0

    # Build filters from --tags
    filters = parse_tags_arg(args.tags) if args.tags else []

    # Parse include/exclude lists
    include_ids = set(args.include.split(",")) if args.include else None
    exclude_ids = set(args.exclude.split(",")) if args.exclude else set()

    # Apply filters
    controls = filter_controls(controls, filters, include_ids, exclude_ids)

    logger.info(f"Auditing {repo_path} with {len(controls)} controls")

    # Detect owner/repo from git if available
    from darnit.core.utils import detect_owner_repo
    from darnit.trust.decision import owner_repo_from_identity

    owner, repo = owner_repo_from_identity(target) if target else detect_owner_repo(str(repo_path))
    default_branch = _detect_default_branch(repo_path)

    # Delegate to canonical audit pipeline
    from darnit.tools.audit import run_sieve_audit

    results, _summary = run_sieve_audit(
        owner=owner,
        repo=repo,
        local_path=str(repo_path),
        default_branch=default_branch,
        level=3,
        controls=controls,
        apply_user_config=True,
        stop_on_llm=True,
        # Issue #427: the framework name has to reach the audit driver, not
        # just the control loader above. Without it the driver cannot
        # register the framework's plugin sieve handlers, and every control
        # referencing one falls through to `manual` with a WARN that reads
        # like "could not verify" rather than "handler never loaded".
        # openssf-baseline masked this because its controls use only
        # built-in handlers.
        framework_name=config.framework_name,
        operator_config=operator_config,
        target=target,
    )

    from darnit.tools.audit import audit_report_metadata

    metadata = audit_report_metadata(operator_config, str(repo_path), target, config.framework_name)

    # Output results
    if args.output == "json":
        sys.stdout.write(format_results_json(results, config.framework_name, metadata) + "\n")
    else:
        sys.stdout.write(
            format_results_text(results, config.framework_name, show_all=args.show_all) + "\n"
        )
        sys.stdout.write(format_audit_metadata_text(metadata) + "\n")

    # Return non-zero if any failures
    failures = [r for r in results if r.get("status") == "FAIL"]
    return 1 if failures and not args.no_fail else 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Show what would be checked (dry-run).

    NOTE: This is a debug/development command. For production use,
    run 'darnit serve' and connect via MCP.
    """
    from darnit.config import (
        load_effective_config,
        load_effective_config_auto,
        load_effective_config_by_name,
    )
    from darnit.filtering import matches_filters, parse_tags_arg

    repo_path = Path(args.repo_path).resolve()

    # Load configuration
    try:
        if args.framework:
            framework_path = Path(args.framework)
            if framework_path.exists():
                config = load_effective_config(framework_path, repo_path if repo_path.exists() else None)
            else:
                config = load_effective_config_by_name(args.framework, repo_path if repo_path.exists() else None)
        else:
            config = load_effective_config_auto(repo_path)
    except (ValueError, FileNotFoundError) as e:
        logger.error(f"Failed to load framework: {e}")
        return 1

    # Build filters from --tags
    filters = parse_tags_arg(args.tags) if args.tags else []

    # Parse include/exclude lists
    include_ids = set(args.include.split(",")) if args.include else None
    exclude_ids = set(args.exclude.split(",")) if args.exclude else set()

    logger.info(f"=== Execution Plan: {config.framework_name} ===")
    logger.info(f"Framework: {config.framework_name} v{config.framework_version}")
    if config.spec_version:
        logger.info(f"Spec: {config.spec_version}")
    logger.info(f"Repository: {repo_path}")
    if filters:
        logger.info(f"Filters: {', '.join(f'{f.field}{f.operator}{f.value}' for f in filters)}")
    if include_ids:
        logger.info(f"Include: {', '.join(sorted(include_ids))}")
    if exclude_ids:
        logger.info(f"Exclude: {', '.join(sorted(exclude_ids))}")

    # Group controls by level
    by_level = {}
    for cid, ctrl in config.controls.items():
        level = ctrl.level
        by_level.setdefault(level, []).append((cid, ctrl))

    total_shown = 0
    total_filtered = 0

    for level in sorted(by_level.keys()):
        controls = by_level[level]
        shown_controls = []

        for cid, ctrl in sorted(controls, key=lambda x: x[0]):
            # Apply include/exclude lists
            if include_ids and cid not in include_ids:
                total_filtered += 1
                continue
            if cid in exclude_ids:
                total_filtered += 1
                continue
            # Apply filters
            if not matches_filters(ctrl, filters):
                total_filtered += 1
                continue
            shown_controls.append((cid, ctrl))

        if not shown_controls:
            continue

        logger.info(f"Level {level} ({len(shown_controls)} controls):")
        for cid, ctrl in shown_controls:
            if ctrl.is_applicable():
                adapter = ctrl.check_adapter
                logger.info(f"  • {cid}: {ctrl.name} [adapter: {adapter}]")
            else:
                logger.info(f"  - {cid}: {ctrl.name} [skipped: {ctrl.status_reason}]")
        total_shown += len(shown_controls)

    if total_filtered > 0:
        logger.info(f"({total_filtered} controls filtered out)")

    # Show excluded controls
    excluded = config.get_excluded_controls()
    if excluded:
        logger.info(f"Excluded ({len(excluded)}):")
        for cid, reason in excluded.items():
            logger.info(f"  - {cid}: {reason}")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a framework configuration file."""
    from darnit.config import load_framework_config, validate_framework_config

    framework_path = Path(args.framework_path)
    if not framework_path.exists():
        logger.error(f"Framework file not found: {framework_path}")
        return 1

    try:
        config = load_framework_config(framework_path)
    except Exception as e:
        logger.error(f"Failed to parse framework: {e}")
        return 1

    errors = validate_framework_config(config)

    if errors:
        logger.error(f"Validation failed with {len(errors)} error(s):")
        for error in errors:
            logger.error(f"  • {error}")
        return 1
    else:
        logger.info(f"Framework '{config.metadata.name}' is valid")
        logger.info(f"  Controls: {len(config.controls)}")
        logger.info(f"  Adapters: {len(config.adapters)}")

        # Show level breakdown
        by_level = {}
        for _cid, ctrl in config.controls.items():
            by_level.setdefault(ctrl.level, 0)
            by_level[ctrl.level] += 1

        logger.info(f"  By level: {', '.join(f'L{k}={v}' for k, v in sorted(by_level.items()))}")
        return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Explain where project claims and operator configuration live; writes nothing."""
    from darnit.config.operator.loader import default_config_path

    repo_path = Path(args.repo_path).resolve()
    if args.framework:
        framework = args.framework
    else:
        from darnit.core.discovery import discover_implementations

        impls = discover_implementations()
        framework = next(iter(impls)) if len(impls) == 1 else "openssf-baseline"

    lines = [
        "darnit does not create configuration files in the repository; nothing was written.",
        "",
        f"Project claims live in {repo_path / '.project' / 'darnit.yaml'} and are committed with the project.",
        "Record a control that does not apply like this:",
        "",
        "  controls:",
        "    OSPS-BR-02.01:",
        "      status: n/a",
        '      reason: "Pre-1.0 project with no releases yet"',
        "",
        "A claim counts only when the operator trusts the repository and no evidence contradicts it;",
        "otherwise it is reported as pending and the control counts as non-compliant.",
        "",
        f"Operator configuration (tool settings; never read from a repository): {default_config_path()}",
        "  darnit config show                           shows the file in use and its settings",
        "  darnit config trust add HOST/NAMESPACE/NAME  trusts a repository's claims",
        "Name the audited repository with --repo HOST/NAMESPACE/NAME; a checkout's own remotes are never trusted.",
        "",
        f"Select the framework per run with --framework {framework}.",
    ]
    if (repo_path / ".baseline.toml").exists():
        lines.extend(["", "This repository has a deprecated .baseline.toml; run `darnit config migrate` to move it."])
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List available frameworks."""
    from darnit.config import list_available_frameworks, load_framework_by_name

    frameworks = list_available_frameworks()

    if not frameworks:
        logger.info("No frameworks found. Install a framework package like darnit-baseline.")
        return 0

    logger.info("Available Frameworks:")
    for name in frameworks:
        try:
            config = load_framework_by_name(name)
            logger.info(f"  • {name}")
            logger.info(f"    Display: {config.metadata.display_name}")
            logger.info(f"    Version: {config.metadata.version}")
            if config.metadata.spec_version:
                logger.info(f"    Spec: {config.metadata.spec_version}")
            logger.info(f"    Controls: {len(config.controls)}")
        except Exception as e:
            logger.info(f"  • {name} (error loading: {e})")

    return 0

def cmd_profiles(args: argparse.Namespace) -> int:
    """List available audit profiles defined by loaded implementations."""
    from darnit.core.discovery import discover_implementations

    impls = discover_implementations()
    if not impls:
        logger.info("No implementations found.")
        return 0

    filter_impl = getattr(args, "impl", None)
    found_any = False

    for name, impl in impls.items():
        if filter_impl and name != filter_impl:
            continue
        get_profiles = getattr(impl, "get_audit_profiles", None)
        if not callable(get_profiles):
            continue
        profiles = get_profiles()
        if not profiles:
            continue
        found_any = True
        logger.info(f"{name}:")
        for profile_name, profile in profiles.items():
            ctrl_count = len(profile.controls) if profile.controls else "tag-based"
            logger.info(f"  {profile_name:<25} {profile.description} ({ctrl_count} controls)")

    if not found_any:
        logger.info("No audit profiles defined by any implementation.")

    return 0

def _find_skills_dir() -> Path | None:
    """Find the skills directory from the darnit package."""
    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        has_skills = any(
            (d / "SKILL.md").exists() for d in skills_dir.iterdir() if d.is_dir()
        )
        if has_skills:
            return skills_dir
    return None


def _install_skills(target_dir: Path, force: bool = False) -> int:
    """Copy skill directories to a target location."""
    import shutil

    source = _find_skills_dir()
    if source is None:
        logger.warning("No skills found in darnit-baseline package. Skipping skill installation.")
        return 0

    skill_dirs = [d for d in source.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
    if not skill_dirs:
        logger.warning("No valid skill directories found.")
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    installed = 0

    for skill_dir in skill_dirs:
        dest = target_dir / skill_dir.name
        if dest.exists() and not force:
            logger.info(f"  Skill '{skill_dir.name}' already exists at {dest}, skipping (use --force to overwrite)")
            continue
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_dir, dest)
        installed += 1
        logger.info(f"  ✓ Installed skill '{skill_dir.name}' → {dest}")

    return installed


def cmd_install(args: argparse.Namespace) -> int:
    """Install darnit MCP server config and skills into a supported client."""
    import shutil

    if args.client == "claude":
        logger.warning(
            "`--client claude` is deprecated; use `--client claude-code` for Claude Code "
            "or `--client claude-desktop` for Claude Desktop."
        )
    if args.project and args.client not in ("claude", "claude-code"):
        logger.warning(
            "`--project` only applies to Claude Code (writes .mcp.json). "
            f"Ignoring --project for --client {args.client}."
        )

    if args.client in ("claude", "claude-code"):
        if args.project:
            settings_path = Path.cwd() / ".mcp.json"
            logger.warning(
                "Writing a project-scoped MCP registration to %s. Anyone who can change this "
                "repository can change how darnit is launched for it, including which operator "
                "configuration it reads. Registering at user scope (the default, without --project) "
                "is recommended.",
                settings_path,
            )
        else:
            settings_path = Path.home() / ".claude.json"
    elif args.client == "claude-desktop":
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "Claude"
        elif sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Claude"
        else:
            base = Path.home() / ".config" / "Claude"
        settings_path = base / "claude_desktop_config.json"
    else:  # cursor
        settings_path = Path.home() / ".cursor" / "mcp.json"

    settings_path.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if settings_path.exists():
        try:
            config = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in settings file: {settings_path}: {e}")
            return 1

        backup_path = settings_path.with_suffix(settings_path.suffix + ".bak")
        shutil.copy2(settings_path, backup_path)

    mcp_servers = config.setdefault("mcpServers", {})
    darnit_entry = {
        "command": "uvx",
        "args": ["--from", "darnit-mcp", "darnit", "serve"],
    }

    if "darnit" in mcp_servers and not args.force:
        response = input(f"'darnit' entry already exists in {settings_path}. Overwrite? [y/N]: ").strip().lower()
        if response not in {"y", "yes"}:
            logger.info("Install cancelled.")
            return 1

    mcp_servers["darnit"] = darnit_entry

    try:
        json.dumps(config)  # validate before write
        settings_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to write settings file: {e}")
        return 1

    logger.info(f"✓ Installed darnit MCP server config in {settings_path}")

    # Install skills
    if not args.mcp_only and args.client in ("claude", "claude-code"):
        if args.project:
            skills_target = Path.cwd() / ".claude" / "skills"
            logger.info(f"Installing skills (project) → {skills_target}")
        else:
            skills_target = Path.home() / ".claude" / "skills"
            logger.info(f"Installing skills (global) → {skills_target}")

        count = _install_skills(skills_target, force=args.force)
        if count > 0:
            logger.info(f"✓ Installed {count} skill(s)")
        elif count == 0:
            logger.info("  No new skills to install")
    elif args.mcp_only:
        logger.info("  Skipping skill installation (--mcp-only)")

    logger.info("Next step: restart your AI client and use the configured MCP server.")
    logger.info("Skills available: /darnit-audit, /darnit-data, /darnit-comply, /darnit-remediate")
    return 0

# Safety ceiling on audit<->collect_context rounds. Each iteration resolves ALL
# pending questions in one batch (the answers comprehension in cmd_run), so this
# bounds re-audit rounds, not the number of controls.
MAX_AGENT_ITERATIONS = 10


_PAST = {"create": "created", "modify": "modified"}


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _remediation_lines(results: list[dict], applied: bool) -> list[str]:
    """Per-control lines for the remediation step of ``darnit run`` (FR-027)."""
    lines: list[str] = []
    for result in results:
        lines.append(f"  {result['control_id']}")
        body: list[str] = []
        if result.get("status") == "skipped":
            body.append(f"skipped: {result.get('reason', '')}")
        elif not applied:
            for item in result.get("plan", []):
                for change in item["file_changes"]:
                    if change["action"] == "none":
                        body.append(f"{change['path']}: not written ({change['reason']})")
                    else:
                        body.append(f"{change['action']} {change['path']}")
                body += [f"command: {' '.join(command)}" for command in item["commands"]]
                if not item["previewable"]:
                    body.append(f"{item['step']}: cannot be previewed exactly")
                if item["requires_individual_approval"]:
                    body.append(f"needs individual approval: {item['digest']}")
        else:
            for change in result.get("file_changes", []):
                if change["action"] == "none":
                    body.append(f"{change['path']}: not written ({change['reason']})")
                else:
                    body.append(f"{_PAST[change['action']]} {change['path']}")
            body += [f"approved: {approval['digest']}" for approval in result.get("approvals", [])]
            body += [
                f"needs approval: {digest} (no step of this remediation was run)"
                for digest in result.get("needs_approval", [])
            ]
            if not result.get("success") and not result.get("needs_approval"):
                body.append(f"not done: {result.get('message', '')}")
        lines += [f"    {_ascii(line)}" for line in body]
    return lines


def cmd_run(args: argparse.Namespace) -> int:
    """Run the audit workflow with human feedback.

    Runs the audit -> collect_context -> remediate pipeline. Checks that
    require LLM judgement halt for an external agent (e.g. Claude Code);
    questions needing a human are handled per --feedback mode. Automated
    in-process LLM backends are not wired into this command yet.

    Remediation is previewed; files and platform settings change only with
    ``--apply`` (FR-027).
    """
    from darnit.agent.feedback import get_feedback_handler
    from darnit.agent.graph import audit, collect_context, remediate, route
    from darnit.agent.state import AuditState

    repo_path = str(Path(args.repo_path).resolve())

    operator_config = _load_operator_config(args, Path(repo_path))
    if operator_config is None:
        return 1
    ok, target = _operator_target(args, operator_config.config)
    if not ok:
        return 1

    from darnit.trust.decision import decide_trust, format_trust, owner_repo_from_identity

    trust = decide_trust(target, operator_config.config, repo_path).report()

    # Feedback mode — default to interactive if terminal, noninteractive if not
    feedback_mode = args.feedback_mode
    if feedback_mode == "auto":
        feedback_mode = "interactive" if sys.stdin.isatty() else "noninteractive"

    print("\nDarnit run")
    print(f"  Repository : {repo_path}")
    print(f"  Feedback   : {feedback_mode}")
    print(f"  Trust      : {format_trust(trust)}")
    for warning in trust["warnings"]:
        print(f"  Warning    : {warning}")
    print(f"  Remediate  : {'apply' if args.apply else 'preview (nothing is written; pass --apply to write)'}")
    print()

    # framework_name=None auto-resolves from .baseline.toml inside audit().
    owner, repo = owner_repo_from_identity(target) if target else (None, None)
    state = AuditState(
        local_path=repo_path,
        owner=owner,
        repo=repo,
        target=target,
        framework_name=getattr(args, "framework", None),
        level=getattr(args, "level", 3),
    )

    feedback = get_feedback_handler(feedback_mode)

    # Inline orchestration (replaces LangGraph): audit, then route() decides the
    # next node ("audit" | "collect_context" | "remediate" | "end"). A re-audit
    # is only meaningful right after collect_context (which clears audit_results
    # to request one), so we re-audit inside that branch. A bare "audit" from
    # route here means the audit produced no results — stop rather than spin.
    try:
        state = audit(state)
        for _ in range(MAX_AGENT_ITERATIONS):
            if state.error:
                break
            step = route(state)
            if step == "collect_context":
                # Noninteractive ask() always returns None -> answers ends up
                # empty -> we break below with questions left queued for the
                # summary. Interactive prompts the user.
                answers = {
                    q.context_key: (feedback.ask(q.control_id, q.question) or "")
                    for q in state.feedback_questions
                    if not q.answered
                }
                answers = {k: v for k, v in answers.items() if v}
                if not answers:
                    break  # nothing answered — avoid re-routing forever
                state = collect_context(state, answers, operator=operator_config.config)
                state = audit(state)  # re-audit with confirmed context
            elif step == "remediate":
                from darnit.remediation.platform import terminal_approver

                approver = terminal_approver() if feedback_mode == "interactive" else None
                state = remediate(
                    state,
                    dry_run=not args.apply,
                    approver=approver,
                    item_approver=approver.approve_item if approver is not None else None,
                )
                break
            else:  # "audit" (no results) or "end"
                break
    except Exception as e:
        logger.error(f"Agent run failed: {e}")
        return 1

    final_state = state

    # AuditState is a dataclass — attribute access, real field names.
    check_results = final_state.audit_results or []
    error = final_state.error

    total = len(check_results)
    passed = len([r for r in check_results if r.get("status") == "PASS"])
    failed = len([r for r in check_results if r.get("status") == "FAIL"])
    warned = len([r for r in check_results if r.get("status") == "WARN"])

    print("Run complete.")
    print(f"  Total  : {total}")
    print(f"  Passed : {passed}")
    print(f"  Failed : {failed}")
    print(f"  Warned : {warned}")

    if final_state.remediation_results:
        if args.apply:
            print("\nRemediation applied:")
        else:
            print("\nRemediation preview (nothing was written; pass --apply to write these changes):")
        for line in _remediation_lines(final_state.remediation_results, applied=args.apply):
            print(line)

    platform = [p for r in final_state.remediation_results for p in r.get("platform", [])]
    if platform:
        policy = operator_config.config.remediation
        print(f"\nPlatform changes (policy: platform={policy.platform}, high_impact={policy.high_impact}):")
        for result in {(p.get("change_set") or {}).get("digest") or id(p): p for p in platform}.values():
            target = result.get("target") or {}
            where = f"{target.get('kind', result.get('target_kind'))} {target.get('branch') or ''}".strip()
            digest = (result.get("change_set") or {}).get("digest", "")
            print(f"  {result['kind']:<15} {where} {result.get('reason') or ''} {digest}".rstrip())

    # Pending human feedback — FeedbackQuestion is a dataclass, not a dict.
    pending = [q for q in final_state.feedback_questions if not q.answered]
    if pending:
        print(f"\nPending human feedback ({len(pending)} unanswered):")
        for q in pending:
            print(f"  Control : {q.control_id}")
            print(f"  Question: {q.question}")
            print()

    if error:
        print(f"\nError: {error}")
        return 1

    return 1 if failed else 0

def cmd_harness(args: argparse.Namespace) -> int:
    """Run the harness: end-to-end audit with in-band LLM dispatch.

    Feature 026. Non-interactive by default; consumes ANTHROPIC_API_KEY
    from env; dispatches LLM steps via PydanticAILLMStep; produces a
    Markdown or JSON report; exits with a documented code.
    """
    import asyncio
    import sys

    from darnit.core.llm_step import PydanticAILLMStep
    from darnit.harness.answer_sources import AnswerSourceLoadError
    from darnit.harness.driver import (
        HarnessRun,
        HarnessRunTimeout,
        HarnessSetupError,
    )
    from darnit.harness.exit_codes import HarnessExitCode

    repo_path = str(Path(args.repo_path).resolve())
    output_format = getattr(args, "format", "markdown")
    output_path = getattr(args, "output", None)
    answers_path = getattr(args, "answers", None)
    interactive = getattr(args, "interactive", False)
    per_resolver_timeout_s = getattr(args, "per_resolver_timeout", None)

    # Feature 027: --interactive fail-fast guard (IR-7..IR-9 / SC-005).
    # Must run BEFORE any control iteration so a CI misfire never silently
    # skips every question.
    if interactive:
        if not sys.stdin.isatty():
            _emit_exit_summary(
                "setup_error, interactive channel unavailable "
                "(stdin is not a TTY)",
                HarnessExitCode.SETUP_ERROR,
            )
            return int(HarnessExitCode.SETUP_ERROR)
        try:
            _tty_probe = open("/dev/tty", "r+", buffering=1, encoding="utf-8")  # noqa: SIM115
            _tty_probe.close()
        except OSError as exc:
            _emit_exit_summary(
                "setup_error, interactive channel unavailable "
                f"(/dev/tty not openable: {exc.strerror or type(exc).__name__})",
                HarnessExitCode.SETUP_ERROR,
            )
            return int(HarnessExitCode.SETUP_ERROR)

    operator_config = _load_operator_config(args, Path(repo_path))
    if operator_config is None:
        _emit_exit_summary("setup_error, operator configuration unusable", HarnessExitCode.SETUP_ERROR)
        return int(HarnessExitCode.SETUP_ERROR)
    ok, target = _operator_target(args, operator_config.config)
    if not ok:
        _emit_exit_summary("setup_error, --repo is not a repository identity", HarnessExitCode.SETUP_ERROR)
        return int(HarnessExitCode.SETUP_ERROR)

    # Build the resolver via the explicit factory. Any AnswerSourceLoadError
    # from a bad --answers file surfaces as a SETUP_ERROR.
    try:
        resolver = HarnessRun.build_default_resolver(
            local_path=repo_path,
            answers_path=answers_path,
        )
    except AnswerSourceLoadError as exc:
        _emit_exit_summary(f"setup_error, {exc}", HarnessExitCode.SETUP_ERROR)
        return int(HarnessExitCode.SETUP_ERROR)
    except FileNotFoundError as exc:
        _emit_exit_summary(f"setup_error, {exc}", HarnessExitCode.SETUP_ERROR)
        return int(HarnessExitCode.SETUP_ERROR)

    # Feature 027: build the QuestionResolver chain via entry-point discovery.
    # PR #367 review Constitution IV fix: external resolvers stay out of the
    # chain unless --allow-external-resolvers is set. An answer they produce
    # is recorded with authority="asserted", so silent invocation would let
    # any installed third-party package produce dispositive-strength values
    # without operator opt-in.
    allow_external_resolvers = getattr(args, "allow_external_resolvers", False)
    try:
        question_resolvers = HarnessRun.build_default_resolver_chain(
            interactive=interactive,
            allow_external_resolvers=allow_external_resolvers,
        )
    except HarnessSetupError as exc:
        _emit_exit_summary(f"setup_error, {exc}", HarnessExitCode.SETUP_ERROR)
        return int(HarnessExitCode.SETUP_ERROR)

    if question_resolvers:
        harness_logger = get_logger("harness")
        harness_logger.info(
            "harness: resolvers configured: %s",
            [getattr(r, "name", "unknown") for r in question_resolvers],
        )

    run = HarnessRun(
        local_path=repo_path,
        framework_name=getattr(args, "framework", None),
        level=getattr(args, "level", 3),
        answer_resolver=resolver,
        llm_step=PydanticAILLMStep(),
        per_call_timeout_s=getattr(args, "per_call_timeout", 60),
        total_run_timeout_s=getattr(args, "total_run_timeout", 900),
        question_resolvers=question_resolvers,
        per_resolver_timeout_s=per_resolver_timeout_s,
        operator_config=operator_config,
        target=target,
    )

    try:
        report = asyncio.run(run.run())
    except HarnessSetupError as exc:
        _emit_exit_summary(f"setup_error, {exc}", HarnessExitCode.SETUP_ERROR)
        return int(HarnessExitCode.SETUP_ERROR)
    except HarnessRunTimeout as exc:
        _emit_exit_summary(f"internal_error, {exc}", HarnessExitCode.INTERNAL_ERROR)
        return int(HarnessExitCode.INTERNAL_ERROR)
    except Exception as exc:
        _emit_exit_summary(
            f"internal_error, {type(exc).__name__}: {exc}",
            HarnessExitCode.INTERNAL_ERROR,
        )
        return int(HarnessExitCode.INTERNAL_ERROR)

    # Render the report
    if output_format == "json":
        text = report.to_json()
    else:
        text = report.to_markdown()

    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")

    # Exit summary. Order matches CLI-13 exactly:
    #   `complete, <P> PASS, <F> FAIL, <W> WARN, <PEND> pending, exit <N>`
    # so CI parsers written against the contract keep working. Answered
    # count is appended AFTER `pending`; the CLI-13 grep pattern is a
    # prefix match on positional fields, so the extra trailing field is
    # additive rather than positional-shifting. PR #367 review fix.
    s = report.summary
    answered_count = len(report.answered_feedback)
    pending_count = len(report.pending_feedback)
    _emit_exit_summary(
        f"complete, {s.pass_} PASS, {s.fail} FAIL, {s.warn} WARN, "
        f"{pending_count} pending, {answered_count} answered",
        HarnessExitCode(report.exit_class),
    )
    return report.exit_class


def _emit_exit_summary(reason: str, exit_code: int) -> None:
    """Emit the one-line stderr summary before process exit (contract CLI-13)."""
    harness_logger = get_logger("harness")
    harness_logger.info("harness: %s, exit %d", reason, int(exit_code))


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the MCP server.

    Supports two modes:
    1. With config file: `darnit serve config.toml` - Uses TOML-defined tools
    2. Without config: `darnit serve` - Auto-detects framework (legacy mode)
    """
    import os

    try:
        from darnit.server import create_server
    except ImportError:
        logger.error("MCP server dependencies not installed. Run: pip install mcp")
        return 1

    config_path = getattr(args, "config", None)

    operator_config = _load_operator_config(args, None)
    if operator_config is None:
        return 1
    launch = {
        "operator_config_path": getattr(args, "operator_config", None),
        "strict_operator_config": getattr(args, "strict_operator_config", False),
    }

    if config_path:
        # New mode: Use TOML config file
        if not os.path.exists(config_path):
            logger.error(f"Config file not found: {config_path}")
            return 1

        try:
            server = create_server(config_path, **launch)
            logger.info(f"Starting MCP server from {config_path}")
            server.run()
            return 0
        except Exception as e:
            logger.error(f"Failed to create server: {e}")
            return 1
    else:
        # Legacy mode: Auto-detect framework
        # For now, try to find a framework config
        from darnit.config import list_available_frameworks, resolve_framework_path

        framework_name = getattr(args, "framework", None)
        if not framework_name:
            frameworks = list_available_frameworks()
            allowed = operator_config.config.plugins.allowed
            if allowed:
                frameworks = [f for f in frameworks if f in allowed]
            if frameworks:
                framework_name = frameworks[0]  # Default to first available
            else:
                logger.error(
                    "No framework specified and none found. "
                    "Use 'darnit serve config.toml' or install a framework package."
                )
                return 1

        # Get framework path and use it as config
        try:
            framework_path = resolve_framework_path(framework_name)
            if not framework_path:
                logger.error(f"Framework not found: {framework_name}")
                return 1
            server = create_server(str(framework_path), **launch)
            logger.info(f"Starting MCP server with framework: {framework_name}")
            server.run()
            return 0
        except Exception as e:
            logger.error(f"Failed to start server with framework '{framework_name}': {e}")
            return 1


_ENV_REFERENCE = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")
_SECRET_KEY = re.compile(r"(?i)secret|token|password|passwd|credential|key")


def _redact_operator_settings(data: dict) -> dict:
    """Show MCP server env values as variable names and hide store secrets."""

    def env_name(value: object) -> str:
        match = _ENV_REFERENCE.match(str(value))
        return f"${match.group(1)}" if match else "[redacted]"

    redacted = dict(data)
    redacted["mcp_servers"] = {
        name: {**server, "env": {k: env_name(v) for k, v in (server.get("env") or {}).items()}}
        for name, server in (data.get("mcp_servers") or {}).items()
    }
    redacted["stores"] = {
        kind: {
            k: (env_name(v) if _SECRET_KEY.search(k) and k != "backend" else v)
            for k, v in (block or {}).items()
        }
        for kind, block in (data.get("stores") or {}).items()
        if block
    }
    return redacted


def cmd_config_show(args: argparse.Namespace) -> int:
    """Print the operator configuration darnit would use and its effective settings."""
    loaded = _load_operator_config(args, None)
    if loaded is None:
        return 1

    settings = loaded.config.model_dump(mode="json", exclude_none=True)
    if loaded.source != "builtin-defaults":
        import tomllib

        raw = tomllib.loads(Path(loaded.source).read_text(encoding="utf-8"))
        # Show store values as written; the parsed model has already substituted $VAR references.
        settings["stores"] = raw.get("stores", {})
        for name, server in raw.get("mcp_servers", {}).items():
            settings["mcp_servers"][name]["env"] = server.get("env", {})

    lines = [
        f"source: {loaded.source}",
        f"digest: {loaded.digest or 'none'}",
        f"permission check: {loaded.permission_check}",
        f"strict: {'yes' if loaded.strict else 'no'}",
        f"searched: {', '.join(loaded.searched)}",
        f"remediation policy: platform={loaded.config.remediation.platform} "
        f"high_impact={loaded.config.remediation.high_impact}",
        "effective settings:",
        json.dumps(_redact_operator_settings(settings), indent=2, sort_keys=True),
    ]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def cmd_config_trust(args: argparse.Namespace) -> int:
    """Add, list, or remove entries of ``[trust].repos`` in the operator configuration file."""
    from darnit.config.operator.loader import default_config_path
    from darnit.config.operator.trust_repos import (
        TrustEditError,
        add_trusted_repo,
        list_trusted_repos,
        remove_trusted_repo,
    )

    path = Path(args.operator_config).expanduser() if args.operator_config else default_config_path()
    try:
        if args.trust_command == "list":
            for entry in list_trusted_repos(path):
                sys.stdout.write(f"{entry}\n")
        elif args.trust_command == "add":
            if add_trusted_repo(path, args.identity):
                logger.info(f"Added {args.identity} to trust.repos in {path}")
            else:
                logger.info(f"{args.identity} is already in trust.repos in {path}")
        else:
            remove_trusted_repo(path, args.identity)
            logger.info(f"Removed {args.identity} from trust.repos in {path}")
    except TrustEditError as e:
        logger.error(str(e))
        return 1
    return 0


def cmd_config_migrate(args: argparse.Namespace) -> int:
    """Move .baseline.toml claims to .project/darnit.yaml and print a proposed operator fragment."""
    from darnit.config.operator.loader import default_config_path
    from darnit.config.operator.migrate import MigrationError, migrate_baseline_toml

    repo_path = Path(args.repo_path).resolve()
    try:
        result = migrate_baseline_toml(repo_path, force=args.force)
    except MigrationError as e:
        logger.error(str(e))
        return 1

    lines = [f"Claims in {result.project_file}:"]
    lines.extend(f"  written: {cid}" for cid in result.written)
    lines.extend(f"  already present: {cid}" for cid in result.unchanged)
    lines.extend(
        f"  kept existing claim for {cid} (re-run with --force to replace it)" for cid in result.skipped
    )
    if not (result.written or result.unchanged or result.skipped):
        lines.append("  none")
    if result.not_migrated:
        lines.append("Not migrated (no equivalent): " + ", ".join(result.not_migrated))
    operator_path = default_config_path()
    if result.operator_fragment:
        lines.extend(
            [
                "",
                f"Proposed operator configuration (not written; review it and add it to {operator_path}):",
                "",
                result.operator_fragment.rstrip("\n"),
            ]
        )
    lines.extend(
        [
            "",
            "Next steps:",
            f"  1. Review {result.project_file.relative_to(repo_path)} and commit it.",
            f"  2. Add the tool settings you want to {operator_path} (`darnit config show` prints the file in use).",
            "  3. Claims count only for repositories you trust: `darnit config trust add HOST/NAMESPACE/NAME`,",
            "     then audit with --repo HOST/NAMESPACE/NAME.",
            "  4. Re-run the audit, compare results, then delete .baseline.toml.",
        ]
    )
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


# Helpers


def _detect_default_branch(repo_path: Path) -> str:
    """Detect the default branch name."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        if result.returncode == 0:
            # refs/remotes/origin/main -> main
            return result.stdout.strip().split("/")[-1]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return "main"


# Main Entry Point


def _add_operator_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--operator-config",
        metavar="PATH",
        help="Operator configuration file (default: the per-user darnit config.toml)",
    )
    parser.add_argument(
        "--strict-operator-config",
        action="store_true",
        help="Refuse an operator configuration file that fails the permission check "
             "(always on in recognized CI)",
    )


def _add_target_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo",
        metavar="HOST/NS/NAME",
        help="Identity of the repository being audited (e.g. github.com/org/project). "
             "Trust is decided from this identity; the checkout's own remotes are never trusted.",
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="darnit",
        description="Declarative compliance auditing for software projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "-V", "--version",
        action="version",
        # PyPI distribution name is `darnit-core` (the CLI command stays `darnit`).
        # Fall back to "dev" when running from a non-installed source checkout
        # so the CLI never crashes on `--version` just because the package
        # metadata isn't on the import path.
        version=f"%(prog)s {_resolve_version()}",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress non-essential output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # serve command (primary - listed first)
    serve_parser = subparsers.add_parser(
        "serve",
        help="Start MCP server (recommended)",
        description="Start darnit as an MCP server. This is the recommended way to use darnit "
                    "as it enables full LLM consultation capabilities for intelligent analysis.\n\n"
                    "Usage:\n"
                    "  darnit serve config.toml      # Use TOML config file\n"
                    "  darnit serve --framework NAME # Use named framework\n"
                    "  darnit serve                  # Auto-detect framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    serve_parser.add_argument(
        "config",
        nargs="?",
        help="Path to TOML config file (e.g., my-framework.toml)",
    )
    serve_parser.add_argument(
        "-f", "--framework",
        help="Framework to use (default: auto-detect). Ignored if config file is provided.",
    )
    _add_operator_config_args(serve_parser)
    serve_parser.set_defaults(func=cmd_serve)

    # audit command (debug)
    audit_parser = subparsers.add_parser(
        "audit",
        help="[Debug] Run audit without LLM",
        description="Run compliance audit in terminal mode. NOTE: This runs without LLM "
                    "consultation - checks requiring analysis will return WARN/inconclusive. "
                    "For full capabilities, use 'darnit serve' with an MCP client.",
    )
    audit_parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    audit_parser.add_argument(
        "-f", "--framework",
        help="Framework to use (name or path to .toml file)",
    )
    audit_parser.add_argument(
        "-t", "--tags",
        action="append",
        default=[],
        help="Filter controls by attributes (e.g., level=1, domain=VM, security). "
             "Multiple filters use AND logic. Bare values match tags list.",
    )
    audit_parser.add_argument(
        "--include",
        help="Include only these control IDs (comma-separated)",
    )
    audit_parser.add_argument(
        "--exclude",
        help="Exclude these control IDs (comma-separated)",
    )
    audit_parser.add_argument(
        "-o", "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    audit_parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Don't exit with error code on failures",
    )
    audit_parser.add_argument(
        "--show-all",
        action="store_true",
        help="List every check in text output: show all passed checks (no truncation) "
             "and include N/A checks. Useful for documenting full OSPS Baseline conformance.",
    )
    audit_parser.add_argument(
        "--profile", "-p",
        dest="profile",
        default=None,
        help="Audit profile name to filter controls (e.g., 'level1_quick' or 'openssf-baseline:level1_quick')",
    )
    _add_operator_config_args(audit_parser)
    _add_target_arg(audit_parser)
    audit_parser.set_defaults(func=cmd_audit)

    # plan command (debug)
    plan_parser = subparsers.add_parser(
        "plan",
        help="[Debug] Show execution plan",
        description="Show what controls would be checked. This is a debug/development command.",
    )
    plan_parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to repository",
    )
    plan_parser.add_argument(
        "-f", "--framework",
        help="Framework to use",
    )
    plan_parser.add_argument(
        "-t", "--tags",
        action="append",
        default=[],
        help="Filter controls by attributes (e.g., level=1, domain=VM, security). "
             "Multiple filters use AND logic. Bare values match tags list.",
    )
    plan_parser.add_argument(
        "--include",
        help="Include only these control IDs (comma-separated)",
    )
    plan_parser.add_argument(
        "--exclude",
        help="Exclude these control IDs (comma-separated)",
    )
    plan_parser.add_argument(
        "--profile", "-p",
        dest="profile",
        default=None,
        help="Audit profile name to filter controls",
    )
    plan_parser.set_defaults(func=cmd_plan)

    # profiles command
    profiles_parser = subparsers.add_parser(
        "profiles",
        help="List available audit profiles",
        description="List named audit profiles defined by loaded implementations.",
    )
    profiles_parser.add_argument(
        "--impl",
        default=None,
        help="Filter to a specific implementation (e.g., 'openssf-baseline')",
    )
    profiles_parser.set_defaults(func=cmd_profiles)

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate framework config")
    validate_parser.add_argument(
        "framework_path",
        help="Path to framework .toml file",
    )
    validate_parser.set_defaults(func=cmd_validate)

    # init command
    init_parser = subparsers.add_parser(
        "init", help="Explain where project claims and operator configuration live"
    )
    init_parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to repository",
    )
    init_parser.add_argument(
        "-f", "--framework",
        help="Framework to suggest (default: auto-detect)",
    )
    init_parser.set_defaults(func=cmd_init)

    # list command
    list_parser = subparsers.add_parser("list", help="List available frameworks")
    list_parser.set_defaults(func=cmd_list)

    # run command (agentic)
    run_parser = subparsers.add_parser(
        "run",
        help="Run full agentic workflow (LLM-powered)",
        description="Run the full autonomous compliance pipeline. "
                    "Loads project context, runs all checks, collects context, "
                    "and remediates failures (previewed unless --apply is given). "
                    "Requires an LLM API key.",
    )
    run_parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    run_parser.add_argument(
        "--feedback",
        dest="feedback_mode",
        choices=["interactive", "noninteractive", "auto"],
        default="auto",
        help="Human feedback mode: interactive (prompts in terminal), "
             "noninteractive (collects questions for later), "
             "auto (interactive if terminal, noninteractive in CI)",
    )
    run_parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the remediation changes (files and platform settings). "
             "Without it, remediation is only previewed and nothing is written.",
    )
    _add_operator_config_args(run_parser)
    _add_target_arg(run_parser)
    run_parser.set_defaults(func=cmd_run)

    # harness command (feature 026)
    harness_parser = subparsers.add_parser(
        "harness",
        help="Run end-to-end audit with in-band LLM dispatch (fleet-operator driver).",
        description=(
            "End-to-end audit driver with in-band LLM dispatch. Reads "
            "ANTHROPIC_API_KEY from env; dispatches LLM steps itself so "
            "no control ends up awaiting a model judgment in the report. Non-interactive; "
            "batch answers via --answers or auto-discovered .project/project.yaml."
        ),
    )
    harness_parser.add_argument(
        "repo_path",
        help="Path to the target repository",
    )
    harness_parser.add_argument(
        "--framework",
        help="Framework name (e.g., openssf-baseline). Overrides .baseline.toml.",
    )
    harness_parser.add_argument(
        "--level",
        type=int,
        choices=[1, 2, 3],
        default=3,
        help="Maximum maturity level to audit (default: 3)",
    )
    harness_parser.add_argument(
        "--answers",
        help=(
            "Path to YAML/JSON file with pre-declared context answers. "
            "Overrides values in .project/project.yaml for the run."
        ),
    )
    harness_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Report format (default: markdown)",
    )
    harness_parser.add_argument(
        "--output",
        help="Write report to this path; without it, stdout carries the report.",
    )
    harness_parser.add_argument(
        "--per-call-timeout",
        type=int,
        default=60,
        help="Per-LLM-call timeout in seconds (default: 60)",
    )
    harness_parser.add_argument(
        "--total-run-timeout",
        type=int,
        default=900,
        help="Total audit-run timeout in seconds (default: 900 = 15 min)",
    )
    harness_parser.add_argument(
        "--interactive",
        action="store_true",
        help=(
            "Prompt the operator at the terminal for any pending feedback "
            "question not covered by --answers or .project/project.yaml. "
            "Requires stdin to be a TTY and /dev/tty to be openable; fails "
            "fast with exit 2 otherwise."
        ),
    )
    harness_parser.add_argument(
        "--per-resolver-timeout",
        type=float,
        default=None,
        help=(
            "Per-resolver timeout in seconds. Default: no timeout. "
            "Setting a global bound is usually inappropriate (an operator at "
            "a terminal cannot be on the same clock as a webhook resolver)."
        ),
    )
    harness_parser.add_argument(
        "--allow-external-resolvers",
        action="store_true",
        help=(
            "Include third-party question resolvers registered under the "
            "`darnit.question_resolvers` entry-point group. Off by default: "
            "external resolvers produce authority='asserted' values, so "
            "silently including them would violate Constitution Principle IV "
            "(only human confirmation may assert)."
        ),
    )
    _add_operator_config_args(harness_parser)
    _add_target_arg(harness_parser)
    harness_parser.set_defaults(func=cmd_harness)

    # config command (feature 040)
    config_parser = subparsers.add_parser("config", help="Inspect or edit operator configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_show_parser = config_subparsers.add_parser(
        "show",
        help="Show the operator configuration source, digest, permission check, and settings",
    )
    _add_operator_config_args(config_show_parser)
    config_show_parser.set_defaults(func=cmd_config_show)
    config_trust_parser = config_subparsers.add_parser(
        "trust",
        help="Edit the repositories listed in [trust].repos of the operator configuration",
    )
    trust_subparsers = config_trust_parser.add_subparsers(dest="trust_command", required=True)
    for name, help_text in (
        ("add", "Add a repository identity (HOST/NAMESPACE/NAME or a clone URL)"),
        ("remove", "Remove a repository identity"),
        ("list", "List trusted repository identities"),
    ):
        trust_parser = trust_subparsers.add_parser(name, help=help_text)
        if name != "list":
            trust_parser.add_argument("identity", metavar="IDENTITY")
        trust_parser.add_argument(
            "--operator-config",
            metavar="PATH",
            help="Operator configuration file to edit (default: the per-user darnit config.toml)",
        )
        trust_parser.set_defaults(func=cmd_config_trust)
    config_migrate_parser = config_subparsers.add_parser(
        "migrate",
        help="Move .baseline.toml claims to .project/darnit.yaml and print a proposed operator configuration",
    )
    config_migrate_parser.add_argument("repo_path", nargs="?", default=".", metavar="REPO", help="Repository path")
    config_migrate_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace claims .project/darnit.yaml already makes for the same controls",
    )
    config_migrate_parser.set_defaults(func=cmd_config_migrate)

    # install command
    install_parser = subparsers.add_parser(
        "install",
        help="Configure MCP server in Claude Code or Cursor",
    )
    install_parser.add_argument(
        "--client",
        choices=["claude-code", "claude-desktop", "claude", "cursor"],
        default="claude-code",
        help="Client to configure (default: claude-code). 'claude' is deprecated — use claude-code or claude-desktop." ,
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing darnit entry without prompting",
    )
    install_parser.add_argument(
        "--mcp-only",
        action="store_true",
        help="Only install MCP server config, skip skills",
    )
    install_parser.add_argument(
        "--project",
        action="store_true",
        help="Install skills into .claude/skills/ and MCP config into .mcp.json (per-project) instead of "
             "user-scope paths. Not recommended: the repository then controls how darnit is launched.",
    )
    install_parser.set_defaults(func=cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args(argv)

    # Configure logging
    if args.verbose:
        configure_logging(level="DEBUG")
    elif args.quiet:
        configure_logging(level="WARNING")
    else:
        configure_logging(level="INFO")

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
