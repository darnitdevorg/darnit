"""CNCF .project/ specification reader and writer.

This module implements reading and writing of .project/project.yaml files
following the CNCF .project/ specification.

Specification: https://github.com/cncf/automation/tree/main/utilities/dot-project
Targeted Spec Version: 1.1.0 (based on types.go as of 2026-02)

The reader is tolerant of unknown fields for forward compatibility with
spec evolution. Required fields are validated per the CNCF types.go struct.

Example:
    from darnit.context.dot_project import DotProjectReader, DotProjectWriter

    # Read project metadata
    reader = DotProjectReader("/path/to/repo")
    if reader.exists():
        config = reader.read()
        print(config.name)
        print(config.maintainers)

    # Write updates (preserving comments)
    writer = DotProjectWriter("/path/to/repo")
    writer.update({"security": {"policy": {"path": "SECURITY.md"}}})
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Targeted .project/ spec version
# Based on cncf/automation types.go
# Update this when we verify compatibility with newer spec versions
DOT_PROJECT_SPEC_VERSION = "1.1.0"
DOT_PROJECT_SPEC_URL = "https://github.com/cncf/automation/tree/main/utilities/dot-project"


@dataclass
class FileReference:
    """Reference to a file path within the repository."""

    path: str


@dataclass
class MaintainerEntry:
    """Individual maintainer with optional structured fields.

    Supports both simple handles and the CNCF structured format
    with handle, email, role, and title.
    """

    handle: str = ""
    email: str = ""
    role: str = ""
    title: str = ""
    name: str = ""

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MaintainerTeam:
    """Team-based maintainer grouping from CNCF teams format.

    Used in maintainers.yaml with the structure:
    teams:
      - name: "maintainers"
        members:
          - handle: "@alice"
            email: "alice@example.com"
    """

    name: str = ""
    members: list[MaintainerEntry] = field(default_factory=list)

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MaintainerLifecycle:
    """Maintainer lifecycle configuration."""

    onboarding_doc: FileReference | None = None
    progression_ladder: FileReference | None = None
    offboarding_policy: FileReference | None = None
    mentoring_program: list[str] = field(default_factory=list)

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class IdentityType:
    """Identity/contributor agreement type configuration."""

    has_dco: bool = False
    has_cla: bool = False
    dco_url: FileReference | None = None
    cla_url: FileReference | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LandscapeConfig:
    """CNCF Landscape placement configuration."""

    category: str = ""
    subcategory: str = ""

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityContact:
    """Security contact information.

    Supports both the CNCF struct format (email + advisory_url)
    and the legacy plain-string format for backward compatibility.
    """

    email: str = ""
    advisory_url: str = ""

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityConfig:
    """Security section of .project/project.yaml."""

    policy: FileReference | None = None
    threat_model: FileReference | None = None
    contact: SecurityContact | str | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class GovernanceConfig:
    """Governance section of .project/project.yaml."""

    contributing: FileReference | None = None
    codeowners: FileReference | None = None
    governance_doc: FileReference | None = None
    gitvote_config: FileReference | None = None
    vendor_neutrality_statement: FileReference | None = None
    decision_making_process: FileReference | None = None
    roles_and_teams: FileReference | None = None
    code_of_conduct: FileReference | None = None
    sub_project_list: FileReference | None = None
    sub_project_docs: FileReference | None = None
    contributor_ladder: FileReference | None = None
    change_process: FileReference | None = None
    comms_channels: FileReference | None = None
    community_calendar: FileReference | None = None
    contributor_guide: FileReference | None = None
    maintainer_lifecycle: MaintainerLifecycle | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LegalConfig:
    """Legal section of .project/project.yaml."""

    license: FileReference | None = None
    identity_type: IdentityType | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentationConfig:
    """Documentation section of .project/project.yaml."""

    readme: FileReference | None = None
    support: FileReference | None = None
    architecture: FileReference | None = None
    api: FileReference | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Audit:
    """Audit record in .project/project.yaml."""

    date: str | None = None
    url: str | None = None
    type: str | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MaturityEntry:
    """Maturity log entry in .project/project.yaml."""

    phase: str | None = None
    date: str | None = None
    issue: str | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtensionConfig:
    """Extension configuration for third-party tools."""

    metadata: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectConfig:
    """Complete .project/project.yaml configuration.

    This dataclass maps to the CNCF .project/ specification types.go struct.
    All fields except name and repositories are optional.
    Unknown fields are preserved in _extra for forward compatibility.
    """

    # Required fields
    name: str = ""
    repositories: list[str] = field(default_factory=list)

    # Optional core fields
    description: str = ""
    schema_version: str = ""
    type: str = ""
    slug: str = ""
    project_lead: str = ""
    cncf_slack_channel: str = ""
    website: str = ""
    artwork: str = ""

    # Optional file reference fields
    adopters: FileReference | None = None

    # Optional list fields
    mailing_lists: list[str] = field(default_factory=list)
    maturity_log: list[MaturityEntry] = field(default_factory=list)
    audits: list[Audit] = field(default_factory=list)

    # Optional map fields
    social: dict[str, str] = field(default_factory=dict)
    package_managers: dict[str, str] = field(default_factory=dict)

    # Optional structured sections
    security: SecurityConfig | None = None
    governance: GovernanceConfig | None = None
    legal: LegalConfig | None = None
    documentation: DocumentationConfig | None = None
    landscape: LandscapeConfig | None = None

    # Extensions (PR #131)
    extensions: dict[str, ExtensionConfig] = field(default_factory=dict)

    # Maintainers (from project.yaml or maintainers.yaml)
    maintainers: list[str] = field(default_factory=list)

    # Structured maintainer data (teams format from CNCF)
    maintainer_teams: list[MaintainerTeam] = field(default_factory=list)
    maintainer_entries: list[MaintainerEntry] = field(default_factory=list)
    maintainer_org: str = ""
    maintainer_project_id: str = ""

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)

    # Track source file for write-back
    _source_path: Path | None = None

    def is_valid(self) -> tuple[bool, list[str]]:
        """Check if required fields are present.

        Returns:
            Tuple of (is_valid, list of missing field names)
        """
        missing = []
        if not self.name:
            missing.append("name")
        if not self.repositories:
            missing.append("repositories")
        return len(missing) == 0, missing


class DotProjectReader:
    """Reader for .project/ directory files.

    Implements tolerant parsing that preserves unknown fields for
    forward compatibility with spec evolution.
    """

    def __init__(self, repo_path: str | Path):
        """Initialize reader with repository path.

        Args:
            repo_path: Path to the repository root
        """
        self.repo_path = Path(repo_path)
        self.project_dir = self.repo_path / ".project"
        self.project_yaml = self.project_dir / "project.yaml"
        self.maintainers_yaml = self.project_dir / "maintainers.yaml"

    def exists(self) -> bool:
        """Check if .project/project.yaml exists."""
        return self.project_yaml.exists()

    def read(self) -> ProjectConfig:
        """Read and parse .project/project.yaml.

        Returns:
            ProjectConfig with parsed data, or empty config if file doesn't exist

        Raises:
            ValueError: If YAML parsing fails
        """
        if not self.exists():
            logger.debug("No .project/project.yaml found at %s", self.repo_path)
            return ProjectConfig()

        try:
            # Use ruamel.yaml for round-trip preservation
            from ruamel.yaml import YAML

            yaml = YAML()
            yaml.preserve_quotes = True

            with open(self.project_yaml) as f:
                data = yaml.load(f)

            if data is None:
                data = {}

            config = self._parse_config(data)
            config._source_path = self.project_yaml

            # Also check for maintainers.yaml
            if self.maintainers_yaml.exists():
                self._read_maintainers_into(config)

            # Validate and log warnings for missing required fields
            is_valid, missing = config.is_valid()
            if not is_valid:
                logger.warning(
                    ".project/project.yaml missing required fields: %s",
                    ", ".join(missing),
                )

            return config

        except ImportError:
            logger.error("ruamel.yaml not installed. Install with: pip install ruamel.yaml")
            raise
        except Exception as e:
            logger.error("Failed to parse .project/project.yaml: %s", e)
            raise ValueError(f"Failed to parse .project/project.yaml: {e}") from e

    def _read_maintainers_into(self, config: ProjectConfig) -> None:
        """Read maintainers from maintainers.yaml into config.

        Populates both the flat maintainers list (handles) and structured
        fields (maintainer_entries, maintainer_teams, maintainer_org,
        maintainer_project_id) when available.
        """
        try:
            from ruamel.yaml import YAML

            yaml = YAML()
            with open(self.maintainers_yaml) as f:
                data = yaml.load(f)

            if data is None:
                return

            # Format 1: Plain list of strings or dicts
            if isinstance(data, list):
                handles, entries = self._extract_maintainer_entries(data)
                if handles:
                    config.maintainers = handles
                if entries:
                    config.maintainer_entries = entries
                return

            if not isinstance(data, dict):
                return

            # Format 2: CNCF teams-based format
            # {project_id, org, teams: [{name, members: [{handle, ...}]}]}
            if "teams" in data:
                config.maintainer_project_id = str(data.get("project_id", ""))
                config.maintainer_org = str(data.get("org", ""))
                teams = self._parse_maintainer_teams(data["teams"])
                config.maintainer_teams = teams
                # Also flatten to handles list for backward compat
                all_handles = []
                all_entries = []
                for team in teams:
                    for member in team.members:
                        if member.handle and member.handle not in all_handles:
                            all_handles.append(member.handle)
                        all_entries.append(member)
                if all_handles:
                    config.maintainers = all_handles
                if all_entries:
                    config.maintainer_entries = all_entries
                return

            # Format 3: Dict with nested maintainers list
            if "maintainers" in data:
                handles, entries = self._extract_maintainer_entries(data["maintainers"])
                if handles:
                    config.maintainers = handles
                if entries:
                    config.maintainer_entries = entries
                return
            if "project-maintainers" in data:
                handles, entries = self._extract_maintainer_entries(
                    data["project-maintainers"]
                )
                if handles:
                    config.maintainers = handles
                if entries:
                    config.maintainer_entries = entries
                return

        except Exception as e:
            logger.warning("Failed to read maintainers.yaml: %s", e)

    def _extract_maintainer_entries(
        self, data: Any
    ) -> tuple[list[str], list[MaintainerEntry]]:
        """Extract maintainer handles and entries from a list.

        Returns:
            Tuple of (flat handles list, structured entries list)
        """
        handles: list[str] = []
        entries: list[MaintainerEntry] = []
        if not isinstance(data, list):
            return handles, entries

        for item in data:
            if isinstance(item, str):
                handle = self._normalize_handle(item)
                handles.append(handle)
                entries.append(MaintainerEntry(handle=handle))
            elif isinstance(item, dict):
                entry = self._parse_maintainer_entry(item)
                if entry.handle:
                    handles.append(entry.handle)
                entries.append(entry)
        return handles, entries

    def _parse_maintainer_entry(self, data: dict[str, Any]) -> MaintainerEntry:
        """Parse a single maintainer entry from a dict."""
        known = {"handle", "email", "role", "title", "name", "github"}
        handle = data.get("handle", "") or data.get("github", "")
        entry = MaintainerEntry(
            handle=self._normalize_handle(handle) if handle else "",
            email=data.get("email", ""),
            role=data.get("role", ""),
            title=data.get("title", ""),
            name=data.get("name", ""),
        )
        for key, value in data.items():
            if key not in known:
                entry._extra[key] = value
        return entry

    def _parse_maintainer_teams(self, data: list) -> list[MaintainerTeam]:
        """Parse teams array from CNCF teams-based maintainers format."""
        teams: list[MaintainerTeam] = []
        for team_data in data:
            if not isinstance(team_data, dict):
                continue
            known = {"name", "members"}
            members: list[MaintainerEntry] = []
            for member_data in team_data.get("members", []):
                if isinstance(member_data, dict):
                    members.append(self._parse_maintainer_entry(member_data))
                elif isinstance(member_data, str):
                    handle = self._normalize_handle(member_data)
                    members.append(MaintainerEntry(handle=handle))
            team = MaintainerTeam(
                name=team_data.get("name", ""),
                members=members,
            )
            for key, value in team_data.items():
                if key not in known:
                    team._extra[key] = value
            teams.append(team)
        return teams

    def _normalize_handle(self, handle: str) -> str:
        """Normalize a maintainer handle (strip @ and whitespace)."""
        return handle.strip().lstrip("@")

    def _parse_config(self, data: dict[str, Any]) -> ProjectConfig:
        """Parse raw YAML data into ProjectConfig."""
        config = ProjectConfig()

        # Known fields
        known_fields = {
            "name",
            "description",
            "schema_version",
            "type",
            "slug",
            "project_lead",
            "cncf_slack_channel",
            "website",
            "artwork",
            "repositories",
            "mailing_lists",
            "social",
            "package_managers",
            "maturity_log",
            "audits",
            "security",
            "governance",
            "legal",
            "documentation",
            "landscape",
            "adopters",
            "extensions",
        }

        # Parse known fields
        config.name = data.get("name", "")
        config.description = data.get("description", "")
        config.schema_version = data.get("schema_version", "")
        config.type = data.get("type", "")
        config.slug = data.get("slug", "")
        config.project_lead = data.get("project_lead", "")
        config.cncf_slack_channel = data.get("cncf_slack_channel", "")
        config.website = data.get("website", "")
        config.artwork = data.get("artwork", "")
        config.repositories = data.get("repositories", [])
        config.mailing_lists = data.get("mailing_lists", [])
        config.social = data.get("social", {})
        config.package_managers = data.get("package_managers", {})

        # Parse adopters file reference
        if "adopters" in data:
            config.adopters = self._parse_file_reference(data["adopters"])

        # Parse maturity log
        if "maturity_log" in data:
            config.maturity_log = [
                self._parse_maturity_entry(entry) for entry in data["maturity_log"]
            ]

        # Parse audits
        if "audits" in data:
            config.audits = [self._parse_audit(entry) for entry in data["audits"]]

        # Parse structured sections
        if "security" in data:
            config.security = self._parse_security(data["security"])

        if "governance" in data:
            config.governance = self._parse_governance(data["governance"])

        if "legal" in data:
            config.legal = self._parse_legal(data["legal"])

        if "documentation" in data:
            config.documentation = self._parse_documentation(data["documentation"])

        if "landscape" in data:
            config.landscape = self._parse_landscape(data["landscape"])

        # Parse extensions
        if "extensions" in data:
            config.extensions = self._parse_extensions(data["extensions"])

        # Preserve unknown fields
        for key, value in data.items():
            if key not in known_fields:
                config._extra[key] = value
                logger.debug("Preserving unknown .project field: %s", key)

        return config

    def _parse_file_reference(self, data: Any) -> FileReference | None:
        """Parse a file reference from various formats."""
        if data is None:
            return None
        if isinstance(data, str):
            return FileReference(path=data)
        if isinstance(data, dict) and "path" in data:
            return FileReference(path=data["path"])
        return None

    def _parse_security(self, data: dict[str, Any]) -> SecurityConfig:
        """Parse security section."""
        known = {"policy", "threat_model", "contact"}
        config = SecurityConfig(
            policy=self._parse_file_reference(data.get("policy")),
            threat_model=self._parse_file_reference(data.get("threat_model")),
            contact=self._parse_security_contact(data.get("contact")),
        )
        for key, value in data.items():
            if key not in known:
                config._extra[key] = value
        return config

    def _parse_security_contact(self, data: Any) -> SecurityContact | str | None:
        """Parse security contact from various formats.

        Supports:
        - Plain string: "security@example.com"
        - CNCF struct: {email: "...", advisory_url: "..."}
        """
        if data is None:
            return None
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            known = {"email", "advisory_url"}
            contact = SecurityContact(
                email=data.get("email", ""),
                advisory_url=data.get("advisory_url", ""),
            )
            for key, value in data.items():
                if key not in known:
                    contact._extra[key] = value
            return contact
        return None

    def _parse_governance(self, data: dict[str, Any]) -> GovernanceConfig:
        """Parse governance section."""
        known = {
            "contributing",
            "codeowners",
            "governance_doc",
            "gitvote_config",
            "vendor_neutrality_statement",
            "decision_making_process",
            "roles_and_teams",
            "code_of_conduct",
            "sub_project_list",
            "sub_project_docs",
            "contributor_ladder",
            "change_process",
            "comms_channels",
            "community_calendar",
            "contributor_guide",
            "maintainer_lifecycle",
        }
        config = GovernanceConfig(
            contributing=self._parse_file_reference(data.get("contributing")),
            codeowners=self._parse_file_reference(data.get("codeowners")),
            governance_doc=self._parse_file_reference(data.get("governance_doc")),
            gitvote_config=self._parse_file_reference(data.get("gitvote_config")),
            vendor_neutrality_statement=self._parse_file_reference(
                data.get("vendor_neutrality_statement")
            ),
            decision_making_process=self._parse_file_reference(
                data.get("decision_making_process")
            ),
            roles_and_teams=self._parse_file_reference(data.get("roles_and_teams")),
            code_of_conduct=self._parse_file_reference(data.get("code_of_conduct")),
            sub_project_list=self._parse_file_reference(data.get("sub_project_list")),
            sub_project_docs=self._parse_file_reference(data.get("sub_project_docs")),
            contributor_ladder=self._parse_file_reference(data.get("contributor_ladder")),
            change_process=self._parse_file_reference(data.get("change_process")),
            comms_channels=self._parse_file_reference(data.get("comms_channels")),
            community_calendar=self._parse_file_reference(data.get("community_calendar")),
            contributor_guide=self._parse_file_reference(data.get("contributor_guide")),
        )

        # Parse nested maintainer_lifecycle
        if "maintainer_lifecycle" in data and isinstance(data["maintainer_lifecycle"], dict):
            config.maintainer_lifecycle = self._parse_maintainer_lifecycle(
                data["maintainer_lifecycle"]
            )

        for key, value in data.items():
            if key not in known:
                config._extra[key] = value
        return config

    def _parse_legal(self, data: dict[str, Any]) -> LegalConfig:
        """Parse legal section."""
        known = {"license", "identity_type"}
        config = LegalConfig(
            license=self._parse_file_reference(data.get("license")),
        )

        # Parse nested identity_type
        if "identity_type" in data and isinstance(data["identity_type"], dict):
            config.identity_type = self._parse_identity_type(data["identity_type"])

        for key, value in data.items():
            if key not in known:
                config._extra[key] = value
        return config

    def _parse_documentation(self, data: dict[str, Any]) -> DocumentationConfig:
        """Parse documentation section."""
        known = {"readme", "support", "architecture", "api"}
        config = DocumentationConfig(
            readme=self._parse_file_reference(data.get("readme")),
            support=self._parse_file_reference(data.get("support")),
            architecture=self._parse_file_reference(data.get("architecture")),
            api=self._parse_file_reference(data.get("api")),
        )
        for key, value in data.items():
            if key not in known:
                config._extra[key] = value
        return config

    def _parse_extensions(self, data: dict[str, Any]) -> dict[str, ExtensionConfig]:
        """Parse extensions section."""
        extensions = {}
        for name, ext_data in data.items():
            if isinstance(ext_data, dict):
                extensions[name] = ExtensionConfig(
                    metadata=ext_data.get("metadata", {}),
                    config=ext_data.get("config", {}),
                )
        return extensions

    def _parse_maturity_entry(self, data: dict[str, Any]) -> MaturityEntry:
        """Parse a maturity log entry."""
        known = {"phase", "date", "issue"}
        entry = MaturityEntry(
            phase=data.get("phase"),
            date=data.get("date"),
            issue=data.get("issue"),
        )
        for key, value in data.items():
            if key not in known:
                entry._extra[key] = value
        return entry

    def _parse_maintainer_lifecycle(self, data: dict[str, Any]) -> MaintainerLifecycle:
        """Parse maintainer lifecycle nested struct."""
        known = {"onboarding_doc", "progression_ladder", "offboarding_policy", "mentoring_program"}
        lifecycle = MaintainerLifecycle(
            onboarding_doc=self._parse_file_reference(data.get("onboarding_doc")),
            progression_ladder=self._parse_file_reference(data.get("progression_ladder")),
            offboarding_policy=self._parse_file_reference(data.get("offboarding_policy")),
            mentoring_program=data.get("mentoring_program", []),
        )
        for key, value in data.items():
            if key not in known:
                lifecycle._extra[key] = value
        return lifecycle

    def _parse_identity_type(self, data: dict[str, Any]) -> IdentityType:
        """Parse identity type nested struct."""
        known = {"has_dco", "has_cla", "dco_url", "cla_url"}
        identity = IdentityType(
            has_dco=bool(data.get("has_dco", False)),
            has_cla=bool(data.get("has_cla", False)),
            dco_url=self._parse_file_reference(data.get("dco_url")),
            cla_url=self._parse_file_reference(data.get("cla_url")),
        )
        for key, value in data.items():
            if key not in known:
                identity._extra[key] = value
        return identity

    def _parse_landscape(self, data: dict[str, Any]) -> LandscapeConfig:
        """Parse landscape nested struct."""
        known = {"category", "subcategory"}
        landscape = LandscapeConfig(
            category=data.get("category", ""),
            subcategory=data.get("subcategory", ""),
        )
        for key, value in data.items():
            if key not in known:
                landscape._extra[key] = value
        return landscape

    def _parse_audit(self, data: dict[str, Any]) -> Audit:
        """Parse an audit entry."""
        known = {"date", "url", "type"}
        audit = Audit(
            date=data.get("date"),
            url=data.get("url"),
            type=data.get("type"),
        )
        for key, value in data.items():
            if key not in known:
                audit._extra[key] = value
        return audit


class DotProjectWriter:
    """Writer for .project/ directory files.

    Implements comment-preserving YAML writing using ruamel.yaml's
    round-trip capabilities.
    """

    def __init__(self, repo_path: str | Path):
        """Initialize writer with repository path.

        Args:
            repo_path: Path to the repository root
        """
        self.repo_path = Path(repo_path)
        self.project_dir = self.repo_path / ".project"
        self.project_yaml = self.project_dir / "project.yaml"

    def update(self, updates: dict[str, Any]) -> None:
        """Update .project/project.yaml with new values.

        This method preserves existing content and comments while
        applying the specified updates.

        Args:
            updates: Dictionary of updates to apply (nested paths supported)

        Example:
            writer.update({"security": {"policy": {"path": "SECURITY.md"}}})
        """
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)

        # Read existing content or create new
        if self.project_yaml.exists():
            with open(self.project_yaml) as f:
                data = yaml.load(f)
            if data is None:
                data = {}
        else:
            # Create directory and new file
            self.project_dir.mkdir(parents=True, exist_ok=True)
            data = {"schema_version": DOT_PROJECT_SPEC_VERSION}

        # Apply updates recursively
        self._deep_update(data, updates)

        # Write back
        with open(self.project_yaml, "w") as f:
            yaml.dump(data, f)

        logger.info("Updated .project/project.yaml")

    def _deep_update(self, target: dict, updates: dict) -> None:
        """Recursively update nested dictionaries."""
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def set_security_policy_path(self, path: str) -> None:
        """Convenience method to set security.policy.path."""
        self.update({"security": {"policy": {"path": path}}})

    def set_codeowners_path(self, path: str) -> None:
        """Convenience method to set governance.codeowners.path."""
        self.update({"governance": {"codeowners": {"path": path}}})

    def set_contributing_path(self, path: str) -> None:
        """Convenience method to set governance.contributing.path."""
        self.update({"governance": {"contributing": {"path": path}}})
