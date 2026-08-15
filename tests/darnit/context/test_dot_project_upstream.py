"""Tests for tracking upstream CNCF .project/ specification changes.

These tests verify that our implementation stays in sync with the upstream
CNCF .project/ specification at:
https://github.com/cncf/automation/tree/main/utilities/dot-project

Run locally to check for upstream changes:
    uv run pytest tests/darnit/context/test_dot_project_upstream.py -v

Update the tracked hash after syncing with upstream:
    uv run pytest tests/darnit/context/test_dot_project_upstream.py -v --update-hash

This test is marked with @pytest.mark.upstream and runs nightly in CI.
It does NOT block PRs - it's informational to alert maintainers when
the upstream spec evolves.

Note: There are active PRs in the CNCF repo exploring spec changes.
Monitor: https://github.com/cncf/automation/pulls
"""

import hashlib
import urllib.request
from pathlib import Path

import pytest

# Upstream spec location
UPSTREAM_TYPES_GO_URL = (
    "https://raw.githubusercontent.com/cncf/automation/main/utilities/dot-project/types.go"
)

# Path to store the tracked hash
HASH_FILE = Path(__file__).parent.parent.parent.parent / ".github" / "dot-project-spec-hash.txt"


def fetch_upstream_types_go() -> bytes:
    """Fetch the current types.go from upstream."""
    try:
        with urllib.request.urlopen(UPSTREAM_TYPES_GO_URL, timeout=30) as response:
            return response.read()
    except Exception as e:
        pytest.skip(f"Could not fetch upstream spec: {e}")


def get_tracked_hash() -> str | None:
    """Get the hash we're currently tracking."""
    if HASH_FILE.exists():
        return HASH_FILE.read_text().strip()
    return None


def compute_hash(content: bytes) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content).hexdigest()


@pytest.mark.upstream
class TestUpstreamSpecSync:
    """Tests for upstream .project/ specification synchronization.

    These tests are marked with @pytest.mark.upstream and should be run:
    - Nightly in CI to detect upstream changes
    - Manually when checking if we need to update our implementation

    They can be excluded from normal runs with: -m "not upstream"
    """

    def test_upstream_spec_unchanged(self, update_upstream_hash):
        """Verify upstream types.go hasn't changed since we last synced.

        If this test fails, the upstream CNCF .project/ specification has
        changed. Review the changes and update our implementation:

        1. Review changes: https://github.com/cncf/automation/tree/main/utilities/dot-project
        2. Update dot_project.py to handle new fields
        3. Update DOT_PROJECT_SPEC_VERSION if needed
        4. Run: uv run pytest tests/darnit/context/test_dot_project_upstream.py -v --update-hash
        """
        # If --update-hash was passed, the fixture already updated it
        if update_upstream_hash:
            return  # Hash was just updated, test passes

        content = fetch_upstream_types_go()
        current_hash = compute_hash(content)
        tracked_hash = get_tracked_hash()

        if tracked_hash is None:
            pytest.fail(
                f"No tracked hash found. Initialize with:\n"
                f"  uv run pytest tests/darnit/context/test_dot_project_upstream.py -v --update-hash\n\n"
                f"Current upstream hash: {current_hash}"
            )

        if current_hash != tracked_hash:
            pytest.fail(
                f"Upstream .project/ spec has changed!\n\n"
                f"Tracked hash: {tracked_hash}\n"
                f"Current hash: {current_hash}\n\n"
                f"Review changes at:\n"
                f"  https://github.com/cncf/automation/tree/main/utilities/dot-project\n\n"
                f"After updating implementation, run:\n"
                f"  uv run pytest tests/darnit/context/test_dot_project_upstream.py -v --update-hash\n\n"
                f"Also check open PRs for upcoming changes:\n"
                f"  https://github.com/cncf/automation/pulls\n\n"
                f"Runbook for reconciling with a new upstream:\n"
                f"  specs/030-dot-project-spec-sync/quickstart.md"
            )

    @pytest.mark.upstream
    def test_our_spec_version_is_documented(self):
        """Verify we document which spec version we target."""
        from darnit.context.dot_project import DOT_PROJECT_SPEC_URL, DOT_PROJECT_SPEC_VERSION

        assert DOT_PROJECT_SPEC_VERSION, "DOT_PROJECT_SPEC_VERSION should be set"
        assert DOT_PROJECT_SPEC_URL, "DOT_PROJECT_SPEC_URL should be set"
        assert "cncf" in DOT_PROJECT_SPEC_URL.lower(), "URL should point to CNCF repo"

    @pytest.mark.upstream
    def test_known_fields_are_supported(self):
        """Verify we support all known fields from the spec.

        This test documents the fields we expect from types.go and verifies
        our dataclasses can handle them.
        """
        from darnit.context.dot_project import (
            DocumentationConfig,
            GovernanceConfig,
            IdentityType,
            LandscapeConfig,
            LegalConfig,
            MaintainerLifecycle,
            ProjectConfig,
            SecurityConfig,
        )

        # Core ProjectConfig fields from types.go
        config = ProjectConfig()
        assert hasattr(config, 'name')
        assert hasattr(config, 'description')
        assert hasattr(config, 'schema_version')
        assert hasattr(config, 'type')
        assert hasattr(config, 'slug')
        assert hasattr(config, 'project_lead')
        assert hasattr(config, 'cncf_slack_channel')
        assert hasattr(config, 'website')
        assert hasattr(config, 'artwork')
        assert hasattr(config, 'adopters')
        assert hasattr(config, 'repositories')
        assert hasattr(config, 'mailing_lists')
        assert hasattr(config, 'social')
        assert hasattr(config, 'package_managers')
        assert hasattr(config, 'maturity_log')
        assert hasattr(config, 'audits')
        assert hasattr(config, 'security')
        assert hasattr(config, 'governance')
        assert hasattr(config, 'legal')
        assert hasattr(config, 'documentation')
        assert hasattr(config, 'landscape')
        assert hasattr(config, 'extensions')

        # Security section fields
        security = SecurityConfig()
        assert hasattr(security, 'policy')
        assert hasattr(security, 'threat_model')
        assert hasattr(security, 'contact')
        assert hasattr(security, '_extra')  # Forward compatibility

        # Governance section fields
        governance = GovernanceConfig()
        assert hasattr(governance, 'contributing')
        assert hasattr(governance, 'codeowners')
        assert hasattr(governance, 'governance_doc')
        assert hasattr(governance, 'gitvote_config')
        assert hasattr(governance, 'vendor_neutrality_statement')
        assert hasattr(governance, 'decision_making_process')
        assert hasattr(governance, 'roles_and_teams')
        assert hasattr(governance, 'code_of_conduct')
        assert hasattr(governance, 'sub_project_list')
        assert hasattr(governance, 'sub_project_docs')
        assert hasattr(governance, 'contributor_ladder')
        assert hasattr(governance, 'change_process')
        assert hasattr(governance, 'comms_channels')
        assert hasattr(governance, 'community_calendar')
        assert hasattr(governance, 'contributor_guide')
        assert hasattr(governance, 'maintainer_lifecycle')
        assert hasattr(governance, '_extra')

        # Maintainer lifecycle fields
        ml = MaintainerLifecycle()
        assert hasattr(ml, 'onboarding_doc')
        assert hasattr(ml, 'progression_ladder')
        assert hasattr(ml, 'offboarding_policy')
        assert hasattr(ml, 'mentoring_program')
        assert hasattr(ml, '_extra')

        # Legal section fields
        legal = LegalConfig()
        assert hasattr(legal, 'license')
        assert hasattr(legal, 'identity_type')
        assert hasattr(legal, '_extra')

        # Identity type fields
        identity = IdentityType()
        assert hasattr(identity, 'has_dco')
        assert hasattr(identity, 'has_cla')
        assert hasattr(identity, 'dco_url')
        assert hasattr(identity, 'cla_url')
        assert hasattr(identity, '_extra')

        # Documentation section fields
        docs = DocumentationConfig()
        assert hasattr(docs, 'readme')
        assert hasattr(docs, 'support')
        assert hasattr(docs, 'architecture')
        assert hasattr(docs, 'api')
        assert hasattr(docs, '_extra')

        # Landscape fields
        landscape = LandscapeConfig()
        assert hasattr(landscape, 'category')
        assert hasattr(landscape, 'subcategory')
        assert hasattr(landscape, '_extra')


