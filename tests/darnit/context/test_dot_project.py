"""Tests for the CNCF .project/ specification reader and writer.

These tests verify:
1. Task 1.5.1: Basic .project/ parser functionality
2. Task 1.5.2: Tolerant parsing of unknown fields (forward compatibility)
3. Task 1.5.3: Write-back with comment preservation
4. Task 1.5.4: Integration test with real .project/ file structure
"""

from pathlib import Path

import pytest


class TestDotProjectReader:
    """Test the DotProjectReader class (Task 1.5.1)."""

    @pytest.mark.unit
    def test_reader_exists_returns_false_when_no_file(self, temp_dir: Path):
        """Reader.exists() returns False when no .project/project.yaml exists."""
        from darnit.context.dot_project import DotProjectReader

        reader = DotProjectReader(temp_dir)
        assert reader.exists() is False

    @pytest.mark.unit
    def test_reader_exists_returns_true_when_file_exists(self, temp_dir: Path):
        """Reader.exists() returns True when .project/project.yaml exists."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")

        reader = DotProjectReader(temp_dir)
        assert reader.exists() is True

    @pytest.mark.unit
    def test_read_returns_empty_config_when_no_file(self, temp_dir: Path):
        """Reader.read() returns empty ProjectConfig when file doesn't exist."""
        from darnit.context.dot_project import DotProjectReader

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.name == ""
        assert config.repositories == []

    @pytest.mark.unit
    def test_read_parses_required_fields(self, temp_dir: Path):
        """Reader correctly parses required name and repositories fields."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
  - https://github.com/org/repo2
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.name == "my-project"
        assert len(config.repositories) == 2
        assert "https://github.com/org/repo" in config.repositories

    @pytest.mark.unit
    def test_read_parses_optional_core_fields(self, temp_dir: Path):
        """Reader correctly parses optional core fields."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
description: A test project
schema_version: "1.0.0"
type: software
website: https://example.com
artwork: https://example.com/logo.png
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.description == "A test project"
        assert config.schema_version == "1.0.0"
        assert config.type == "software"
        assert config.website == "https://example.com"
        assert config.artwork == "https://example.com/logo.png"

    @pytest.mark.unit
    def test_read_parses_security_section(self, temp_dir: Path):
        """Reader correctly parses security section with file references."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy:
    path: SECURITY.md
  threat_model:
    path: docs/threat-model.md
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.security is not None
        assert config.security.policy is not None
        assert config.security.policy.path == "SECURITY.md"
        assert config.security.threat_model is not None
        assert config.security.threat_model.path == "docs/threat-model.md"

    @pytest.mark.unit
    def test_read_parses_governance_section(self, temp_dir: Path):
        """Reader correctly parses governance section."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
governance:
  contributing:
    path: CONTRIBUTING.md
  codeowners:
    path: .github/CODEOWNERS
  governance_doc:
    path: GOVERNANCE.md
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.governance is not None
        assert config.governance.contributing.path == "CONTRIBUTING.md"
        assert config.governance.codeowners.path == ".github/CODEOWNERS"
        assert config.governance.governance_doc.path == "GOVERNANCE.md"

    @pytest.mark.unit
    def test_read_parses_documentation_section(self, temp_dir: Path):
        """Reader correctly parses documentation section."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
documentation:
  readme:
    path: README.md
  support:
    path: SUPPORT.md
  architecture:
    path: docs/architecture.md
  api:
    path: docs/api.md
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.documentation is not None
        assert config.documentation.readme.path == "README.md"
        assert config.documentation.support.path == "SUPPORT.md"
        assert config.documentation.architecture.path == "docs/architecture.md"
        assert config.documentation.api.path == "docs/api.md"

    @pytest.mark.unit
    def test_read_parses_legal_section(self, temp_dir: Path):
        """Reader correctly parses legal section."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
legal:
  license:
    path: LICENSE
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.legal is not None
        assert config.legal.license.path == "LICENSE"

    @pytest.mark.unit
    def test_read_parses_extensions_section(self, temp_dir: Path):
        """Reader correctly parses extensions section."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
extensions:
  darnit:
    metadata:
      version: "1.0.0"
    config:
      level: 2
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert "darnit" in config.extensions
        assert config.extensions["darnit"].metadata["version"] == "1.0.0"
        assert config.extensions["darnit"].config["level"] == 2

    @pytest.mark.unit
    def test_read_parses_maturity_log(self, temp_dir: Path):
        """Reader correctly parses maturity_log list."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
