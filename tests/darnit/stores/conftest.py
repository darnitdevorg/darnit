"""Session-scoped pytest fixtures for feature 033 US3 tests.

Provides ``example_store_plugin_installed`` -- an opt-in fixture that
``pip install -e``s the fixture plugin at ``fixtures/example_store_plugin_pkg/``
so entry-point discovery can be verified against a real installed
distribution. Uninstalls at session end.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "example_store_plugin_pkg"
_DIST_NAME = "example-store-plugin"


def _pip_available() -> bool:
    return shutil.which("uv") is not None or shutil.which("pip") is not None


def _install_editable() -> subprocess.CompletedProcess:
    # Install into the exact interpreter running pytest so the newly
    # installed package is importable by this process. Prefer
    # `uv pip install --python <sys.executable>` for speed; fall back to
    # the interpreter's own `pip`.
    if shutil.which("uv"):
        cmd = [
            "uv", "pip", "install", "--python", sys.executable,
            "-e", str(_FIXTURE_DIR),
        ]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "-e", str(_FIXTURE_DIR)]
    return subprocess.run(cmd, capture_output=True, text=True)


def _uninstall() -> None:
    if shutil.which("uv"):
        cmd = ["uv", "pip", "uninstall", "--python", sys.executable, _DIST_NAME]
    else:
        cmd = [sys.executable, "-m", "pip", "uninstall", "-y", _DIST_NAME]
    subprocess.run(cmd, capture_output=True, text=True)


@pytest.fixture(scope="session")
def example_store_plugin_installed():
    """Install the fixture plugin for the test session; uninstall at end.

    Opt-in (not autouse). Any US3 test that needs a real installed
    third-party plugin depends on this fixture.
    """
    if not _pip_available():
        pytest.skip("neither `uv` nor `pip` available for fixture install")

    proc = _install_editable()
    if proc.returncode != 0:
        pytest.skip(
            f"failed to install fixture plugin: {proc.stderr[:400]}"
        )

    # importlib caches finders; force it to pick up the freshly-installed
    # package before any test tries `import example_store_plugin`.
    import importlib
    import site

    importlib.invalidate_caches()
    if hasattr(site, "getsitepackages"):
        for p in site.getsitepackages():
            if p not in sys.path:
                sys.path.insert(0, p)
    # Even after site refresh, an editable install performed mid-session
    # may fail to add its ``src/`` layout to sys.path (finders were
    # frozen at interpreter start). Prepend the fixture's ``src/``
    # directly so `import example_store_plugin` resolves; the dist-info
    # is what makes entry-point discovery work.
    fixture_src = str(_FIXTURE_DIR / "src")
    if fixture_src not in sys.path:
        sys.path.insert(0, fixture_src)

    # Reset the discovery cache so the freshly-installed entry point is
    # discovered on next call.
    from darnit.stores import discovery
    discovery._reset_discovery_cache()

    try:
        yield
    finally:
        _uninstall()
        discovery._reset_discovery_cache()
        # Purge the imported module so a re-install in a subsequent
        # session gets fresh module objects.
        for mod in list(sys.modules):
            if mod == "example_store_plugin" or mod.startswith(
                "example_store_plugin."
            ):
                del sys.modules[mod]
