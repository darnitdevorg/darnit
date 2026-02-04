"""CNCF .project/ specification reader and writer.

This module implements reading and writing of .project/project.yaml files
following the CNCF .project/ specification.

Specification: https://github.com/cncf/automation/tree/main/utilities/dot-project
Targeted Spec Version: 1.0.0 (based on types.go as of 2024-01)

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
DOT_PROJECT_SPEC_VERSION = "1.0.0"
DOT_PROJECT_SPEC_URL = "https://github.com/cncf/automation/tree/main/utilities/dot-project"


@dataclass
class FileReference:
    """Reference to a file path within the repository."""

    path: str


@dataclass
class SecurityConfig:
    """Security section of .project/project.yaml."""

    policy: FileReference | None = None
    threat_model: FileReference | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class GovernanceConfig:
    """Governance section of .project/project.yaml."""

    contributing: FileReference | None = None
    codeowners: FileReference | None = None
    governance_doc: FileReference | None = None

    # Allow unknown fields for forward compatibility
    _extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LegalConfig:
    """Legal section of .project/project.yaml."""

    license: FileReference | None = None

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
    website: str = ""
    artwork: str = ""

    # Optional list fields
    mailing_lists: list[str] = field(default_factory=list)
    maturity_log: list[MaturityEntry] = field(default_factory=list)
    audits: list[Audit] = field(default_factory=list)

    # Optional map fields
    social: dict[str, str] = field(default_factory=dict)

    # Optional structured sections
    security: SecurityConfig | None = None
    governance: GovernanceConfig | None = None
    legal: LegalConfig | None = None
    documentation: DocumentationConfig | None = None

    # Extensions (PR #131)
    extensions: dict[str, ExtensionConfig] = field(default_factory=dict)

    # Maintainers (from project.yaml or maintainers.yaml)
    maintainers: list[str] = field(default_factory=list)

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
                maintainers = self._read_maintainers()
                if maintainers:
                    config.maintainers = maintainers

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

    def _read_maintainers(self) -> list[str]:
        """Read maintainers from maintainers.yaml."""
        try:
            from ruamel.yaml import YAML

            yaml = YAML()
            with open(self.maintainers_yaml) as f:
                data = yaml.load(f)

            if data is None:
                return []

            # Extract maintainer handles from various formats
            maintainers = []
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, str):
                        maintainers.append(self._normalize_handle(entry))
                    elif isinstance(entry, dict) and "handle" in entry:
                        maintainers.append(self._normalize_handle(entry["handle"]))
            elif isinstance(data, dict):
                # Check for nested maintainers list
                if "maintainers" in data:
                    return self._extract_maintainers(data["maintainers"])
                if "project-maintainers" in data:
                    return self._extract_maintainers(data["project-maintainers"])

            return maintainers

        except Exception as e:
            logger.warning("Failed to read maintainers.yaml: %s", e)
            return []

    def _extract_maintainers(self, data: Any) -> list[str]:
        """Extract maintainer handles from various data structures."""
        if isinstance(data, list):
            maintainers = []
            for entry in data:
                if isinstance(entry, str):
                    maintainers.append(self._normalize_handle(entry))
                elif isinstance(entry, dict):
                    if "handle" in entry:
                        maintainers.append(self._normalize_handle(entry["handle"]))
                    elif "github" in entry:
                        maintainers.append(self._normalize_handle(entry["github"]))
            return maintainers
        return []

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
            "website",
            "artwork",
            "repositories",
            "mailing_lists",
            "social",
            "maturity_log",
            "audits",
            "security",
            "governance",
            "legal",
            "documentation",
            "extensions",
        }

        # Parse known fields
        config.name = data.get("name", "")
        config.description = data.get("description", "")
        config.schema_version = data.get("schema_version", "")
        config.type = data.get("type", "")
        config.website = data.get("website", "")
        config.artwork = data.get("artwork", "")
        config.repositories = data.get("repositories", [])
        config.mailing_lists = data.get("mailing_lists", [])
        config.social = data.get("social", {})

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
        known = {"policy", "threat_model"}
        config = SecurityConfig(
            policy=self._parse_file_reference(data.get("policy")),
            threat_model=self._parse_file_reference(data.get("threat_model")),
        )
        for key, value in data.items():
            if key not in known:
                config._extra[key] = value
        return config

    def _parse_governance(self, data: dict[str, Any]) -> GovernanceConfig:
        """Parse governance section."""
        known = {"contributing", "codeowners", "governance_doc"}
        config = GovernanceConfig(
            contributing=self._parse_file_reference(data.get("contributing")),
            codeowners=self._parse_file_reference(data.get("codeowners")),
            governance_doc=self._parse_file_reference(data.get("governance_doc")),
        )
        for key, value in data.items():
            if key not in known:
                config._extra[key] = value
        return config

    def _parse_legal(self, data: dict[str, Any]) -> LegalConfig:
        """Parse legal section."""
        known = {"license"}
        config = LegalConfig(
            license=self._parse_file_reference(data.get("license")),
        )
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
