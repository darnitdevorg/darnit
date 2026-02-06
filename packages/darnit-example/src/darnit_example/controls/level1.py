"""Python-defined controls for the Project Hygiene Standard.

This module defines 2 controls that need Python logic beyond what TOML can express:
- PH-DOC-03: ReadmeHasDescription (custom analyzer for content quality)
- PH-CI-01: CIConfigExists (glob pattern matching for CI configs)
"""

import glob as glob_module
import os
import re
from collections.abc import Callable

from darnit.sieve.models import (
    CheckContext,
    ControlSpec,
    PassOutcome,
    PassResult,
    VerificationPhase,
)
from darnit.sieve.passes import DeterministicPass, ManualPass, PatternPass
from darnit.sieve.registry import register_control

# =============================================================================
# PH-DOC-03: ReadmeHasDescription
# =============================================================================


def _create_readme_description_check() -> Callable[[CheckContext], PassResult]:
    """Create a check that verifies the README has substantive content.

    Returns PASS if the README has at least one paragraph of text (>20 chars)
    beyond just the title line.
    """

    def check(ctx: CheckContext) -> PassResult:
        readme_names = ["README.md", "README", "README.rst", "README.txt"]
        for name in readme_names:
            filepath = os.path.join(ctx.local_path, name)
            if os.path.exists(filepath):
                try:
                    with open(filepath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue

                # Strip the title line (first heading) and check remaining content
                lines = content.strip().splitlines()
                non_title_lines = []
                for line in lines:
                    stripped = line.strip()
                    # Skip headings, blank lines, and decorators
                    if stripped.startswith("#") or stripped == "" or re.match(r"^[=\-]+$", stripped):
                        continue
                    non_title_lines.append(stripped)

                body_text = " ".join(non_title_lines)
                if len(body_text) > 20:
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.PASS,
                        message=f"README ({name}) contains a description ({len(body_text)} chars)",
                        evidence={"file": name, "body_length": len(body_text)},
                    )
                else:
                    return PassResult(
                        phase=VerificationPhase.DETERMINISTIC,
                        outcome=PassOutcome.FAIL,
                        message=f"README ({name}) exists but has no substantive description",
                        evidence={"file": name, "body_length": len(body_text)},
                    )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="No README file found",
        )

    return check


def _create_readme_quality_analyzer() -> Callable[[CheckContext], PassResult]:
    """Create a pattern-phase analyzer that checks README quality heuristics.

    Checks for common sections like Installation, Usage, etc.
    """

    def analyze(ctx: CheckContext) -> PassResult:
        readme_path = os.path.join(ctx.local_path, "README.md")
        if not os.path.exists(readme_path):
            return PassResult(
                phase=VerificationPhase.PATTERN,
                outcome=PassOutcome.INCONCLUSIVE,
                message="No README.md to analyze",
            )

        try:
            with open(readme_path, encoding="utf-8", errors="ignore") as f:
                content = f.read().lower()
        except OSError:
            return PassResult(
                phase=VerificationPhase.PATTERN,
                outcome=PassOutcome.INCONCLUSIVE,
                message="Could not read README.md",
            )

        # Check for common helpful sections
        sections_found = []
        for section in ["install", "usage", "getting started", "contributing", "license"]:
            if section in content:
                sections_found.append(section)

        if len(sections_found) >= 2:
            return PassResult(
                phase=VerificationPhase.PATTERN,
                outcome=PassOutcome.PASS,
                message=f"README has good structure with sections: {', '.join(sections_found)}",
                evidence={"sections_found": sections_found},
            )

        return PassResult(
            phase=VerificationPhase.PATTERN,
            outcome=PassOutcome.INCONCLUSIVE,
            message=f"README has limited structure (found: {sections_found})",
            evidence={"sections_found": sections_found},
        )

    return analyze


register_control(
    ControlSpec(
        control_id="PH-DOC-03",
        level=1,
        domain="DOC",
        name="ReadmeHasDescription",
        description="README contains a project description",
        passes=[
            DeterministicPass(config_check=_create_readme_description_check()),
            PatternPass(custom_analyzer=_create_readme_quality_analyzer()),
            ManualPass(
                verification_steps=[
                    "Open the README file",
                    "Verify it contains a meaningful project description",
                    "Check that it explains what the project does and how to use it",
                ]
            ),
        ],
    )
)


# =============================================================================
# PH-CI-01: CIConfigExists
# =============================================================================


def _create_ci_config_check() -> Callable[[CheckContext], PassResult]:
    """Create a check that looks for CI/CD configuration files.

    Searches for common CI providers: GitHub Actions, GitLab CI, CircleCI,
    Travis CI, Jenkins, Azure Pipelines.
    """

    def check(ctx: CheckContext) -> PassResult:
        ci_patterns = [
            ".github/workflows/*.yml",
            ".github/workflows/*.yaml",
            ".gitlab-ci.yml",
            ".circleci/config.yml",
            ".travis.yml",
            "Jenkinsfile",
            "azure-pipelines.yml",
            ".buildkite/pipeline.yml",
        ]

        for pattern in ci_patterns:
            full_pattern = os.path.join(ctx.local_path, pattern)
            matches = glob_module.glob(full_pattern)
            if matches:
                rel_paths = [os.path.relpath(m, ctx.local_path) for m in matches]
                return PassResult(
                    phase=VerificationPhase.DETERMINISTIC,
                    outcome=PassOutcome.PASS,
                    message=f"CI configuration found: {rel_paths[0]}",
                    evidence={"ci_files": rel_paths, "pattern": pattern},
                )

        return PassResult(
            phase=VerificationPhase.DETERMINISTIC,
            outcome=PassOutcome.FAIL,
            message="No CI/CD configuration found",
            evidence={"searched_patterns": ci_patterns},
        )

    return check


register_control(
    ControlSpec(
        control_id="PH-CI-01",
        level=2,
        domain="CI",
        name="CIConfigExists",
        description="Project has CI/CD configuration",
        passes=[
            DeterministicPass(config_check=_create_ci_config_check()),
            ManualPass(
                verification_steps=[
                    "Check for CI/CD configuration (GitHub Actions, GitLab CI, etc.)",
                    "Verify the CI pipeline runs tests on pull requests",
                ]
            ),
        ],
    )
)
