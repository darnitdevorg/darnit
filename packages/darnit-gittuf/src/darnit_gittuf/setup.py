# SPDX-License-Identifier: Apache-2.0
"""Minimal new-installation helper used by GT-01.01's exec remediation."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from darnit.config.context_resolve import resolve_context
from darnit.config.context_storage import framework_definitions
from darnit.config.merger import load_framework_by_name
from darnit.trust.decision import target_from_owner_repo

ROOT_KEY = "gittuf_root_key"
POLICY = "refs/gittuf/policy"
RSL = "refs/gittuf/reference-state-log"


class SetupError(RuntimeError):
    """A prerequisite or initialization command failed."""


def run(repo: str, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=repo, env=env, input="", capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SetupError(f"{args[0]} {args[1]} failed: {result.stderr.strip()[:1000] or result.returncode}")
    return result.stdout.strip()


def references(repo: str) -> dict[str, str]:
    return dict(
        line.split(" ", 1)
        for line in run(repo, "git", "for-each-ref", "--format=%(refname) %(objectname)", "refs/gittuf/").splitlines()
    )


def initialize(repo: str, owner: str | None = None, name: str | None = None) -> None:
    for tool in ("git", "gittuf", "ssh-keygen"):
        if not shutil.which(tool):
            raise SetupError(f"{tool} is not installed or not on PATH")
    if references(repo):
        raise SetupError("refs/gittuf/* already exist; existing metadata has been preserved")
    definitions = framework_definitions(load_framework_by_name("gittuf"))
    context = resolve_context(
        repo, definitions, target=target_from_owner_repo(owner, name), owner=owner, repo=name, detect=False
    ).usable()
    if not context.get(ROOT_KEY):
        raise SetupError("Ask the maintainer for gittuf_root_key and record it with confirm_project_data first")
    key = Path(context[ROOT_KEY]).expanduser()
    if not key.is_absolute() or not key.is_file() or key.suffix == ".pub":
        raise SetupError("gittuf_root_key must be an absolute path to an existing SSH signing key, not a .pub file")
    run(repo, "ssh-keygen", "-l", "-f", str(key))
    run(repo, "git", "var", "GIT_AUTHOR_IDENT")
    run(repo, "git", "var", "GIT_COMMITTER_IDENT")

    # Use the chosen identity for metadata signing without editing Git config.
    env = os.environ.copy()
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    for offset, (name, value) in enumerate((("gpg.format", "ssh"), ("user.signingkey", str(key)))):
        env[f"GIT_CONFIG_KEY_{count + offset}"] = name
        env[f"GIT_CONFIG_VALUE_{count + offset}"] = value
    env["GIT_CONFIG_COUNT"] = str(count + 2)
    for command in (
        ("trust", "init", "-k", str(key)),
        ("trust", "stage", "--local-only"),
        ("trust", "apply", "--local-only"),
    ):
        run(repo, "gittuf", *command, env=env)
    if not {POLICY, RSL} <= references(repo).keys():
        raise SetupError("Initialization did not create the applied root and reference state log")


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize gittuf using the maintainer's confirmed SSH key")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--owner", default="")
    parser.add_argument("--name", default="")
    args = parser.parse_args()
    try:
        initialize(args.repo, args.owner or None, args.name or None)
    except (SetupError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Initialization stopped: {exc}. Inspect any existing metadata before retrying.", file=sys.stderr)
        return 1
    print("Initial gittuf root applied locally. Branch policy remains a maintainer decision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
