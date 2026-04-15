"""Tests for the DotProjectMapper context mapper.

These tests verify:
1. Mapper initialization with and without owner
2. Config property with org resolution and merging
3. YAML parsing through DotProjectReader
4. Context variable generation and flattening
5. Edge cases: missing .project/, empty sections, legacy formats
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestDotProjectMapperInitialization:
    """Test DotProjectMapper initialization and config property."""

    @pytest.mark.unit
    def test_init_with_repo_path_only(self, tmp_path: Path):
        """Mapper initializes correctly with repo_path only."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        mapper = DotProjectMapper(tmp_path)

        assert mapper.repo_path == tmp_path
        assert mapper.owner == ""
        assert mapper.reader is not None

    @pytest.mark.unit
    def test_init_with_owner(self, tmp_path: Path):
        """Mapper initializes correctly with repo_path and owner."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        mapper = DotProjectMapper(tmp_path, owner="my-org")

        assert mapper.repo_path == tmp_path
        assert mapper.owner == "my-org"

    @pytest.mark.unit
    def test_config_property_uses_local_when_no_owner(self, tmp_path: Path):
        """Config property returns local config when no owner specified."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        local_config = ProjectConfig(name="local-project", repositories=["https://github.com/org/repo"])

        with patch.object(DotProjectReader, "read", return_value=local_config):
            mapper = DotProjectMapper(tmp_path)
            config = mapper.config

            assert config.name == "local-project"
            assert config.repositories == ["https://github.com/org/repo"]

    @pytest.mark.unit
    def test_config_property_caches_result(self, tmp_path: Path):
        """Config property caches result on subsequent accesses."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        local_config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=local_config) as mock_read:
            mapper = DotProjectMapper(tmp_path)

            # Multiple accesses should only call read once
            _ = mapper.config
            _ = mapper.config

            assert mock_read.call_count == 1

    @pytest.mark.unit
    def test_config_property_merges_org_and_local(self, tmp_path: Path):
        """Config property merges org config with local when owner specified."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper
        from darnit.context.dot_project_org import OrgProjectResolver

        org_config = ProjectConfig(name="org-project", repositories=["https://github.com/org/repo1"])
        local_config = ProjectConfig(name="local-project", repositories=["https://github.com/org/repo2"])
        merged_config = ProjectConfig(name="local-project", repositories=["https://github.com/org/repo2"])

        with (
            patch.object(DotProjectReader, "read", return_value=local_config),
            patch.object(OrgProjectResolver, "resolve", return_value=org_config),
            patch("darnit.context.dot_project_mapper.merge_configs", return_value=merged_config),
        ):
            mapper = DotProjectMapper(tmp_path, owner="my-org")
            config = mapper.config

            assert config.name == "local-project"

    @pytest.mark.unit
    def test_config_property_handles_org_resolution_error(self, tmp_path: Path):
        """Config property falls back to local config on org resolution error."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper
        from darnit.context.dot_project_org import OrgProjectResolver

        local_config = ProjectConfig(name="local-project", repositories=[])

        with (
            patch.object(DotProjectReader, "read", return_value=local_config),
            patch.object(OrgProjectResolver, "resolve", side_effect=RuntimeError("Network error")),
        ):
            mapper = DotProjectMapper(tmp_path, owner="my-org")
            config = mapper.config

            assert config.name == "local-project"

    @pytest.mark.unit
    def test_config_property_handles_missing_dot_project(self, tmp_path: Path):
        """Config property returns empty config when .project/ doesn't exist."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        # DotProjectReader returns empty config when file doesn't exist
        mapper = DotProjectMapper(tmp_path)
        config = mapper.config

        assert config.name == ""
        assert config.repositories == []