maturity_log:
  - phase: sandbox
    date: "2024-01-01"
    issue: https://github.com/org/toc/issues/123
  - phase: incubating
    date: "2024-06-01"
    issue: https://github.com/org/toc/issues/456
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert len(config.maturity_log) == 2
        assert config.maturity_log[0].phase == "sandbox"
        assert config.maturity_log[0].date == "2024-01-01"
        assert config.maturity_log[1].phase == "incubating"

    @pytest.mark.unit
    def test_read_parses_audits(self, temp_dir: Path):
        """Reader correctly parses audits list."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
audits:
  - date: "2024-03-01"
    url: https://audits.example.com/report-123
    type: security
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert len(config.audits) == 1
        assert config.audits[0].date == "2024-03-01"
        assert config.audits[0].type == "security"

    @pytest.mark.unit
    def test_read_parses_social(self, temp_dir: Path):
        """Reader correctly parses social map."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
social:
  slack: https://slack.example.com/channel
  twitter: "@myproject"
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.social["slack"] == "https://slack.example.com/channel"
        assert config.social["twitter"] == "@myproject"


class TestDotProjectReaderMaintainers:
    """Test maintainers parsing from .project/ files."""

    @pytest.mark.unit
    def test_read_maintainers_from_maintainers_yaml_list(self, temp_dir: Path):
        """Reader reads maintainers from maintainers.yaml simple list."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
""")
        (project_dir / "maintainers.yaml").write_text("""
- alice
- "@bob"
- charlie
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert "alice" in config.maintainers
        assert "bob" in config.maintainers
        assert "charlie" in config.maintainers

    @pytest.mark.unit
    def test_read_maintainers_from_maintainers_yaml_dict_format(self, temp_dir: Path):
        """Reader reads maintainers from maintainers.yaml with dict entries."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
""")
        (project_dir / "maintainers.yaml").write_text("""
- handle: alice
  name: Alice Smith
- handle: "@bob"
  name: Bob Jones
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert "alice" in config.maintainers
        assert "bob" in config.maintainers

    @pytest.mark.unit
    def test_read_maintainers_nested_list(self, temp_dir: Path):
        """Reader reads maintainers from nested maintainers key."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
""")
        (project_dir / "maintainers.yaml").write_text("""
maintainers:
  - alice
  - bob
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert "alice" in config.maintainers
        assert "bob" in config.maintainers

    @pytest.mark.unit
    def test_normalize_handle_strips_at_symbol(self, temp_dir: Path):
        """Reader normalizes handles by stripping @ prefix."""
        from darnit.context.dot_project import DotProjectReader

        reader = DotProjectReader(temp_dir)
        assert reader._normalize_handle("@alice") == "alice"
        assert reader._normalize_handle("  @bob  ") == "bob"
        assert reader._normalize_handle("charlie") == "charlie"


class TestDotProjectReaderTolerantParsing:
    """Test tolerant parsing of unknown fields (Task 1.5.2)."""

    @pytest.mark.unit
    def test_unknown_top_level_fields_preserved(self, temp_dir: Path):
        """Unknown top-level fields are preserved in _extra."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
future_field: some_value
another_new_field:
  nested: data
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        # Known fields parsed normally
        assert config.name == "my-project"

        # Unknown fields preserved in _extra
        assert "future_field" in config._extra
        assert config._extra["future_field"] == "some_value"
        assert "another_new_field" in config._extra
        assert config._extra["another_new_field"]["nested"] == "data"

    @pytest.mark.unit
    def test_unknown_security_fields_preserved(self, temp_dir: Path):
        """Unknown fields in security section are preserved."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy:
    path: SECURITY.md
  new_security_feature: enabled
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.security is not None
        assert "new_security_feature" in config.security._extra
        assert config.security._extra["new_security_feature"] == "enabled"

    @pytest.mark.unit
    def test_unknown_governance_fields_preserved(self, temp_dir: Path):
        """Unknown fields in governance section are preserved."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
governance:
  contributing:
    path: CONTRIBUTING.md
  new_governance_field: value
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.governance is not None
        assert "new_governance_field" in config.governance._extra

    @pytest.mark.unit
    def test_unknown_maturity_entry_fields_preserved(self, temp_dir: Path):
        """Unknown fields in maturity_log entries are preserved."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
maturity_log:
  - phase: sandbox
    date: "2024-01-01"
    new_maturity_field: extra_data
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert len(config.maturity_log) == 1
        assert "new_maturity_field" in config.maturity_log[0]._extra

    @pytest.mark.unit
    def test_file_reference_string_format(self, temp_dir: Path):
        """File references can be specified as simple strings."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy: SECURITY.md
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        # String format should also work
        assert config.security is not None
        assert config.security.policy is not None
        assert config.security.policy.path == "SECURITY.md"


class TestDotProjectNewFields:
    """Test parsing of new fields added in spec 1.1.0."""

    @pytest.mark.unit
    def test_read_parses_security_contact(self, temp_dir: Path):
        """Reader correctly parses security.contact as a string."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy:
    path: SECURITY.md
  contact: security@example.com
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.security is not None
        assert config.security.contact == "security@example.com"
        assert config.security.policy.path == "SECURITY.md"

    @pytest.mark.unit
    def test_read_parses_new_governance_pathref_fields(self, temp_dir: Path):
        """Reader correctly parses all new governance PathRef fields."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
governance:
  contributing:
    path: CONTRIBUTING.md
  gitvote_config:
    path: .gitvote.yml
  vendor_neutrality_statement:
    path: VENDOR_NEUTRALITY.md
  decision_making_process:
    path: DECISION_MAKING.md
  roles_and_teams:
    path: ROLES.md
  code_of_conduct:
    path: CODE_OF_CONDUCT.md
  sub_project_list:
    path: SUB_PROJECTS.md
  sub_project_docs:
    path: docs/sub-projects/
  contributor_ladder:
    path: CONTRIBUTOR_LADDER.md
  change_process:
    path: CHANGE_PROCESS.md
  comms_channels:
    path: COMMS.md
  community_calendar:
    path: CALENDAR.md
  contributor_guide:
    path: CONTRIBUTOR_GUIDE.md
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.governance is not None
        assert config.governance.contributing.path == "CONTRIBUTING.md"
        assert config.governance.gitvote_config.path == ".gitvote.yml"
        assert config.governance.vendor_neutrality_statement.path == "VENDOR_NEUTRALITY.md"
        assert config.governance.decision_making_process.path == "DECISION_MAKING.md"
        assert config.governance.roles_and_teams.path == "ROLES.md"
        assert config.governance.code_of_conduct.path == "CODE_OF_CONDUCT.md"
        assert config.governance.sub_project_list.path == "SUB_PROJECTS.md"
        assert config.governance.sub_project_docs.path == "docs/sub-projects/"
        assert config.governance.contributor_ladder.path == "CONTRIBUTOR_LADDER.md"
        assert config.governance.change_process.path == "CHANGE_PROCESS.md"
        assert config.governance.comms_channels.path == "COMMS.md"
        assert config.governance.community_calendar.path == "CALENDAR.md"
        assert config.governance.contributor_guide.path == "CONTRIBUTOR_GUIDE.md"

    @pytest.mark.unit
    def test_read_parses_maintainer_lifecycle(self, temp_dir: Path):
        """Reader correctly parses governance.maintainer_lifecycle nested struct."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
governance:
  maintainer_lifecycle:
    onboarding_doc:
      path: ONBOARDING.md
    progression_ladder:
      path: PROGRESSION.md
    offboarding_policy:
      path: OFFBOARDING.md
    mentoring_program:
      - mentoring-2024
      - buddy-system
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.governance is not None
        ml = config.governance.maintainer_lifecycle
        assert ml is not None
        assert ml.onboarding_doc.path == "ONBOARDING.md"
        assert ml.progression_ladder.path == "PROGRESSION.md"
        assert ml.offboarding_policy.path == "OFFBOARDING.md"
        assert ml.mentoring_program == ["mentoring-2024", "buddy-system"]

    @pytest.mark.unit
    def test_read_parses_identity_type(self, temp_dir: Path):
        """Reader correctly parses legal.identity_type nested struct."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
legal:
  license:
    path: LICENSE
  identity_type:
    has_dco: true
    has_cla: false
    dco_url:
      path: DCO
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.legal is not None
        it = config.legal.identity_type
        assert it is not None
        assert it.has_dco is True
        assert it.has_cla is False
        assert it.dco_url.path == "DCO"
        assert it.cla_url is None

    @pytest.mark.unit
    def test_read_parses_new_top_level_fields(self, temp_dir: Path):
        """Reader correctly parses new top-level fields."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
slug: my-proj
project_lead: "@alice"
cncf_slack_channel: "#my-project"
adopters:
  path: ADOPTERS.md
package_managers:
  npm: my-project
  pypi: my-project
landscape:
  category: "App Definition and Development"
  subcategory: "Database"
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.slug == "my-proj"
        assert config.project_lead == "@alice"
        assert config.cncf_slack_channel == "#my-project"
        assert config.adopters is not None
        assert config.adopters.path == "ADOPTERS.md"
        assert config.package_managers == {"npm": "my-project", "pypi": "my-project"}
        assert config.landscape is not None
        assert config.landscape.category == "App Definition and Development"
        assert config.landscape.subcategory == "Database"

    @pytest.mark.unit
    def test_unknown_fields_in_new_nested_types(self, temp_dir: Path):
        """Unknown fields in new nested types go to _extra."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
governance:
  maintainer_lifecycle:
    onboarding_doc:
      path: ONBOARDING.md
    future_field: some_value
legal:
  identity_type:
    has_dco: true
    future_legal_field: test
landscape:
  category: Networking
  future_landscape_field: data
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        # maintainer_lifecycle extra
        ml = config.governance.maintainer_lifecycle
        assert "future_field" in ml._extra
        assert ml._extra["future_field"] == "some_value"

        # identity_type extra
        it = config.legal.identity_type
        assert "future_legal_field" in it._extra
        assert it._extra["future_legal_field"] == "test"

        # landscape extra
        assert "future_landscape_field" in config.landscape._extra
        assert config.landscape._extra["future_landscape_field"] == "data"


class TestDotProjectNewFieldsMapper:
    """Test mapper context variable output for new fields."""

    @pytest.mark.unit
    def test_mapper_maps_security_contact(self, temp_dir: Path):
        """Mapper correctly maps security.contact."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  contact: security@example.com
""")

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert context.get("project.security.contact") == "security@example.com"

    @pytest.mark.unit
    def test_mapper_maps_new_governance_fields(self, temp_dir: Path):
        """Mapper correctly maps new governance PathRef fields."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
governance:
  code_of_conduct:
    path: CODE_OF_CONDUCT.md
  contributor_ladder:
    path: CONTRIBUTOR_LADDER.md
  comms_channels:
    path: COMMS.md
""")

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert context.get("project.governance.code_of_conduct_path") == "CODE_OF_CONDUCT.md"
        assert context.get("project.governance.contributor_ladder_path") == "CONTRIBUTOR_LADDER.md"
        assert context.get("project.governance.comms_channels_path") == "COMMS.md"

    @pytest.mark.unit
    def test_mapper_maps_maintainer_lifecycle(self, temp_dir: Path):
        """Mapper correctly maps governance.maintainer_lifecycle nested fields."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
governance:
  maintainer_lifecycle:
    onboarding_doc:
      path: ONBOARDING.md
    mentoring_program:
      - buddy-system
""")

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert (
            context.get("project.governance.maintainer_lifecycle.onboarding_doc_path")
            == "ONBOARDING.md"
        )
        assert context.get("project.governance.maintainer_lifecycle.mentoring_program") == [
            "buddy-system"
        ]

    @pytest.mark.unit
    def test_mapper_maps_identity_type(self, temp_dir: Path):
        """Mapper correctly maps legal.identity_type nested fields."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
legal:
  identity_type:
    has_dco: true
    has_cla: false
    dco_url:
      path: DCO
""")

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert context.get("project.legal.identity_type.has_dco") is True
        assert context.get("project.legal.identity_type.has_cla") is False
        assert context.get("project.legal.identity_type.dco_url_path") == "DCO"

    @pytest.mark.unit
    def test_mapper_maps_new_top_level_fields(self, temp_dir: Path):
        """Mapper correctly maps new top-level fields."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
slug: my-proj
project_lead: "@alice"
cncf_slack_channel: "#my-project"
adopters:
  path: ADOPTERS.md
package_managers:
  npm: my-project
landscape:
  category: Networking
  subcategory: "Service Mesh"
""")

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert context.get("project.slug") == "my-proj"
        assert context.get("project.project_lead") == "@alice"
        assert context.get("project.cncf_slack_channel") == "#my-project"
        assert context.get("project.adopters_path") == "ADOPTERS.md"
        assert context.get("project.package_managers") == {"npm": "my-project"}
        assert context.get("project.landscape.category") == "Networking"
        assert context.get("project.landscape.subcategory") == "Service Mesh"


