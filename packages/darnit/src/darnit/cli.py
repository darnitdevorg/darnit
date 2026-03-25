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
    darnit init [OPTIONS] [REPO_PATH]   # Initialize .baseline.toml
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
import sys
from pathlib import Path

from darnit.core.logging import configure_logging, get_logger

logger = get_logger("cli")


# =============================================================================
# Output Formatters
# =============================================================================


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
        "NA": "-",
    }
    icon = status_icons.get(status, "?")

    return f"  {icon} {control_id}: {status} - {details}"


def format_results_text(results: list[dict], framework_name: str) -> str:
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
    na = len(by_status.get("NA", []))

    lines.append(f"Total: {total} | Pass: {passed} | Fail: {failed} | Warn: {warned} | N/A: {na}\n")

    # Show failures first
    if "FAIL" in by_status:
        lines.append("\n--- Failures ---")
        for r in by_status["FAIL"]:
            lines.append(format_result_text(r))

    # Show warnings
    if "WARN" in by_status:
        lines.append("\n--- Warnings ---")
        for r in by_status["WARN"]:
            lines.append(format_result_text(r))

    # Show passes (optional, can be verbose)
    if "PASS" in by_status:
        lines.append(f"\n--- Passed ({len(by_status['PASS'])}) ---")
        for r in by_status["PASS"][:10]:  # Limit to 10
            lines.append(format_result_text(r))
        if len(by_status["PASS"]) > 10:
            lines.append(f"  ... and {len(by_status['PASS']) - 10} more")

    return "\n".join(lines)


def format_results_json(results: list[dict], framework_name: str) -> str:
    """Format results as JSON."""
    output = {
        "framework": framework_name,
        "results": results,
        "summary": {
            "total": len(results),
            "pass": len([r for r in results if r.get("status") == "PASS"]),
            "fail": len([r for r in results if r.get("status") == "FAIL"]),
            "warn": len([r for r in results if r.get("status") == "WARN"]),
            "na": len([r for r in results if r.get("status") == "NA"]),
        },
    }
    return json.dumps(output, indent=2)


# =============================================================================
# Commands
# =============================================================================


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

    # Load configuration
    try:
        if args.framework:
            framework_path = Path(args.framework)
            if framework_path.exists():
                config = load_effective_config(framework_path, repo_path)
            else:
                # Try as framework name
                config = load_effective_config_by_name(args.framework, repo_path)
        else:
            config = load_effective_config_auto(repo_path)
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

    owner, repo = detect_owner_repo(str(repo_path))
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
        apply_user_config=False,  # CLI already applied filters above
        stop_on_llm=True,
    )

    # Output results
    if args.output == "json":
        print(format_results_json(results, config.framework_name))
    else:
        print(format_results_text(results, config.framework_name))

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

    print(f"\n=== Execution Plan: {config.framework_name} ===\n")
    print(f"Framework: {config.framework_name} v{config.framework_version}")
    if config.spec_version:
        print(f"Spec: {config.spec_version}")
    print(f"Repository: {repo_path}")
    if filters:
        print(f"Filters: {', '.join(f'{f.field}{f.operator}{f.value}' for f in filters)}")
    if include_ids:
        print(f"Include: {', '.join(sorted(include_ids))}")
    if exclude_ids:
        print(f"Exclude: {', '.join(sorted(exclude_ids))}")
    print()

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

        print(f"Level {level} ({len(shown_controls)} controls):")
        for cid, ctrl in shown_controls:
            if ctrl.is_applicable():
                adapter = ctrl.check_adapter
                print(f"  • {cid}: {ctrl.name} [adapter: {adapter}]")
            else:
                print(f"  - {cid}: {ctrl.name} [skipped: {ctrl.status_reason}]")
        print()
        total_shown += len(shown_controls)

    if total_filtered > 0:
        print(f"({total_filtered} controls filtered out)")

    # Show excluded controls
    excluded = config.get_excluded_controls()
    if excluded:
        print(f"Excluded ({len(excluded)}):")
        for cid, reason in excluded.items():
            print(f"  - {cid}: {reason}")

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
        print(f"\n✗ Validation failed with {len(errors)} error(s):\n")
        for error in errors:
            print(f"  • {error}")
        return 1
    else:
        print(f"\n✓ Framework '{config.metadata.name}' is valid")
        print(f"  Controls: {len(config.controls)}")
        print(f"  Adapters: {len(config.adapters)}")

        # Show level breakdown
        by_level = {}
        for _cid, ctrl in config.controls.items():
            by_level.setdefault(ctrl.level, 0)
            by_level[ctrl.level] += 1

        print(f"  By level: {', '.join(f'L{k}={v}' for k, v in sorted(by_level.items()))}")
        return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a .baseline.toml file."""
    repo_path = Path(args.repo_path).resolve()
    baseline_path = repo_path / ".baseline.toml"

    if baseline_path.exists() and not args.force:
        logger.error(".baseline.toml already exists. Use --force to overwrite.")
        return 1

    # Auto-detect framework from installed implementations
    if args.framework:
        framework = args.framework
    else:
        from darnit.core.discovery import discover_implementations
        impls = discover_implementations()
        if len(impls) == 1:
            framework = next(iter(impls))
        else:
            framework = "openssf-baseline"

    template = f'''# Darnit configuration file
# See: https://github.com/kusari-oss/darnit

version = "1.0"
extends = "{framework}"

[settings]
cache_results = true
timeout = 300

# Adapter definitions (uncomment to use external tools)
# [adapters.kusari]
# type = "command"
# command = "kusari"
# output_format = "json"

# Control overrides
# [controls."CONTROL-ID"]
# status = "n/a"
# reason = "Pre-release project"

# Use custom adapter for specific controls
# [controls."CONTROL-ID"]
# check = {{ adapter = "kusari" }}
'''

    baseline_path.write_text(template)
    print(f"✓ Created {baseline_path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List available frameworks."""
    from darnit.config import list_available_frameworks, load_framework_by_name

    frameworks = list_available_frameworks()

    if not frameworks:
        print("No frameworks found. Install a framework package like darnit-baseline.")
        return 0

    print("\nAvailable Frameworks:\n")
    for name in frameworks:
        try:
            config = load_framework_by_name(name)
            print(f"  • {name}")
            print(f"    Display: {config.metadata.display_name}")
            print(f"    Version: {config.metadata.version}")
            if config.metadata.spec_version:
                print(f"    Spec: {config.metadata.spec_version}")
            print(f"    Controls: {len(config.controls)}")
            print()
        except Exception as e:
            print(f"  • {name} (error loading: {e})")

    return 0