class TestDotProjectMapperContextGeneration:
    """Test context variable generation and flattening."""

    @pytest.mark.unit
    def test_get_context_returns_dict(self, tmp_path: Path):
        """get_context() returns a dictionary."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert isinstance(context, dict)

    @pytest.mark.unit
    def test_get_context_caches_result(self, tmp_path: Path):
        """get_context() caches result on subsequent accesses."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)

            context1 = mapper.get_context()
            context2 = mapper.get_context()

            assert context1 is context2  # Same object reference

    @pytest.mark.unit
    def test_get_context_maps_core_fields(self, tmp_path: Path):
        """get_context() maps core project fields to context variables."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="my-project",
            description="A test project",
            schema_version="1.0.0",
            type="software",
            slug="my-project",
            project_lead="@alice",
            website="https://example.com",
            repositories=["https://github.com/org/repo"],
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.name"] == "my-project"
            assert context["project.description"] == "A test project"
            assert context["project.schema_version"] == "1.0.0"
            assert context["project.type"] == "software"
            assert context["project.slug"] == "my-project"
            assert context["project.project_lead"] == "@alice"
            assert context["project.website"] == "https://example.com"
            assert context["project.repositories"] == ["https://github.com/org/repo"]

    @pytest.mark.unit
    def test_get_context_maps_maintainers(self, tmp_path: Path):
        """get_context() maps maintainers list to context variable."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            maintainers=["@alice", "@bob", "@charlie"],
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.maintainers"] == ["@alice", "@bob", "@charlie"]

    @pytest.mark.unit
    def test_get_context_maps_security_section(self, tmp_path: Path):
        """get_context() maps security section paths to context variables."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            ProjectConfig,
            SecurityConfig,
            SecurityContact,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            security=SecurityConfig(
                policy=FileReference(path="SECURITY.md"),
                threat_model=FileReference(path="docs/threat-model.md"),
                contact=SecurityContact(email="security@example.com", advisory_url="https://example.com/advisories"),
            ),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.security.policy_path"] == "SECURITY.md"
            assert context["project.security.threat_model_path"] == "docs/threat-model.md"
            assert context["project.security.contact_email"] == "security@example.com"
            assert context["project.security.advisory_url"] == "https://example.com/advisories"

    @pytest.mark.unit
    def test_get_context_maps_security_contact_legacy_string(self, tmp_path: Path):
        """get_context() handles legacy plain-string security contact."""
        from darnit.context.dot_project import (
            DotProjectReader,
            ProjectConfig,
            SecurityConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            security=SecurityConfig(contact="security@example.com"),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.security.contact"] == "security@example.com"

    @pytest.mark.unit
    def test_get_context_maps_governance_section(self, tmp_path: Path):
        """get_context() maps governance section paths to context variables."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            GovernanceConfig,
            ProjectConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            governance=GovernanceConfig(
                contributing=FileReference(path="CONTRIBUTING.md"),
                codeowners=FileReference(path=".github/CODEOWNERS"),
                governance_doc=FileReference(path="GOVERNANCE.md"),
                code_of_conduct=FileReference(path="CODE_OF_CONDUCT.md"),
            ),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.governance.contributing_path"] == "CONTRIBUTING.md"
            assert context["project.governance.codeowners_path"] == ".github/CODEOWNERS"
            assert context["project.governance.governance_doc_path"] == "GOVERNANCE.md"
            assert context["project.governance.code_of_conduct_path"] == "CODE_OF_CONDUCT.md"

    @pytest.mark.unit
    def test_get_context_maps_maintainer_lifecycle(self, tmp_path: Path):
        """get_context() maps nested maintainer lifecycle paths."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            GovernanceConfig,
            MaintainerLifecycle,
            ProjectConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            governance=GovernanceConfig(
                maintainer_lifecycle=MaintainerLifecycle(
                    onboarding_doc=FileReference(path="docs/maintainer-onboarding.md"),
                    progression_ladder=FileReference(path="docs/progression-ladder.md"),
                    offboarding_policy=FileReference(path="docs/offboarding.md"),
                    mentoring_program=["mentoring-guide.md"],
                ),
            ),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert (
                context["project.governance.maintainer_lifecycle.onboarding_doc_path"]
                == "docs/maintainer-onboarding.md"
            )
            assert (
                context["project.governance.maintainer_lifecycle.progression_ladder_path"]
                == "docs/progression-ladder.md"
            )
            assert context["project.governance.maintainer_lifecycle.offboarding_policy_path"] == "docs/offboarding.md"
            assert context["project.governance.maintainer_lifecycle.mentoring_program"] == ["mentoring-guide.md"]

    @pytest.mark.unit
    def test_get_context_maps_legal_section(self, tmp_path: Path):
        """get_context() maps legal section to context variables."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            IdentityType,
            LegalConfig,
            ProjectConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            legal=LegalConfig(
                license=FileReference(path="LICENSE"),
                identity_type=IdentityType(
                    has_dco=True,
                    has_cla=False,
                    dco_url=FileReference(path="DCO"),
                    cla_url=None,
                ),
            ),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.legal.license_path"] == "LICENSE"
            assert context["project.legal.identity_type.has_dco"] is True
            assert context["project.legal.identity_type.has_cla"] is False
            assert context["project.legal.identity_type.dco_url_path"] == "DCO"

    @pytest.mark.unit
    def test_get_context_maps_documentation_section(self, tmp_path: Path):
        """get_context() maps documentation section paths."""
        from darnit.context.dot_project import (
            DocumentationConfig,
            DotProjectReader,
            FileReference,
            ProjectConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            documentation=DocumentationConfig(
                readme=FileReference(path="README.md"),
                support=FileReference(path="SUPPORT.md"),
                architecture=FileReference(path="docs/architecture.md"),
                api=FileReference(path="docs/api.md"),
            ),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.documentation.readme_path"] == "README.md"
            assert context["project.documentation.support_path"] == "SUPPORT.md"
            assert context["project.documentation.architecture_path"] == "docs/architecture.md"
            assert context["project.documentation.api_path"] == "docs/api.md"

    @pytest.mark.unit
    def test_get_context_maps_social_links(self, tmp_path: Path):
        """get_context() maps social links dictionary."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            social={
                "twitter": "@myproject",
                "slack": "myworkspace",
                "github": "org-name",
            },
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.social.twitter"] == "@myproject"
            assert context["project.social.slack"] == "myworkspace"
            assert context["project.social.github"] == "org-name"

    @pytest.mark.unit
    def test_get_context_maps_extensions(self, tmp_path: Path):
        """get_context() maps extension configurations."""
        from darnit.context.dot_project import DotProjectReader, ExtensionConfig, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            extensions={
                "darnit": ExtensionConfig(
                    metadata={"version": "1.0"},
                    config={"auto_detect": True},
                ),
                "custom": ExtensionConfig(
                    metadata={"author": "team"},
                    config={"enabled": True},
                ),
            },
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.extensions.darnit.metadata.version"] == "1.0"
            assert context["project.extensions.darnit.config.auto_detect"] is True
            assert context["project.extensions.custom.metadata.author"] == "team"
            assert context["project.extensions.custom.config.enabled"] is True


class TestDotProjectMapperHelperMethods:
    """Test helper methods for quick checks."""

    @pytest.mark.unit
    def test_has_security_policy_returns_true(self, tmp_path: Path):
        """has_security_policy() returns True when policy is defined."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            ProjectConfig,
            SecurityConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            security=SecurityConfig(policy=FileReference(path="SECURITY.md")),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.has_security_policy() is True

    @pytest.mark.unit
    def test_has_security_policy_returns_false(self, tmp_path: Path):
        """has_security_policy() returns False when policy is not defined."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.has_security_policy() is False

    @pytest.mark.unit
    def test_has_codeowners_returns_true(self, tmp_path: Path):
        """has_codeowners() returns True when CODEOWNERS is defined."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            GovernanceConfig,
            ProjectConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            governance=GovernanceConfig(codeowners=FileReference(path=".github/CODEOWNERS")),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.has_codeowners() is True

    @pytest.mark.unit
    def test_has_codeowners_returns_false(self, tmp_path: Path):
        """has_codeowners() returns False when CODEOWNERS is not defined."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.has_codeowners() is False

    @pytest.mark.unit
    def test_has_maintainers_returns_true(self, tmp_path: Path):
        """has_maintainers() returns True when maintainers are defined."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            maintainers=["@alice", "@bob"],
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.has_maintainers() is True

    @pytest.mark.unit
    def test_has_maintainers_returns_false(self, tmp_path: Path):
        """has_maintainers() returns False when maintainers list is empty."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.has_maintainers() is False

    @pytest.mark.unit
    def test_get_security_policy_path(self, tmp_path: Path):
        """get_security_policy_path() returns correct path."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            ProjectConfig,
            SecurityConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            security=SecurityConfig(policy=FileReference(path="docs/security.md")),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.get_security_policy_path() == "docs/security.md"

    @pytest.mark.unit
    def test_get_security_policy_path_returns_none(self, tmp_path: Path):
        """get_security_policy_path() returns None when not defined."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.get_security_policy_path() is None

    @pytest.mark.unit
    def test_get_codeowners_path(self, tmp_path: Path):
        """get_codeowners_path() returns correct path."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            GovernanceConfig,
            ProjectConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            governance=GovernanceConfig(codeowners=FileReference(path=".github/CODEOWNERS")),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.get_codeowners_path() == ".github/CODEOWNERS"

    @pytest.mark.unit
    def test_get_codeowners_path_returns_none(self, tmp_path: Path):
        """get_codeowners_path() returns None when not defined."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            assert mapper.get_codeowners_path() is None

    @pytest.mark.unit
    def test_get_darnit_extension_config(self, tmp_path: Path):
        """get_darnit_extension_config() returns darnit extension config."""
        from darnit.context.dot_project import DotProjectReader, ExtensionConfig, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            extensions={
                "darnit": ExtensionConfig(
                    config={"auto_detect": True, "baseline": "openssf"},
                ),
            },
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            ext_config = mapper.get_darnit_extension_config()

            assert ext_config["auto_detect"] is True
            assert ext_config["baseline"] == "openssf"

    @pytest.mark.unit
    def test_get_darnit_extension_config_returns_empty_dict(self, tmp_path: Path):
        """get_darnit_extension_config() returns empty dict when not present."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="test-project", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            ext_config = mapper.get_darnit_extension_config()

            assert ext_config == {}


class TestDotProjectMapperEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.unit
    def test_get_context_with_empty_config(self, tmp_path: Path):
        """get_context() handles empty project config gracefully."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(name="", repositories=[])

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            # Should not include empty fields
            assert "project.name" not in context
            assert isinstance(context, dict)

    @pytest.mark.unit
    def test_get_context_with_none_sections(self, tmp_path: Path):
        """get_context() handles None sections gracefully."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            security=None,
            governance=None,
            legal=None,
            documentation=None,
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert "project.security" not in context
            assert "project.governance" not in context

    @pytest.mark.unit
    def test_repo_path_accepts_string(self, tmp_path: Path):
        """Mapper accepts repo_path as string and converts to Path."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        mapper = DotProjectMapper(str(tmp_path))
        assert isinstance(mapper.repo_path, Path)
        assert mapper.repo_path == tmp_path

    @pytest.mark.unit
    def test_repo_path_accepts_path_object(self, tmp_path: Path):
        """Mapper accepts repo_path as Path object."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        mapper = DotProjectMapper(tmp_path)
        assert isinstance(mapper.repo_path, Path)
        assert mapper.repo_path == tmp_path

    @pytest.mark.unit
    def test_get_context_with_extra_fields(self, tmp_path: Path):
        """get_context() includes extra fields from _extra dict."""
        from darnit.context.dot_project import (
            DotProjectReader,
            ProjectConfig,
            SecurityConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        security = SecurityConfig()
        security._extra = {"custom_field": "custom_value"}

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            security=security,
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.security.custom_field"] == "custom_value"

    @pytest.mark.unit
    def test_get_context_omits_none_file_references(self, tmp_path: Path):
        """get_context() omits None file references."""
        from darnit.context.dot_project import (
            DotProjectReader,
            FileReference,
            GovernanceConfig,
            ProjectConfig,
        )
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            governance=GovernanceConfig(
                contributing=FileReference(path="CONTRIBUTING.md"),
                codeowners=None,
                governance_doc=None,
            ),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert "project.governance.contributing_path" in context
            assert "project.governance.codeowners_path" not in context
            assert "project.governance.governance_doc_path" not in context

    @pytest.mark.unit
    def test_get_context_with_structured_maintainers(self, tmp_path: Path):
        """get_context() maps structured maintainer fields."""
        from darnit.context.dot_project import DotProjectReader, MaintainerTeam, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            maintainer_org="my-org",
            maintainer_project_id="12345",
            maintainer_teams=[
                MaintainerTeam(name="core-team"),
                MaintainerTeam(name="emeritus"),
            ],
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.maintainer_org"] == "my-org"
            assert context["project.maintainer_project_id"] == "12345"
            assert context["project.maintainer_teams"] == ["core-team", "emeritus"]

    @pytest.mark.unit
    def test_get_context_with_landscape_section(self, tmp_path: Path):
        """get_context() maps landscape category and subcategory."""
        from darnit.context.dot_project import DotProjectReader, LandscapeConfig, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            landscape=LandscapeConfig(
                category="App Definition and Development",
                subcategory="Runtime",
            ),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.landscape.category"] == "App Definition and Development"
            assert context["project.landscape.subcategory"] == "Runtime"

    @pytest.mark.unit
    def test_get_context_with_mailing_lists(self, tmp_path: Path):
        """get_context() maps mailing lists."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            mailing_lists=["users@example.com", "dev@example.com"],
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.mailing_lists"] == ["users@example.com", "dev@example.com"]

    @pytest.mark.unit
    def test_get_context_with_adopters_path(self, tmp_path: Path):
        """get_context() maps adopters file reference."""
        from darnit.context.dot_project import DotProjectReader, FileReference, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            adopters=FileReference(path="docs/adopters.md"),
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.adopters_path"] == "docs/adopters.md"

    @pytest.mark.unit
    def test_get_context_with_package_managers(self, tmp_path: Path):
        """get_context() maps package managers dictionary."""
        from darnit.context.dot_project import DotProjectReader, ProjectConfig
        from darnit.context.dot_project_mapper import DotProjectMapper

        config = ProjectConfig(
            name="test-project",
            repositories=[],
            package_managers={
                "npm": "my-package",
                "pip": "my-package",
                "cargo": "my-package",
            },
        )

        with patch.object(DotProjectReader, "read", return_value=config):
            mapper = DotProjectMapper(tmp_path)
            context = mapper.get_context()

            assert context["project.package_managers"]["npm"] == "my-package"
            assert context["project.package_managers"]["pip"] == "my-package"
            assert context["project.package_managers"]["cargo"] == "my-package"
