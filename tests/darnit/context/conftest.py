"""Pytest configuration for context tests."""

import hashlib
import urllib.request
from pathlib import Path

import pytest

# Path to store the tracked hash
HASH_FILE = Path(__file__).parent.parent.parent.parent / ".github" / "dot-project-spec-hash.txt"
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/cncf/automation/main/utilities/dot-project/types.go"
)


def pytest_addoption(parser):
    """Add --update-hash option to pytest."""
    parser.addoption(
        "--update-hash",
        action="store_true",
        default=False,
        help="Update the tracked upstream .project/ spec hash",
    )


def pytest_configure(config):
    """Register the upstream marker."""
    config.addinivalue_line(
        "markers", "upstream: marks tests that check upstream spec synchronization (deselect with '-m \"not upstream\"')"
    )


@pytest.fixture
def update_upstream_hash(request):
    """Fixture to update the tracked hash when --update-hash is passed."""
    if request.config.getoption("--update-hash"):
        try:
            with urllib.request.urlopen(UPSTREAM_URL, timeout=30) as response:
                content = response.read()
            current_hash = hashlib.sha256(content).hexdigest()

            HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
            HASH_FILE.write_text(current_hash + "\n")

            print(f"\n✅ Updated tracked hash to: {current_hash}")
            print(f"   Saved to: {HASH_FILE}")
            return current_hash
        except Exception as e:
            pytest.skip(f"Could not fetch upstream spec: {e}")
    return None