class TestDotProjectConfigValidation:
    """Test ProjectConfig validation."""

    @pytest.mark.unit
    def test_is_valid_with_required_fields(self, temp_dir: Path):
        """Config is valid when required fields are present."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        is_valid, missing = config.is_valid()
        assert is_valid is True
        assert len(missing) == 0

    @pytest.mark.unit
    def test_is_valid_missing_name(self, temp_dir: Path):
        """Config is invalid when name is missing."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
repositories:
  - https://github.com/org/repo
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        is_valid, missing = config.is_valid()
        assert is_valid is False
        assert "name" in missing

    @pytest.mark.unit
    def test_is_valid_missing_repositories(self, temp_dir: Path):
        """Config is invalid when repositories is missing."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        is_valid, missing = config.is_valid()
        assert is_valid is False
        assert "repositories" in missing

    @pytest.mark.unit
    def test_is_valid_empty_config(self):
        """Empty config is invalid."""
        from darnit.context.dot_project import ProjectConfig

        config = ProjectConfig()

        is_valid, missing = config.is_valid()
        assert is_valid is False
        assert "name" in missing
        assert "repositories" in missing


class TestDotProjectWriter:
    """Test the DotProjectWriter class (Task 1.5.3)."""

    @pytest.mark.unit
    def test_writer_creates_directory_and_file(self, temp_dir: Path):
        """Writer creates .project/ directory and project.yaml if not exists."""
        from darnit.context.dot_project import DotProjectWriter

        writer = DotProjectWriter(temp_dir)
        writer.update({"name": "new-project"})

        project_yaml = temp_dir / ".project" / "project.yaml"
        assert project_yaml.exists()

        content = project_yaml.read_text()
        assert "new-project" in content

    @pytest.mark.unit
    def test_writer_updates_existing_file(self, temp_dir: Path):
        """Writer updates existing .project/project.yaml."""
        from darnit.context.dot_project import DotProjectWriter

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: old-name
repositories:
  - https://github.com/org/repo
""")

        writer = DotProjectWriter(temp_dir)
        writer.update({"name": "new-name"})

        content = (project_dir / "project.yaml").read_text()
        assert "new-name" in content
        assert "old-name" not in content
        # repositories should still be present
        assert "https://github.com/org/repo" in content

    @pytest.mark.unit
    def test_writer_deep_updates_nested_fields(self, temp_dir: Path):
        """Writer performs deep updates on nested fields."""
        from darnit.context.dot_project import DotProjectWriter

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
security:
  threat_model:
    path: existing/threat-model.md
