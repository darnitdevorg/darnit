#!/usr/bin/env python3
"""Sync validation for darnit framework.

This script validates that:
1. TOML configs validate against the framework schema
2. Framework code matches the specification
3. Generated docs are up to date

Exit Codes:
    0 = All validations pass
    1 = Critical validation failure (blocks merge)
    2 = Warning (does not block)

Usage:
    python scripts/validate_sync.py [--changed-files]

    --changed-files    Only validate files that have changed (for pre-commit)
    --fix              Attempt to fix issues where possible
    --verbose          Show detailed output
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SPEC_PATH = PROJECT_ROOT / "openspec" / "specs" / "framework-design" / "spec.md"
TOML_PATH = PROJECT_ROOT / "packages" / "darnit-baseline" / "openssf-baseline.toml"
FRAMEWORK_SCHEMA_PATH = (
    PROJECT_ROOT / "packages" / "darnit" / "src" / "darnit" / "config" / "framework_schema.py"
)
GENERATED_DOCS_DIR = PROJECT_ROOT / "docs" / "generated"


class ValidationResult(NamedTuple):
    """Result of a validation check."""

    passed: bool
    message: str
    details: str = ""
    is_warning: bool = False


def validate_toml_schema() -> ValidationResult:
    """Validate that the TOML config can be loaded by the framework schema.

    Returns:
        ValidationResult with pass/fail status
    """
    try:
        # Try to load the TOML using the framework's own loader
        import tomllib

        from darnit.config.framework_schema import FrameworkConfig

        with open(TOML_PATH, "rb") as f:
            toml_data = tomllib.load(f)

        # Attempt to parse with Pydantic model
        config = FrameworkConfig(**toml_data)

        # Basic validation checks
        errors = []

        if not config.metadata.name:
            errors.append("metadata.name is required")

        if not config.metadata.display_name:
            errors.append("metadata.display_name is required")

        if not config.controls:
            errors.append("No controls defined")

        # Check each control has required fields
        for control_id, control in config.controls.items():
            if not control.name:
                errors.append(f"{control_id}: missing name")
            if not control.description:
                errors.append(f"{control_id}: missing description")

        if errors:
            return ValidationResult(
                passed=False,
                message="TOML schema validation failed",
                details="\n".join(f"  - {e}" for e in errors),
            )

        return ValidationResult(
            passed=True,
            message=f"TOML schema valid ({len(config.controls)} controls)",
        )

    except ImportError as e:
        return ValidationResult(
            passed=False,
            message="Could not import framework schema",
            details=str(e),
        )
    except Exception as e:
        return ValidationResult(
            passed=False,
            message="TOML parsing failed",
            details=str(e),
        )


def validate_spec_exists() -> ValidationResult:
    """Validate that the framework spec exists.

    Returns:
        ValidationResult with pass/fail status
    """
    if not SPEC_PATH.exists():
        return ValidationResult(
            passed=False,
            message="Framework spec not found",
            details=f"Expected at: {SPEC_PATH}",
        )

    # Check spec has required sections
    content = SPEC_PATH.read_text()

    required_sections = [
        "TOML Schema",
        "Built-in Pass Types",
        "Sieve Orchestrator",
    ]

    missing = []
    for section in required_sections:
        if section not in content:
            missing.append(section)

    if missing:
        return ValidationResult(
            passed=False,
            message="Spec missing required sections",
            details="\n".join(f"  - {s}" for s in missing),
        )

    return ValidationResult(
        passed=True,
        message="Framework spec exists and has required sections",
    )


def validate_pass_types_sync() -> ValidationResult:
    """Validate that pass types in code match spec.

    Returns:
        ValidationResult with pass/fail status
    """
    # Read spec to get documented pass types
    if not SPEC_PATH.exists():
        return ValidationResult(
            passed=False,
            message="Cannot validate pass types: spec not found",
        )

    spec_content = SPEC_PATH.read_text()

    # Expected pass types from spec
    spec_pass_types = set()
    for pass_type in ["DeterministicPass", "ExecPass", "PatternPass", "LLMPass", "ManualPass"]:
        if pass_type in spec_content:
            spec_pass_types.add(pass_type)

    # Check that code has these pass types
    passes_file = PROJECT_ROOT / "packages" / "darnit" / "src" / "darnit" / "sieve" / "passes.py"
    if not passes_file.exists():
        return ValidationResult(
            passed=False,
            message="passes.py not found",
            details=str(passes_file),
        )

    code_content = passes_file.read_text()

    missing_in_code = []
    for pass_type in spec_pass_types:
        if f"class {pass_type}" not in code_content:
            missing_in_code.append(pass_type)

    if missing_in_code:
        return ValidationResult(
            passed=False,
            message="Pass types in spec not found in code",
            details="\n".join(f"  - {t}" for t in missing_in_code),
        )

    return ValidationResult(
        passed=True,
        message=f"Pass types in sync ({len(spec_pass_types)} types)",
    )


def validate_docs_freshness() -> ValidationResult:
    """Validate that generated docs are up to date.

    Returns:
        ValidationResult (warning level, not blocking)
    """
    if not GENERATED_DOCS_DIR.exists():
        return ValidationResult(
            passed=False,
            message="Generated docs directory not found",
            details=f"Run: python scripts/generate_docs.py",
            is_warning=True,
        )

    expected_files = ["ARCHITECTURE.md", "SCHEMA_REFERENCE.md", "USAGE_GUIDE.md"]
    missing = []

    for filename in expected_files:
        if not (GENERATED_DOCS_DIR / filename).exists():
            missing.append(filename)

    if missing:
        return ValidationResult(
            passed=False,
            message="Generated docs incomplete",
            details="\n".join(f"  - Missing: {f}" for f in missing),
            is_warning=True,
        )

    # Check if spec is newer than generated docs
    if SPEC_PATH.exists():
        spec_mtime = SPEC_PATH.stat().st_mtime
        for filename in expected_files:
            doc_path = GENERATED_DOCS_DIR / filename
            if doc_path.stat().st_mtime < spec_mtime:
                return ValidationResult(
                    passed=False,
                    message="Generated docs may be stale",
                    details=f"Spec modified after {filename}. Run: python scripts/generate_docs.py",
                    is_warning=True,
                )

    return ValidationResult(
        passed=True,
        message="Generated docs are present",
    )


def validate_sarif_reads_from_toml() -> ValidationResult:
    """Validate that SARIF formatter reads from TOML, not catalog.

    Returns:
        ValidationResult with pass/fail status
    """
    sarif_path = (
        PROJECT_ROOT
        / "packages"
        / "darnit-baseline"
        / "src"
        / "darnit_baseline"
        / "formatters"
        / "sarif.py"
    )

    if not sarif_path.exists():
        return ValidationResult(
            passed=False,
            message="SARIF formatter not found",
            details=str(sarif_path),
        )

    content = sarif_path.read_text()

    # Check for TOML loading
    if "_load_framework_config" not in content:
        return ValidationResult(
            passed=False,
            message="SARIF formatter should load from framework config",
            details="Expected _load_framework_config function",
        )

    # Check deprecation notice for catalog
    if "deprecated" not in content.lower():
        return ValidationResult(
            passed=False,
            message="SARIF formatter should document catalog deprecation",
            is_warning=True,
        )

    return ValidationResult(
        passed=True,
        message="SARIF formatter reads from TOML (catalog deprecated)",
    )


def run_validations(verbose: bool = False) -> int:
    """Run all validation checks.

    Args:
        verbose: Show detailed output

    Returns:
        Exit code (0=pass, 1=fail, 2=warning)
    """
    validations = [
        ("TOML Schema", validate_toml_schema),
        ("Spec Exists", validate_spec_exists),
        ("Pass Types Sync", validate_pass_types_sync),
        ("SARIF Source", validate_sarif_reads_from_toml),
        ("Docs Freshness", validate_docs_freshness),
    ]

    results = []
    print("Running sync validations...\n")

    for name, validator in validations:
        result = validator()
        results.append((name, result))

        # Print result
        if result.passed:
            status = "✓"
            color = "\033[32m"  # Green
        elif result.is_warning:
            status = "⚠"
            color = "\033[33m"  # Yellow
        else:
            status = "✗"
            color = "\033[31m"  # Red

        reset = "\033[0m"
        print(f"{color}{status}{reset} {name}: {result.message}")

        if verbose and result.details:
            print(f"  {result.details}")

    print()

    # Determine exit code
    has_failure = any(not r.passed and not r.is_warning for _, r in results)
    has_warning = any(not r.passed and r.is_warning for _, r in results)

    if has_failure:
        print("FAILED: Critical validation errors found")
        return 1
    elif has_warning:
        print("WARNING: Non-critical issues found")
        return 2
    else:
        print("PASSED: All validations successful")
        return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate spec-implementation sync")
    parser.add_argument(
        "--changed-files",
        action="store_true",
        help="Only validate changed files (for pre-commit)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed output"
    )
    args = parser.parse_args()

    exit_code = run_validations(verbose=args.verbose)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
