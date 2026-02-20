"""Context schema models for interactive context collection.

This module defines Pydantic models for:
- Context values with provenance tracking (source, timestamp)
- Context definitions from TOML framework files
- Context prompt requests for user input during audits

These models support the Interactive Context Collection System
as designed in docs/design/CONTEXT_PROMPTS.md.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContextSource(str, Enum):
    """Source/provenance of a context value.

    Indicates how a context value was obtained:
    - user_confirmed: Explicitly set by user via MCP tool
    - auto_detected: Automatically detected from repo structure
    - file_reference: Points to a file containing the information
    - default: Default value when no other source available
    """

    USER_CONFIRMED = "user_confirmed"
    AUTO_DETECTED = "auto_detected"
    FILE_REFERENCE = "file_reference"
    DEFAULT = "default"


class ContextType(str, Enum):
    """Supported context value types.

    Used in TOML [context] definitions to specify validation:
    - boolean: Yes/No question (true/false)
    - string: Free text (non-empty)
    - enum: One of predefined values
    - list: Multiple string values
    - path: File path (optionally must exist)
    - list_or_path: Either list or path
    - email: Email address (RFC 5322)
    - url: Valid URL
    """

    BOOLEAN = "boolean"
    STRING = "string"
    ENUM = "enum"
    LIST = "list"
    PATH = "path"
    LIST_OR_PATH = "list_or_path"
    EMAIL = "email"
    URL = "url"


class ContextValue(BaseModel):
    """A context value with provenance tracking.

    Wraps any context value with metadata about:
    - How it was obtained (source)
    - When it was set/detected (timestamps)
    - How reliable it is (confidence)

    Example:
        >>> value = ContextValue(
        ...     source=ContextSource.USER_CONFIRMED,
        ...     value=["@mlieberman85"],
        ...     confirmed_at=datetime.now(),
        ...     confidence=1.0
        ... )
    """

    model_config = ConfigDict(use_enum_values=True)

    source: ContextSource
    value: Any
    confirmed_at: datetime | None = None
    detected_at: datetime | None = None
    detection_method: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @classmethod
    def user_confirmed(
        cls, value: Any, confirmed_at: datetime | None = None
    ) -> "ContextValue":
        """Create a user-confirmed context value."""
        return cls(
            source=ContextSource.USER_CONFIRMED,
            value=value,
            confirmed_at=confirmed_at or datetime.now(),
            confidence=1.0,
        )

    @classmethod
    def auto_detected(
        cls,
        value: Any,
        method: str,
        confidence: float = 0.8,
        detected_at: datetime | None = None,
    ) -> "ContextValue":
        """Create an auto-detected context value."""
        return cls(
            source=ContextSource.AUTO_DETECTED,
            value=value,
            detected_at=detected_at or datetime.now(),
            detection_method=method,
            confidence=confidence,
        )

    @classmethod
    def file_reference(cls, path: str) -> "ContextValue":
        """Create a file reference context value."""
        return cls(
            source=ContextSource.FILE_REFERENCE,
            value=path,
            confirmed_at=datetime.now(),
            confidence=0.9,
        )

    @classmethod
    def default(cls, value: Any) -> "ContextValue":
        """Create a default context value."""
        return cls(
            source=ContextSource.DEFAULT,
            value=value,
            confidence=0.5,
        )


class ContextDefinition(BaseModel):
    """Definition of a context key from TOML framework file.

    Loaded from [context.key] sections in openssf-baseline.toml.
    Defines how a context key should be prompted, validated, and stored.

    Example TOML:
        [context.maintainers]
        type = "list_or_path"
        prompt = "Who are the project maintainers?"
        hint = "Provide GitHub usernames or path to MAINTAINERS.md"
        examples = ["@user1, @user2", "MAINTAINERS.md"]
        affects = ["OSPS-GV-01.01", "OSPS-GV-01.02"]
        store_as = "governance.maintainers"
    """

    model_config = ConfigDict(use_enum_values=True)

    type: ContextType
    prompt: str
    hint: str | None = None
    examples: list[str] = Field(default_factory=list)
    values: list[str] | None = None  # For enum type - allowed values
    affects: list[str] = Field(default_factory=list)  # Control IDs
    store_as: str | None = None  # e.g., "governance.maintainers"
    auto_detect: bool = False
    auto_detect_method: str | None = None  # e.g., "github_collaborators"
    required: bool = False
    presentation_hint: str | None = None  # e.g., "[y/N]", "[1-3]"
    allowed_values: list[str] | None = None  # Display values (distinct from validation `values`)

    @property
    def computed_presentation_hint(self) -> str | None:
        """Return the presentation hint, with smart defaults for boolean/enum types."""
        if self.presentation_hint is not None:
            return self.presentation_hint
        if self.type == ContextType.BOOLEAN:
            return "[y/N]"
        if self.type == ContextType.ENUM:
            vals = self.allowed_values or self.values
            if vals:
                return "[" + "/".join(vals) + "]"
        return None


class ContextPromptRequest(BaseModel):
    """Request for user input on a context value.

    Generated during audits when context would help verify controls.
    Used by get_pending_context to return prompts for missing context.

    Example:
        >>> request = ContextPromptRequest(
        ...     key="maintainers",
        ...     definition=ContextDefinition(...),
        ...     control_ids=["OSPS-GV-01.01", "OSPS-GV-01.02"],
        ...     priority=3  # affects 3 controls
        ... )
    """

    key: str
    definition: ContextDefinition
    control_ids: list[str]  # Controls that need this context
    current_value: ContextValue | None = None  # If auto-detected
    priority: int = 0  # Higher = more important (usually len(control_ids))


# Type alias for context organized by category
ContextByCategory = dict[str, dict[str, ContextValue]]


class ContextCategory(BaseModel):
    """A category of context values (governance, security, build, etc.).

    Organizes related context values together.
    Categories are defined by the store_as field in ContextDefinition.
    """

    model_config = ConfigDict(extra="allow")

    # Dynamic fields are allowed via extra="allow"
    # Each field is a ContextValue keyed by context key name


# CNCF Extension Format Models (schema_version 1.1.0+)


class ExtensionMetadata(BaseModel):
    """Metadata for a CNCF .project extension.

    Used in the extensions.openssf-baseline.metadata section.
    """

    author: str
    homepage: str | None = None
    version: str | None = None
    description: str | None = None


class BaselineExtensionConfig(BaseModel):
    """Configuration for the openssf-baseline extension.

    Used in extensions.openssf-baseline.config section.
    Contains context values organized by category and control overrides.
    """

    model_config = ConfigDict(extra="allow")

    # Context organized by category: governance, security, build, etc.
    # Each category contains key -> ContextValue mappings
    context: dict[str, dict[str, ContextValue | Any]] | None = None

    # Control overrides: control_id -> {status, reason}
    controls: dict[str, Any] | None = None


class BaselineExtension(BaseModel):
    """CNCF-compliant openssf-baseline extension.

    Top-level structure for the extension in project.yaml:
    extensions:
      openssf-baseline:
        metadata: {...}
        config: {...}
    """

    metadata: ExtensionMetadata
    config: BaselineExtensionConfig


class ProjectExtensions(BaseModel):
    """All extensions in a .project file.

    Container for extensions defined in project.yaml.
    Uses alias to handle hyphenated key names.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    openssf_baseline: BaselineExtension | None = Field(
        default=None, alias="openssf-baseline"
    )
    # Other extensions can be added here with similar pattern


class CNCFProjectConfig(BaseModel):
    """CNCF .project/project.yaml schema (v1.1.0+).

    Top-level project configuration following CNCF conventions.
    Uses the extensions: section for tool-specific data.

    Note: The CNCF spec is still under development (PR #131).
    This model may need updates as the spec evolves.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.1.0"
    name: str | None = None
    description: str | None = None
    type: str | None = None
    extensions: ProjectExtensions | None = None
