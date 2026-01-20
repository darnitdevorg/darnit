"""Darnit CLI - Declarative compliance auditing.

A Terraform-like CLI for running compliance audits against repositories.

Usage:
    darnit audit [OPTIONS] [REPO_PATH]
    darnit plan [OPTIONS] [REPO_PATH]
    darnit validate [OPTIONS] FRAMEWORK_PATH
    darnit init [OPTIONS] [REPO_PATH]
    darnit list [OPTIONS]
    darnit serve [OPTIONS]

Examples:
    # Audit a repository against OpenSSF Baseline
    darnit audit /path/to/repo

    # Audit with a custom framework
    darnit audit --framework ./my-framework.toml /path/to/repo

    # Show what would be checked (dry-run)
    darnit plan /path/to/repo

    # Validate a framework definition
    darnit validate ./my-framework.toml

    # Initialize a .baseline.toml file
    darnit init /path/to/repo

    # List available frameworks
    darnit list

    # Start the MCP server
    darnit serve
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from darnit.core.logging import get_logger, configure_logging

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


def format_results_text(results: List[dict], framework_name: str) -> str:
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


def format_results_json(results: List[dict], framework_name: str) -> str:
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
    """Run compliance audit against a repository."""
    from darnit.config import (
        load_effective_config,
        load_effective_config_by_name,
        load_effective_config_auto,
        load_controls_from_effective,
    )
    from darnit.sieve import SieveOrchestrator, CheckContext

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

    # Filter by level if specified
    if args.level:
        controls = [c for c in controls if c.level <= args.level]

    logger.info(f"Auditing {repo_path} with {len(controls)} controls")

    # Create orchestrator and run checks
    orchestrator = SieveOrchestrator()

    # Detect owner/repo from git if available
    owner, repo = _detect_owner_repo(repo_path)
    default_branch = _detect_default_branch(repo_path)

    results = []
    for control in controls:
        context = CheckContext(
            owner=owner,
            repo=repo,
            local_path=str(repo_path),
            default_branch=default_branch,
            control_id=control.control_id,
            control_metadata={
                "name": control.name,
                "description": control.description,
            },
        )

        result = orchestrator.verify(control, context)
        results.append(result.to_legacy_dict())

    # Output results
    if args.output == "json":
        print(format_results_json(results, config.framework_name))
    else:
        print(format_results_text(results, config.framework_name))

    # Return non-zero if any failures
    failures = [r for r in results if r.get("status") == "FAIL"]
    return 1 if failures and not args.no_fail else 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Show what would be checked (dry-run)."""
    from darnit.config import (
        load_effective_config_auto,
        load_effective_config,
        load_effective_config_by_name,
    )

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

    print(f"\n=== Execution Plan: {config.framework_name} ===\n")
    print(f"Framework: {config.framework_name} v{config.framework_version}")
    if config.spec_version:
        print(f"Spec: {config.spec_version}")
    print(f"Repository: {repo_path}")
    print()

    # Group controls by level
    by_level = {}
    for cid, ctrl in config.controls.items():
        level = ctrl.level
        by_level.setdefault(level, []).append((cid, ctrl))

    for level in sorted(by_level.keys()):
        if args.level and level > args.level:
            continue

        controls = by_level[level]
        print(f"Level {level} ({len(controls)} controls):")
        for cid, ctrl in sorted(controls, key=lambda x: x[0]):
            if ctrl.is_applicable():
                adapter = ctrl.check_adapter
                print(f"  • {cid}: {ctrl.name} [adapter: {adapter}]")
            else:
                print(f"  - {cid}: {ctrl.name} [skipped: {ctrl.status_reason}]")
        print()

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
        for cid, ctrl in config.controls.items():
            by_level.setdefault(ctrl.level, 0)
            by_level[ctrl.level] += 1

        print(f"  By level: {', '.join(f'L{k}={v}' for k, v in sorted(by_level.items()))}")
        return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a .baseline.toml file."""
    repo_path = Path(args.repo_path).resolve()
    baseline_path = repo_path / ".baseline.toml"

    if baseline_path.exists() and not args.force:
        logger.error(f".baseline.toml already exists. Use --force to overwrite.")
        return 1

    framework = args.framework or "openssf-baseline"

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
# [controls."OSPS-BR-02.01"]
# status = "n/a"
# reason = "Pre-release project"

# Use custom adapter for specific controls
# [controls."OSPS-VM-05.02"]
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


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the MCP server."""
    # Import and run the MCP server
    try:
        from darnit.server import create_server
        server = create_server()
        server.run()
        return 0
    except ImportError:
        logger.error("MCP server dependencies not installed. Run: pip install mcp")
        return 1


# =============================================================================
# Helpers
# =============================================================================


def _detect_owner_repo(repo_path: Path) -> tuple:
    """Detect owner/repo from git remote."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Parse GitHub URL
            if "github.com" in url:
                # https://github.com/owner/repo.git or git@github.com:owner/repo.git
                parts = url.replace(".git", "").split("/")
                if len(parts) >= 2:
                    return parts[-2], parts[-1]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # Fallback
    return "unknown", repo_path.name


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

    # audit command
    audit_parser = subparsers.add_parser("audit", help="Run compliance audit")
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
        "-l", "--level",
        type=int,
        choices=[1, 2, 3],
        help="Maximum level to check (default: all)",
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

    # plan command
    plan_parser = subparsers.add_parser("plan", help="Show execution plan")
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
        "-l", "--level",
        type=int,
        choices=[1, 2, 3],
        help="Maximum level to show",
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
        help="Framework to extend (default: openssf-baseline)",
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

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start MCP server")
    serve_parser.set_defaults(func=cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
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
