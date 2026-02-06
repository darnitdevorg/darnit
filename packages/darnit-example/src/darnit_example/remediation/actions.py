"""Remediation action implementations for the Project Hygiene Standard.

Each function creates a missing file to satisfy a control.
"""

import os
from pathlib import Path


def create_readme(local_path: str, dry_run: bool = True, **kwargs: object) -> dict:
    """Create a README.md file in the project root.

    Args:
        local_path: Path to the repository root.
        dry_run: If True, report what would be done without writing.

    Returns:
        Dict with remediation result.
    """
    target = Path(local_path) / "README.md"
    if target.exists():
        return {
            "status": "skipped",
            "message": "README.md already exists",
            "path": str(target),
        }

    repo_name = os.path.basename(os.path.abspath(local_path))
    content = f"# {repo_name}\n\nA brief description of what this project does.\n"

    if dry_run:
        return {
            "status": "dry_run",
            "message": f"Would create {target}",
            "path": str(target),
        }

    target.write_text(content, encoding="utf-8")
    return {
        "status": "created",
        "message": f"Created {target}",
        "path": str(target),
    }


def create_gitignore(local_path: str, dry_run: bool = True, **kwargs: object) -> dict:
    """Create a .gitignore file in the project root.

    Args:
        local_path: Path to the repository root.
        dry_run: If True, report what would be done without writing.

    Returns:
        Dict with remediation result.
    """
    target = Path(local_path) / ".gitignore"
    if target.exists():
        return {
            "status": "skipped",
            "message": ".gitignore already exists",
            "path": str(target),
        }

    content = """\
# OS files
.DS_Store
Thumbs.db

# Editor files
*.swp
*.swo
*~
.idea/
.vscode/

# Build artifacts
build/
dist/
*.egg-info/

# Virtual environments
.venv/
venv/

# Byte-compiled files
__pycache__/
*.py[cod]
"""

    if dry_run:
        return {
            "status": "dry_run",
            "message": f"Would create {target}",
            "path": str(target),
        }

    target.write_text(content, encoding="utf-8")
    return {
        "status": "created",
        "message": f"Created {target}",
        "path": str(target),
    }