# Regression tests for the sync-test's failure diagnostics (feature 030 US2).
# These live OUTSIDE the @pytest.mark.upstream class so they run on every
# PR and lock the behavior spec User Story 2 depends on.


def test_upstream_spec_failure_message_names_both_hashes(monkeypatch):
    """FR-014/US2: fabricated tracked hash triggers a `pytest.fail` whose
    message names both hashes AND references the reconciliation runbook.

    Locks the loud-diagnostic behavior of `test_upstream_spec_unchanged`
    against a future rewrite that swallows either hash or drops the
    runbook pointer.
    """
    import sys

    mod = sys.modules[__name__]

    fake_tracked = "d" * 64  # 64 hex chars; obviously not a real upstream hash
    fake_content = b"// fabricated upstream content for regression test\n"
    fake_current = compute_hash(fake_content)

    monkeypatch.setattr(mod, "get_tracked_hash", lambda: fake_tracked)
    monkeypatch.setattr(mod, "fetch_upstream_types_go", lambda: fake_content)

    with pytest.raises(pytest.fail.Exception) as excinfo:
        TestUpstreamSpecSync().test_upstream_spec_unchanged(update_upstream_hash=False)

    msg = str(excinfo.value)
    assert fake_tracked in msg, "failure message must name the tracked hash"
    assert fake_current in msg, "failure message must name the current upstream hash"
    assert "specs/030-dot-project-spec-sync/quickstart.md" in msg, (
        "failure message must point at the reconciliation runbook"
    )


def test_upstream_spec_skips_when_offline(monkeypatch):
    """FR-007/US2: a `URLError` at fetch time yields `pytest.skip`, not
    `pytest.fail`. Locks the offline-tolerance behavior against a future
    rewrite of the fetch path.
    """
    import sys
    import urllib.error

    mod = sys.modules[__name__]

    def _raise_urlerror(*_args, **_kwargs):
        raise urllib.error.URLError("simulated offline")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_urlerror)

    with pytest.raises(pytest.skip.Exception):
        # Call the module-level fetch helper directly. Whether the harness
        # would then invoke test_upstream_spec_unchanged is irrelevant: the
        # skip is raised inside fetch_upstream_types_go and propagates.
        mod.fetch_upstream_types_go()