""")

        writer = DotProjectWriter(temp_dir)
        writer.update({"security": {"policy": {"path": "SECURITY.md"}}})

        content = (project_dir / "project.yaml").read_text()
        # New policy should be added
        assert "SECURITY.md" in content
        # Existing threat_model should be preserved
        assert "existing/threat-model.md" in content

    @pytest.mark.unit
    def test_writer_preserves_comments(self, temp_dir: Path):
        """Writer preserves YAML comments during updates."""
        from darnit.context.dot_project import DotProjectWriter

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""# Project configuration
# Generated by darnit

name: my-project  # The project name
repositories:
  # Main repository
  - https://github.com/org/repo
""")

        writer = DotProjectWriter(temp_dir)
        writer.update({"description": "A test project"})

        content = (project_dir / "project.yaml").read_text()
        # Comments should be preserved
        assert "# Project configuration" in content
        assert "# Generated by darnit" in content
        assert "# The project name" in content
        assert "# Main repository" in content
        # New field should be added
        assert "A test project" in content

    @pytest.mark.unit
    def test_set_security_policy_path(self, temp_dir: Path):
        """Convenience method sets security.policy.path."""
        from darnit.context.dot_project import DotProjectWriter

        writer = DotProjectWriter(temp_dir)
        writer.set_security_policy_path("SECURITY.md")

        content = (temp_dir / ".project" / "project.yaml").read_text()
        assert "security:" in content
        assert "policy:" in content
        assert "SECURITY.md" in content

    @pytest.mark.unit
    def test_set_codeowners_path(self, temp_dir: Path):
        """Convenience method sets governance.codeowners.path."""
        from darnit.context.dot_project import DotProjectWriter

        writer = DotProjectWriter(temp_dir)
        writer.set_codeowners_path(".github/CODEOWNERS")

        content = (temp_dir / ".project" / "project.yaml").read_text()
        assert "governance:" in content
        assert "codeowners:" in content
        assert ".github/CODEOWNERS" in content

    @pytest.mark.unit
    def test_set_contributing_path(self, temp_dir: Path):
        """Convenience method sets governance.contributing.path."""
        from darnit.context.dot_project import DotProjectWriter

        writer = DotProjectWriter(temp_dir)
        writer.set_contributing_path("CONTRIBUTING.md")

        content = (temp_dir / ".project" / "project.yaml").read_text()
        assert "governance:" in content
        assert "contributing:" in content
        assert "CONTRIBUTING.md" in content

    @pytest.mark.unit
    def test_writer_sets_schema_version_on_new_file(self, temp_dir: Path):
        """Writer sets schema_version when creating new file."""
        from darnit.context.dot_project import DOT_PROJECT_SPEC_VERSION, DotProjectWriter

        writer = DotProjectWriter(temp_dir)
        writer.update({"name": "new-project"})

        content = (temp_dir / ".project" / "project.yaml").read_text()
        assert "schema_version:" in content
        assert DOT_PROJECT_SPEC_VERSION in content