def cmd_install(args: argparse.Namespace) -> int:
    """Install darnit MCP server config into a supported client settings file."""
    import shutil

    if args.client == "claude":
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = Path.home() / ".cursor" / "mcp.json"

    settings_path.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if settings_path.exists():
        try:
            config = json.loads(settings_path.read_text())
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in settings file: {settings_path}: {e}")
            return 1

        backup_path = settings_path.with_suffix(settings_path.suffix + ".bak")
        shutil.copy2(settings_path, backup_path)

    mcp_servers = config.setdefault("mcpServers", {})
    darnit_entry = {
        "command": "uvx",
        "args": ["--from", "darnit", "darnit", "serve"],
    }

    if "darnit" in mcp_servers and not args.force:
        response = input(
            f"'darnit' entry already exists in {settings_path}. Overwrite? [y/N]: "
        ).strip().lower()
        if response not in {"y", "yes"}:
            print("Install cancelled.")
            return 1

    mcp_servers["darnit"] = darnit_entry

    try:
        json.dumps(config)  # validate before write
        settings_path.write_text(json.dumps(config, indent=2) + "\n")
    except Exception as e:
        logger.error(f"Failed to write settings file: {e}")
        return 1

    print(f"✓ Installed darnit MCP server config in {settings_path}")
    print("Next step: restart your AI client and use the configured MCP server.")
    return 0

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

    if config_path:
        # New mode: Use TOML config file
        if not os.path.exists(config_path):
            logger.error(f"Config file not found: {config_path}")
            return 1

        try:
            server = create_server(config_path)
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
            server = create_server(str(framework_path))
            logger.info(f"Starting MCP server with framework: {framework_name}")
            server.run()
            return 0
        except Exception as e:
            logger.error(f"Failed to start server with framework '{framework_name}': {e}")
            return 1


# =============================================================================
# Helpers
# =============================================================================



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


# =============================================================================
# Main Entry Point
# =============================================================================


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
        version=f"%(prog)s {importlib.metadata.version('darnit')}",
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
    plan_parser.set_defaults(func=cmd_plan)

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate framework config")
    validate_parser.add_argument(
        "framework_path",
        help="Path to framework .toml file",
    )
    validate_parser.set_defaults(func=cmd_validate)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize .baseline.toml")
    init_parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to repository",
    )
    init_parser.add_argument(
        "-f", "--framework",
        help="Framework to extend (default: auto-detect)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing file",
    )
    init_parser.set_defaults(func=cmd_init)

    # list command
    list_parser = subparsers.add_parser("list", help="List available frameworks")
    list_parser.set_defaults(func=cmd_list)

    # install command
    install_parser = subparsers.add_parser(
        "install",
        help="Configure MCP server in Claude Code or Cursor",
    )
    install_parser.add_argument(
        "--client",
        choices=["claude", "cursor"],
        default="claude",
        help="Client to configure (default: claude)",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing darnit entry without prompting",
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
