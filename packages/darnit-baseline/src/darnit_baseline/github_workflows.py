"""The ``github_workflows_present`` sieve handler (#584).

The first step of the controls that audit GitHub Actions workflow files
(``OSPS-BR-01.01``, ``OSPS-BR-01.02``, ``OSPS-AC-04.02``). Without workflow
files their commands have nothing to read: zizmor exits 3 and ``grep``
exits 2, which an ``exec`` step reports as ``unexpected_exit``. This step
says what happened instead, before either runs.

* WARN when ``.github/workflows/`` holds no ``.yml`` or ``.yaml`` file inside
  the repository. The step type's ceiling is ``{fail}``, so the WARN
  concludes the control with this message and no error class, and no later
  step runs.
* With ``actions = true``, an action definition (``action.yml`` or
  ``action.yaml``) anywhere in the repository outside ``.git`` also counts as
  something to audit, for a control whose zizmor audit reads actions as well
  as workflows (``template-injection``). zizmor collects action definitions
  from the whole tree, so without the setting this step would end such a
  control before zizmor could report a finding in one.
* INCONCLUSIVE otherwise: the files are evidence and evaluation continues
  with the control's other steps.

It never returns PASS or FAIL.
"""

from __future__ import annotations

import os
from typing import Any

from darnit.core.repo_files import escaping_entry, within_repository
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus

WORKFLOWS_DIR = ".github/workflows"
WORKFLOW_SUFFIXES = (".yml", ".yaml")
ACTION_FILE_NAMES = ("action.yml", "action.yaml")
_EVIDENCE_LIMIT = 20

NO_WORKFLOWS_MESSAGE = (
    "No GitHub Actions workflow files (.github/workflows/*.yml or *.yaml) were found, "
    "so there is nothing to audit. If this project does not use GitHub Actions, "
    "confirm ci_provider to mark this control not applicable."
)
NO_WORKFLOWS_OR_ACTIONS_MESSAGE = (
    "No GitHub Actions workflow files (.github/workflows/*.yml or *.yaml) or action "
    "definitions (action.yml or action.yaml) were found, so there is nothing to audit. "
    "If this project does not use GitHub Actions, confirm ci_provider to mark this "
    "control not applicable."
)


def _first_action_file(root: str, skipped: list[str]) -> str | None:
    """The first action definition inside the repository, as a repository-relative path."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            if name.lower() not in ACTION_FILE_NAMES:
                continue
            path = os.path.join(dirpath, name)
            if not within_repository(root, path):
                entry = escaping_entry(root, path)
                if entry not in skipped:
                    skipped.append(entry)
                continue
            if os.path.isfile(path):
                return os.path.relpath(path, root).replace(os.sep, "/")
    return None


def github_workflows_present_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """WARN when the repository has nothing for the control to audit, else INCONCLUSIVE."""
    directory = os.path.join(context.local_path, *WORKFLOWS_DIR.split("/"))
    try:
        names = sorted(entry.name for entry in os.scandir(directory))
    except (FileNotFoundError, NotADirectoryError):
        names = []
    except OSError as e:
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"Could not list {WORKFLOWS_DIR}/: {e}",
            evidence={"workflows_dir": WORKFLOWS_DIR},
        )

    found: list[str] = []
    skipped: list[str] = []
    for name in names:
        if not name.lower().endswith(WORKFLOW_SUFFIXES):
            continue
        path = os.path.join(directory, name)
        if not within_repository(context.local_path, path):
            entry = escaping_entry(context.local_path, path)
            if entry not in skipped:
                skipped.append(entry)
            continue
        if os.path.isfile(path):
            found.append(f"{WORKFLOWS_DIR}/{name}")

    evidence: dict[str, Any] = {"workflows_dir": WORKFLOWS_DIR, "workflow_files": found[:_EVIDENCE_LIMIT]}
    if found:
        if skipped:
            evidence["skipped_outside_repository"] = skipped
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"GitHub Actions workflow files found: {len(found)}",
            evidence=evidence,
        )

    include_actions = config.get("actions") is True
    action_file = _first_action_file(context.local_path, skipped) if include_actions else None
    if skipped:
        evidence["skipped_outside_repository"] = skipped
    if action_file is not None:
        evidence["action_files"] = [action_file]
        return HandlerResult(
            status=HandlerResultStatus.INCONCLUSIVE,
            message=f"No GitHub Actions workflow files; action definition found: {action_file}",
            evidence=evidence,
        )
    return HandlerResult(
        status=HandlerResultStatus.WARN,
        message=NO_WORKFLOWS_OR_ACTIONS_MESSAGE if include_actions else NO_WORKFLOWS_MESSAGE,
        confidence=1.0,
        evidence=evidence,
    )


__all__ = ["NO_WORKFLOWS_MESSAGE", "NO_WORKFLOWS_OR_ACTIONS_MESSAGE", "github_workflows_present_handler"]