class TestDotProjectMapper:
    """Test the DotProjectMapper for context injection."""

    @pytest.mark.unit
    def test_mapper_returns_empty_context_when_no_file(self, temp_dir: Path):
        """Mapper returns empty dict when no .project/ exists."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert context == {}

    @pytest.mark.unit
    def test_mapper_maps_security_section(self, temp_dir: Path):
        """Mapper correctly maps security section to context variables."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy:
    path: SECURITY.md
  threat_model:
    path: docs/threat-model.md
""")

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert context.get("project.security.policy_path") == "SECURITY.md"
        assert context.get("project.security.threat_model_path") == "docs/threat-model.md"

    @pytest.mark.unit
    def test_mapper_maps_governance_section(self, temp_dir: Path):
        """Mapper correctly maps governance section to context variables."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
governance:
  contributing:
    path: CONTRIBUTING.md
  codeowners:
    path: .github/CODEOWNERS
""")

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert context.get("project.governance.contributing_path") == "CONTRIBUTING.md"
        assert context.get("project.governance.codeowners_path") == ".github/CODEOWNERS"

    @pytest.mark.unit
    def test_mapper_maps_maintainers(self, temp_dir: Path):
        """Mapper correctly maps maintainers list."""
        from darnit.context.dot_project_mapper import DotProjectMapper

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
""")
        (project_dir / "maintainers.yaml").write_text("""
- alice
- bob
""")

        mapper = DotProjectMapper(temp_dir)
        context = mapper.get_context()

        assert "alice" in context.get("project.maintainers", [])
        assert "bob" in context.get("project.maintainers", [])


