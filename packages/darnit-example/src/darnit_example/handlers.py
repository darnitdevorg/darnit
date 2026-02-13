"""Custom sieve handlers for the Project Hygiene Standard.

These handlers implement verification logic that requires Python beyond what
built-in TOML handlers can express:
- readme_description: Checks README has substantive content beyond the title
- readme_quality: Heuristic check for common README sections
- ci_config: Glob-based search for CI/CD configuration files
"""

import glob as glob_module
import os
import re

from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)


def readme_description_handler(
    config: dict, context: HandlerContext
) -> HandlerResult:
    """Check that the README has substantive content beyond the title.

    Returns PASS if the README has at least one paragraph of text (>20 chars)
    beyond just the title line.
    """
    readme_names = config.get("readme_names", ["README.md", "README", "README.rst", "README.txt"])

    for name in readme_names:
        filepath = os.path.join(context.local_path, name)
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
                if stripped.startswith("#") or stripped == "" or re.match(r"^[=\-]+$", stripped):
                    continue
                non_title_lines.append(stripped)

            body_text = " ".join(non_title_lines)
            if len(body_text) > 20:
                return HandlerResult(
                    status=HandlerResultStatus.PASS,
                    message=f"README ({name}) contains a description ({len(body_text)} chars)",
                    evidence={"file": name, "body_length": len(body_text)},
                )
            else:
                return HandlerResult(
                    status=HandlerResultStatus.FAIL,
                    message=f"README ({name}) exists but has no substantive description",
                    evidence={"file": name, "body_length": len(body_text)},
                )

    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message="No README file found",
    )


def readme_quality_handler(
    config: dict, context: HandlerContext
) -> HandlerResult:
    """Check README quality heuristics — looks for common sections.

    Checks for common sections like Installation, Usage, etc.
    Returns PASS if at least 2 sections are found.
    """
    readme_path = os.path.join(context.local_path, "README.md")
    if not os.path.exists(readme_path):
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="No README.md to analyze",
        )

    try:
        with open(readme_path, encoding="utf-8", errors="ignore") as f:
            content = f.read().lower()
    except OSError:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message="Could not read README.md",
        )

    sections = config.get("sections", ["install", "usage", "getting started", "contributing", "license"])
    sections_found = [s for s in sections if s in content]

    min_sections = config.get("min_sections", 2)
    if len(sections_found) >= min_sections:
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"README has good structure with sections: {', '.join(sections_found)}",
            evidence={"sections_found": sections_found},
        )

    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message=f"README has limited structure (found: {sections_found})",
        evidence={"sections_found": sections_found},
    )


def ci_config_handler(
    config: dict, context: HandlerContext
) -> HandlerResult:
    """Check for CI/CD configuration files using glob patterns.

    Searches for common CI providers: GitHub Actions, GitLab CI, CircleCI,
    Travis CI, Jenkins, Azure Pipelines, Buildkite.
    """
    ci_patterns = config.get("patterns", [
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
        ".gitlab-ci.yml",
        ".circleci/config.yml",
        ".travis.yml",
        "Jenkinsfile",
        "azure-pipelines.yml",
        ".buildkite/pipeline.yml",
    ])

    for pattern in ci_patterns:
        full_pattern = os.path.join(context.local_path, pattern)
        matches = glob_module.glob(full_pattern)
        if matches:
            rel_paths = [os.path.relpath(m, context.local_path) for m in matches]
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message=f"CI configuration found: {rel_paths[0]}",
                evidence={"ci_files": rel_paths, "pattern": pattern},
            )

    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message="No CI/CD configuration found",
        evidence={"searched_patterns": ci_patterns},
    )
