"""Tests for .project/ config merge logic."""

from pathlib import Path

import pytest

from darnit.context.dot_project import (
    FileReference,
    GovernanceConfig,
    ProjectConfig,
    SecurityConfig,
)
from darnit.context.dot_project_merger import merge_configs


class TestMergeConfigs:
    """Test the merge_configs function."""

    @pytest.mark.unit
    def test_merge_returns_local_when_org_is_none(self):
        """Merge returns local config unchanged when org is None."""
        local = ProjectConfig(name="local-project")
        result = merge_configs(None, local)
        assert result.name == "local-project"

    @pytest.mark.unit
    def test_merge_uses_org_defaults_for_missing_local_fields(self):
        """Merge uses org values when local fields are empty."""
        org = ProjectConfig(
            name="org-project",
            description="Org description",
            website="https://org.example.com",
        )
        local = ProjectConfig(name="local-project")

        result = merge_configs(org, local)
        assert result.name == "local-project"  # Local overrides
        assert result.description == "Org description"  # Org default
        assert result.website == "https://org.example.com"  # Org default

    @pytest.mark.unit
    def test_merge_local_scalars_override_org(self):
        """Local scalar values override org defaults."""
        org = ProjectConfig(
            name="org-project",
            description="Org description",
            website="https://org.example.com",
        )
        local = ProjectConfig(
            name="local-project",
            description="Local description",
        )

        result = merge_configs(org, local)
        assert result.name == "local-project"
        assert result.description == "Local description"
        # Website from org since local doesn't have it
        assert result.website == "https://org.example.com"

    @pytest.mark.unit
    def test_merge_section_level_override(self):
        """Local section completely overrides org section."""
        org = ProjectConfig(
            name="org-project",
            security=SecurityConfig(
                policy=FileReference(path="ORG-SECURITY.md"),
                contact="org-security@example.com",
            ),
        )
        local = ProjectConfig(
            name="local-project",
            security=SecurityConfig(
                policy=FileReference(path="SECURITY.md"),
                # No contact in local
            ),
        )

        result = merge_configs(org, local)
        assert result.security is not None
        assert result.security.policy.path == "SECURITY.md"
        # Contact is None because local section wins entirely
        assert result.security.contact is None

    @pytest.mark.unit
    def test_merge_uses_org_section_when_local_missing(self):
        """Org section is used when local doesn't have that section."""
        org = ProjectConfig(
            name="org-project",
            security=SecurityConfig(
                policy=FileReference(path="ORG-SECURITY.md"),
                contact="org-security@example.com",
            ),
        )
        local = ProjectConfig(name="local-project")  # No security section

        result = merge_configs(org, local)
        assert result.security is not None
        assert result.security.policy.path == "ORG-SECURITY.md"
        assert result.security.contact == "org-security@example.com"

    @pytest.mark.unit
    def test_merge_list_fields_local_wins_if_present(self):
        """Local list fields override org when non-empty."""
        org = ProjectConfig(
            name="org-project",
            maintainers=["org-alice", "org-bob"],
            repositories=["https://github.com/org/repo1"],
        )
        local = ProjectConfig(
            name="local-project",
            maintainers=["local-alice"],
            # No repositories in local
        )

        result = merge_configs(org, local)
        assert result.maintainers == ["local-alice"]  # Local wins
        assert result.repositories == ["https://github.com/org/repo1"]  # Org default

    @pytest.mark.unit
    def test_merge_dict_fields_local_wins_if_present(self):
        """Local dict fields override org when non-empty."""
        org = ProjectConfig(
            name="org-project",
            social={"twitter": "@org"},
        )
        local = ProjectConfig(
            name="local-project",
            social={"twitter": "@local", "mastodon": "@local@fosstodon"},
        )

        result = merge_configs(org, local)
        assert result.social == {"twitter": "@local", "mastodon": "@local@fosstodon"}

    @pytest.mark.unit
    def test_merge_extra_fields_combined(self):
        """Extra fields from both org and local are combined."""
        org = ProjectConfig(name="org-project")
        org._extra = {"org_custom": "value1", "shared_key": "org_value"}
        local = ProjectConfig(name="local-project")
        local._extra = {"local_custom": "value2", "shared_key": "local_value"}

        result = merge_configs(org, local)
        assert result._extra["org_custom"] == "value1"
        assert result._extra["local_custom"] == "value2"
        assert result._extra["shared_key"] == "local_value"  # Local wins

    @pytest.mark.unit
    def test_merge_preserves_local_source_path(self):
        """Merged config preserves the local source path."""
        org = ProjectConfig(name="org-project")
        org._source_path = Path("/org/.project/project.yaml")
        local = ProjectConfig(name="local-project")
        local._source_path = Path("/local/.project/project.yaml")

        result = merge_configs(org, local)
        assert result._source_path == Path("/local/.project/project.yaml")

    @pytest.mark.unit
    def test_merge_does_not_mutate_inputs(self):
        """Merge creates a new config without modifying inputs."""
        org = ProjectConfig(
            name="org-project",
            maintainers=["org-alice"],
        )
        local = ProjectConfig(
            name="local-project",
            maintainers=["local-alice"],
        )

        result = merge_configs(org, local)
        result.name = "modified"
        result.maintainers.append("new-person")

        assert org.name == "org-project"
        assert org.maintainers == ["org-alice"]
        assert local.name == "local-project"
        assert local.maintainers == ["local-alice"]

    @pytest.mark.unit
    def test_merge_governance_section_level(self):
        """Governance section merges at section level, not field level."""
        org = ProjectConfig(
            name="org-project",
            governance=GovernanceConfig(
                contributing=FileReference(path="ORG-CONTRIBUTING.md"),
                codeowners=FileReference(path="ORG-CODEOWNERS"),
            ),
        )
        local = ProjectConfig(
            name="local-project",
            governance=GovernanceConfig(
                contributing=FileReference(path="CONTRIBUTING.md"),
                # No codeowners in local
            ),
        )

        result = merge_configs(org, local)
        assert result.governance is not None
        assert result.governance.contributing.path == "CONTRIBUTING.md"
        # Codeowners is None because entire governance section from local wins
        assert result.governance.codeowners is None

    @pytest.mark.unit
    def test_merge_maintainer_metadata(self):
        """Merge handles maintainer_org and maintainer_project_id."""
        org = ProjectConfig(
            name="org-project",
            maintainer_org="test-org",
            maintainer_project_id="proj-123",
        )
        local = ProjectConfig(name="local-project")

        result = merge_configs(org, local)
        assert result.maintainer_org == "test-org"
        assert result.maintainer_project_id == "proj-123"