class TestDotProjectInjection:
    """Test injection of .project/ context into CheckContext."""

    @pytest.mark.unit
    def test_inject_project_context(self, temp_dir: Path):
        """inject_project_context populates context.project_context."""
        from darnit.context.inject import inject_project_context
        from darnit.sieve.models import CheckContext

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy:
    path: SECURITY.md
""")

        context = CheckContext(
            owner="org",
            repo="repo",
            local_path=str(temp_dir),
            default_branch="main",
            control_id="TEST-01",
        )

        inject_project_context(context)

        assert context.project_context.get("project.security.policy_path") == "SECURITY.md"

    @pytest.mark.unit
    def test_create_check_context_with_project(self, temp_dir: Path):
        """create_check_context_with_project creates context with .project/ data."""
        from darnit.context.inject import create_check_context_with_project

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy:
    path: SECURITY.md
""")

        context = create_check_context_with_project(
            owner="org",
            repo="repo",
            local_path=str(temp_dir),
            default_branch="main",
            control_id="TEST-01",
        )

        assert context.project_context.get("project.security.policy_path") == "SECURITY.md"

    @pytest.mark.unit
    def test_get_project_value(self, temp_dir: Path):
        """get_project_value retrieves values from project_context."""
        from darnit.context.inject import get_project_value, inject_project_context
        from darnit.sieve.models import CheckContext

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy:
    path: SECURITY.md
