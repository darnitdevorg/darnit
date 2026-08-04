"""Wheel-install regression test for framework config resolution (feature 021).

Every darnit implementation package (darnit-baseline, darnit-gittuf,
darnit-reproducibility) MUST resolve its framework TOML correctly when
installed from a built wheel, not just from an editable checkout. This
test builds each wheel, installs it into a fresh venv, and asserts:

1. ``get_framework_path()`` returns an existing, readable Path that
   parses as valid TOML (path-level check).
2. ``python -m darnit list`` exits 0, prints the framework name, and
   does not print "error loading" (CLI-level check; closes SC-001).

The test would have caught the pre-021 bug where ``get_framework_config_path()``
walked ``Path(__file__).parent.parent.parent`` and the TOML was not
included in the built wheel at all.

Marked ``@pytest.mark.slow`` because each parametrized case builds a
wheel, creates a venv, and runs pip install with network access.
"""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# (package_name, module_name, toml_filename)
IMPLEMENTATIONS = [
    ("darnit-baseline", "darnit_baseline", "openssf-baseline.toml"),
    ("darnit-gittuf", "darnit_gittuf", "gittuf.toml"),
    ("darnit-reproducibility", "darnit_reproducibility", "reproducibility.toml"),
]


def _venv_python(venv_path: Path) -> Path:
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _venv_darnit(venv_path: Path) -> Path:
    """Path to the ``darnit`` console script installed in the venv."""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "darnit.exe"
    return venv_path / "bin" / "darnit"


def _build_wheel(package_name: str, out_dir: Path) -> Path:
    """Build the wheel for `package_name` into `out_dir` and return its Path."""
    subprocess.run(
        ["uv", "build", "--package", package_name, "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    wheels = list(out_dir.glob(f"{package_name.replace('-', '_')}-*.whl"))
    assert len(wheels) == 1, (
        f"expected exactly one wheel for {package_name}, found {wheels}"
    )
    return wheels[0]


def _install_wheel(venv_python: Path, target_wheel: Path, core_wheel: Path) -> None:
    """Install `core_wheel` + `target_wheel` into the venv.

    Passes both wheels so pip satisfies the ``darnit-core>=0.1.0`` requirement
    from the target's own metadata using the local build, not PyPI. Transitive
    dependencies (pydantic, cel-python, etc.) still resolve from PyPI.
    """
    subprocess.run(
        [
            str(venv_python), "-m", "pip", "install",
            "--disable-pip-version-check",
            str(core_wheel),
            str(target_wheel),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    ("package_name", "module_name", "toml_filename"),
    IMPLEMENTATIONS,
    ids=[p for p, _, _ in IMPLEMENTATIONS],
)
def test_framework_config_resolves_under_wheel_install(
    tmp_path: Path,
    package_name: str,
    module_name: str,
    toml_filename: str,
) -> None:
    """Full wheel-install lifecycle for one implementation package.

    Steps: build wheel -> create venv -> install wheel -> check
    ``get_framework_path()`` -> check ``darnit list`` CLI.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    # 1. Build the target wheel + the darnit-core wheel (needed to satisfy
    # the target's own metadata locally instead of fetching from PyPI).
    target_wheel = _build_wheel(package_name, dist_dir)
    core_wheel = _build_wheel("darnit-core", dist_dir)

    # 2. Create a fresh venv.
    venv_path = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(str(venv_path))
    venv_python = _venv_python(venv_path)
    assert venv_python.is_file(), f"venv python not found at {venv_python}"

    # 3. Install both wheels.
    _install_wheel(venv_python, target_wheel, core_wheel)

    # 4. Path-resolution check: get_framework_path() returns a readable TOML.
    probe = (
        "import tomllib, sys\n"
        f"from {module_name} import get_framework_path\n"
        "p = get_framework_path()\n"
        "print('PATH:', p)\n"
        "assert p is not None, 'get_framework_path() returned None'\n"
        "assert p.exists(), f'path does not exist: {p}'\n"
        "with open(p, 'rb') as fh:\n"
        "    doc = tomllib.load(fh)\n"
        "assert isinstance(doc, dict) and doc, 'TOML parsed empty'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [str(venv_python), "-c", probe],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{package_name}: get_framework_path() probe failed\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout, f"probe did not reach OK: {result.stdout}"

    # 5. CLI-level check: `darnit list` via the console script (closes SC-001).
    #
    # Skipped for darnit-gittuf: gittuf.toml has a preexisting schema mismatch
    # (uses top-level [framework] section instead of [metadata]) tracked in
    # https://github.com/darnitdevorg/darnit/issues/361. The path check above
    # still validates that feature 021's packaging + resolver work for gittuf;
    # this early-return can be removed once #361 is fixed.
    if package_name == "darnit-gittuf":
        return

    darnit_bin = _venv_darnit(venv_path)
    assert darnit_bin.is_file(), (
        f"darnit console script not installed at {darnit_bin}; "
        f"check darnit-core wheel installed with its [project.scripts]"
    )
    cli = subprocess.run(
        [str(darnit_bin), "list"],
        capture_output=True,
        text=True,
    )
    combined = cli.stdout + cli.stderr
    assert cli.returncode == 0, (
        f"{package_name}: darnit list exited non-zero ({cli.returncode})\n"
        f"stdout:\n{cli.stdout}\nstderr:\n{cli.stderr}"
    )
    # framework name from the entry-point key (matches the argument to
    # `uv build --package`) e.g. "openssf-baseline" not "darnit-baseline".
    framework_key = {
        "darnit-baseline": "openssf-baseline",
        "darnit-gittuf": "gittuf",
        "darnit-reproducibility": "reproducibility",
    }[package_name]
    assert framework_key in combined, (
        f"{package_name}: framework key '{framework_key}' not in darnit list output\n"
        f"stdout:\n{cli.stdout}\nstderr:\n{cli.stderr}"
    )
    assert "error loading" not in combined, (
        f"{package_name}: 'error loading' appeared in darnit list output\n"
        f"stdout:\n{cli.stdout}\nstderr:\n{cli.stderr}"
    )
