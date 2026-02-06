"""Remediation registry for the Project Hygiene Standard.

Maps controls to their automated fix functions.
"""

from typing import Any

REMEDIATION_REGISTRY: dict[str, dict[str, Any]] = {
    "create_readme": {
        "description": "Create a README.md file",
        "controls": ["PH-DOC-01", "PH-DOC-03"],
        "function": "create_readme",
        "safe": True,
        "requires_api": False,
    },
    "create_gitignore": {
        "description": "Create a .gitignore file",
        "controls": ["PH-CFG-01"],
        "function": "create_gitignore",
        "safe": True,
        "requires_api": False,
    },
}