""")

        context = CheckContext(
            owner="org",
            repo="repo",
            local_path=str(temp_dir),
            default_branch="main",
            control_id="TEST-01",
        )
        inject_project_context(context)

        assert get_project_value(context, "project.security.policy_path") == "SECURITY.md"
        assert get_project_value(context, "nonexistent", "default") == "default"

    @pytest.mark.unit
    def test_has_project_value(self, temp_dir: Path):
        """has_project_value checks if key exists in project_context."""
        from darnit.context.inject import has_project_value, inject_project_context
        from darnit.sieve.models import CheckContext

        project_dir = temp_dir / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("""
name: my-project
repositories:
  - https://github.com/org/repo
security:
  policy:
    path: SECURITY.md
""")

        context = CheckContext(
            owner="org",
            repo="repo",
            local_path=str(temp_dir),
            default_branch="main",
            control_id="TEST-01",
        )
        inject_project_context(context)

        assert has_project_value(context, "project.security.policy_path") is True
        assert has_project_value(context, "nonexistent") is False


class TestDotProjectIntegration:
    """Integration tests for .project/ functionality (Task 1.5.4)."""

    @pytest.mark.integration
    def test_full_read_write_cycle(self, temp_dir: Path):
        """Test complete read-write-read cycle with .project/ file."""
        from darnit.context.dot_project import DotProjectReader, DotProjectWriter

        # Initial write
        writer = DotProjectWriter(temp_dir)
        writer.update({
            "name": "integration-test",
            "repositories": ["https://github.com/org/repo"],
        })
        writer.set_security_policy_path("SECURITY.md")
        writer.set_codeowners_path(".github/CODEOWNERS")

        # Read back
        reader = DotProjectReader(temp_dir)
        config = reader.read()

        assert config.name == "integration-test"
        assert len(config.repositories) == 1
        assert config.security.policy.path == "SECURITY.md"
        assert config.governance.codeowners.path == ".github/CODEOWNERS"

        # Update
        writer.update({
            "description": "Added description",
            "security": {"threat_model": {"path": "docs/threat-model.md"}},
        })

        # Read again
        config = reader.read()

        assert config.description == "Added description"
        # Original security.policy should still be there
        assert config.security.policy.path == "SECURITY.md"
        # New threat_model should be added
        assert config.security.threat_model.path == "docs/threat-model.md"

    @pytest.mark.integration
    def test_real_cncf_project_structure(self, temp_dir: Path):
        """Test parsing a realistic CNCF .project/ structure."""
        from darnit.context.dot_project import DotProjectReader

        project_dir = temp_dir / ".project"
        project_dir.mkdir()

        # Create a realistic CNCF project.yaml
        (project_dir / "project.yaml").write_text("""
# CNCF Project Configuration
# See: https://github.com/cncf/automation/tree/main/utilities/dot-project

name: my-cncf-project
description: A sample CNCF project demonstrating .project/ structure
schema_version: "1.0.0"
type: software

repositories:
  - https://github.com/cncf/my-project
  - https://github.com/cncf/my-project-website

website: https://my-project.io
artwork: https://my-project.io/images/logo.svg

mailing_lists:
  - my-project@lists.cncf.io
  - my-project-security@lists.cncf.io

