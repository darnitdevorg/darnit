# SPDX-License-Identifier: Apache-2.0
"""The attestation extra's Sigstore floor must provide SigningContext.from_trust_config (#606).

``tests/conftest.py`` replaces ``SigningContext.from_trust_config`` with a stub
before any test body runs. An in-process ``hasattr`` check would pass because
of that stub. These probes run in a fresh interpreter, import nothing from the
test harness, and never call the method (calling it builds Fulcio, Rekor, and
timestamp clients and can start an OIDC login).
"""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_PYPROJECT = REPO_ROOT / "packages" / "darnit" / "pyproject.toml"
MIN_SIGSTORE = "4.0.0"

# Executed with ``python -c`` so pytest's autouse Sigstore monkeypatch is absent.
_PROBE = """
import inspect
import sys
from importlib.metadata import version

if "pytest" in sys.modules or "tests.conftest" in sys.modules:
    raise SystemExit("probe loaded the test harness; SigningContext may be monkeypatched")

from sigstore.sign import ClientTrustConfig, SigningContext

installed = version("sigstore")
parts = []
for piece in installed.split("."):
    digits = ""
    for char in piece:
        if not char.isdigit():
            break
        digits += char
    if not digits:
        break
    parts.append(int(digits))
if tuple(parts) < (4, 0, 0):
    raise SystemExit(f"sigstore {installed} is below 4.0.0")

exact = sys.argv[1]
if exact != "any" and installed != exact:
    raise SystemExit(f"expected sigstore {exact}, found {installed}")

found = None
for cls in SigningContext.__mro__:
    if "from_trust_config" in cls.__dict__:
        found = cls.__dict__["from_trust_config"]
        break
if found is None:
    raise SystemExit(f"sigstore {installed} SigningContext has no from_trust_config")
func = found.__func__ if isinstance(found, (classmethod, staticmethod)) else found
module = getattr(func, "__module__", "")
if not str(module).startswith("sigstore"):
    raise SystemExit(f"from_trust_config comes from {module}, not sigstore")
parameters = [
    parameter
    for parameter in inspect.signature(func).parameters.values()
    if parameter.name != "cls"
    and parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
]
if not parameters:
    raise SystemExit("from_trust_config accepts no trust-config argument")
if not isinstance(ClientTrustConfig, type):
    raise SystemExit("sigstore.sign.ClientTrustConfig is not a class")
print(installed)
"""


def _sigstore_requirement() -> Requirement:
    with CORE_PYPROJECT.open("rb") as source:
        project = tomllib.load(source)
    extras = project["project"]["optional-dependencies"]["attestation"]
    requirements = [Requirement(item) for item in extras]
    return next(item for item in requirements if item.name == "sigstore")


def _probe_env() -> dict[str, str]:
    env = os.environ.copy()
    # A parent pytest run may point imports or uv at the project environment.
    # The probe and the isolated install must see only the interpreter they name.
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    return env


def _run_probe(python: Path, exact: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-c", _PROBE, exact],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_probe_env(),
        timeout=timeout,
    )


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


@pytest.mark.unit
def test_attestation_extra_requires_sigstore_4() -> None:
    """The attestation extra and the lock require sigstore>=4.0.0."""
    requirement = _sigstore_requirement()
    assert requirement.specifier == SpecifierSet(f">={MIN_SIGSTORE}")
    assert Version(MIN_SIGSTORE) in requirement.specifier
    assert Version("3.9.0") not in requirement.specifier

    with (REPO_ROOT / "uv.lock").open("rb") as source:
        lock = tomllib.load(source)
    core = next(package for package in lock["package"] if package["name"] == "darnit-core")
    locked_requirement = next(item for item in core["metadata"]["requires-dist"] if item["name"] == "sigstore")
    assert locked_requirement["specifier"] == f">={MIN_SIGSTORE}"
    locked = next(package for package in lock["package"] if package["name"] == "sigstore")
    assert Version(locked["version"]) in requirement.specifier
    assert Version(locked["version"]) >= Version(MIN_SIGSTORE)


def test_installed_sigstore_exposes_from_trust_config() -> None:
    """The environment that runs the suite has the real 4.x method, not the conftest stub."""
    pytest.importorskip("sigstore")
    result = _run_probe(Path(sys.executable), "any")
    assert result.returncode == 0, result.stderr or result.stdout
    assert Version(result.stdout.strip()) >= Version(MIN_SIGSTORE)


@pytest.mark.live
def test_sigstore_4_0_0_exposes_from_trust_config(tmp_path: Path) -> None:
    """The minimum allowed release, in its own environment, exposes the method signing calls.

    Installing ``sigstore==4.0.0`` reaches PyPI, so this test stays opt-in (#548).
    """
    uv = shutil.which("uv")
    if uv is None:
        pytest.fail("uv is required to install sigstore==4.0.0 in an isolated environment")

    venv = tmp_path / "sigstore-4.0.0"
    env = _probe_env()
    created = subprocess.run(
        [uv, "venv", str(venv), "--python", sys.executable],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )
    assert created.returncode == 0, created.stderr or created.stdout

    python = _venv_python(venv)
    installed = subprocess.run(
        [uv, "pip", "install", "--python", str(python), f"sigstore=={MIN_SIGSTORE}"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=venv,
        timeout=300,
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout

    result = _run_probe(python, MIN_SIGSTORE)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == MIN_SIGSTORE