social:
  slack: https://cloud-native.slack.com/channels/my-project
  twitter: "@myproject"
  linkedin: https://linkedin.com/company/myproject

security:
  policy:
    path: SECURITY.md
  threat_model:
    path: docs/security/threat-model.md

governance:
  contributing:
    path: CONTRIBUTING.md
  codeowners:
    path: .github/CODEOWNERS
  governance_doc:
    path: GOVERNANCE.md

legal:
  license:
    path: LICENSE

documentation:
  readme:
    path: README.md
  support:
    path: SUPPORT.md
  architecture:
    path: docs/architecture.md
  api:
    path: docs/api-reference.md

maturity_log:
  - phase: sandbox
    date: "2023-06-01"
    issue: https://github.com/cncf/toc/issues/1234
  - phase: incubating
    date: "2024-01-15"
    issue: https://github.com/cncf/toc/issues/1567

audits:
  - date: "2024-02-01"
    url: https://example.com/audits/my-project-2024
    type: security

extensions:
  darnit:
    metadata:
      version: "1.0.0"
    config:
      target_level: 2
      skip_controls:
        - OSPS-AC-01.02
""")

        # Create maintainers.yaml
        (project_dir / "maintainers.yaml").write_text("""
# Project Maintainers
project-maintainers:
  - handle: alice
    name: Alice Smith
    company: CNCF
  - handle: bob
    name: Bob Jones
    company: CNCF
""")

        reader = DotProjectReader(temp_dir)
        config = reader.read()

        # Verify all sections parsed correctly
        assert config.name == "my-cncf-project"
        assert config.schema_version == "1.0.0"
        assert len(config.repositories) == 2
        assert config.website == "https://my-project.io"

        # Security
        assert config.security.policy.path == "SECURITY.md"
        assert config.security.threat_model.path == "docs/security/threat-model.md"

        # Governance
        assert config.governance.contributing.path == "CONTRIBUTING.md"
        assert config.governance.codeowners.path == ".github/CODEOWNERS"

        # Documentation
        assert config.documentation.readme.path == "README.md"
        assert config.documentation.architecture.path == "docs/architecture.md"

        # Maturity log
        assert len(config.maturity_log) == 2
        assert config.maturity_log[0].phase == "sandbox"
        assert config.maturity_log[1].phase == "incubating"

        # Audits
        assert len(config.audits) == 1
        assert config.audits[0].type == "security"

        # Extensions
        assert "darnit" in config.extensions
        assert config.extensions["darnit"].config["target_level"] == 2

        # Maintainers
        assert "alice" in config.maintainers
        assert "bob" in config.maintainers

        # Validation
        is_valid, missing = config.is_valid()
        assert is_valid is True

    @pytest.mark.integration
    def test_context_injection_end_to_end(self, temp_dir: Path):
        """Test complete flow from .project/ file to CheckContext."""
        from darnit.context.dot_project import DotProjectWriter
        from darnit.context.inject import (
            create_check_context_with_project,
            get_project_value,
            has_project_value,
        )

        # Create .project/ via writer
        writer = DotProjectWriter(temp_dir)
        writer.update({
            "name": "e2e-test",
            "repositories": ["https://github.com/org/repo"],
            "security": {
                "policy": {"path": "SECURITY.md"},
            },
            "governance": {
                "codeowners": {"path": ".github/CODEOWNERS"},
                "contributing": {"path": "CONTRIBUTING.md"},
            },
        })

        # Create maintainers.yaml
        project_dir = temp_dir / ".project"
        (project_dir / "maintainers.yaml").write_text("""
- alice
- bob
""")

        # Create CheckContext with injected .project/ data
        context = create_check_context_with_project(
            owner="org",
            repo="repo",
            local_path=str(temp_dir),
            default_branch="main",
            control_id="TEST-01",
        )

        # Verify all context variables
        assert has_project_value(context, "project.security.policy_path")
        assert get_project_value(context, "project.security.policy_path") == "SECURITY.md"

        assert has_project_value(context, "project.governance.codeowners_path")
        assert get_project_value(context, "project.governance.codeowners_path") == ".github/CODEOWNERS"

        assert has_project_value(context, "project.maintainers")
        maintainers = get_project_value(context, "project.maintainers")
        assert "alice" in maintainers
        assert "bob" in maintainers
