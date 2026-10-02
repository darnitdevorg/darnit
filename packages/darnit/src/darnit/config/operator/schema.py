"""Operator configuration models (feature 040, contracts/operator-config.md).

Every model forbids unknown keys: a misplaced trust setting must fail loudly
rather than be silently ignored. Trust-relevant booleans are strict so that a
string such as "false" is not coerced.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from darnit.config.framework_schema import (
    ControlConfig,
    HandlerInvocation,
    McpServerConfig,
    StoresConfig,
)

_FORBID = ConfigDict(extra="forbid")


class OperatorIdentity(BaseModel):
    model_config = _FORBID

    # Recorded as ``confirmed_by`` on confirmations; the OS user name is used when unset.
    identity: StrictStr | None = None


class PluginSettings(BaseModel):
    model_config = _FORBID

    # Empty means every installed framework may load.
    allowed: list[StrictStr] = Field(default_factory=list)
    trusted_publishers: list[StrictStr] = Field(default_factory=list)
    allow_unsigned: StrictBool = False


class OperatorControlOverride(BaseModel):
    model_config = _FORBID

    passes: list[HandlerInvocation] | None = None


class LlmSettings(BaseModel):
    model_config = _FORBID

    provider: StrictStr | None = None
    model: StrictStr | None = None
    max_cost_usd_per_run: float | None = Field(default=None, ge=0)


class CiTrustRule(BaseModel):
    model_config = _FORBID

    event: Literal["push-default-branch"]
    # Optional narrowing to specific trusted repositories (canonical identities).
    repos: list[StrictStr] = Field(default_factory=list)


class TrustSettings(BaseModel):
    model_config = _FORBID

    repos: list[StrictStr] = Field(default_factory=list)
    case_insensitive_hosts: list[StrictStr] = Field(default_factory=list)
    ci: list[CiTrustRule] = Field(default_factory=list)


class PolicySettings(BaseModel):
    model_config = _FORBID

    confirmation_expiry_days: int = Field(default=180, ge=1)
    # May only turn strict mode on; the launch option and CI detection are the
    # primary switches, and the checked file can never turn strict mode off.
    strict_permissions: StrictBool = False


RemediationMode = Literal["prompt", "manual", "auto"]


class RemediationSettings(BaseModel):
    """Policy for platform changes made by remediation (feature 043, FR-026).

    ``prompt`` asks a person and applies only an approved change; ``manual``
    makes no platform change and reports the steps; ``auto`` applies without
    asking. ``high_impact`` covers organization-wide settings and repository
    visibility (FR-008); ``platform`` covers every other platform change.
    """

    model_config = _FORBID

    platform: RemediationMode = "prompt"
    high_impact: RemediationMode = "prompt"


class OperatorConfig(BaseModel):
    """Tool configuration owned by whoever runs darnit."""

    model_config = _FORBID

    schema_version: Literal[1]
    operator: OperatorIdentity = Field(default_factory=OperatorIdentity)
    plugins: PluginSettings = Field(default_factory=PluginSettings)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    controls: dict[str, OperatorControlOverride] = Field(default_factory=dict)
    custom_controls: dict[str, ControlConfig] = Field(default_factory=dict)
    stores: StoresConfig = Field(default_factory=StoresConfig)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    trust: TrustSettings = Field(default_factory=TrustSettings)
    policy: PolicySettings = Field(default_factory=PolicySettings)
    remediation: RemediationSettings = Field(default_factory=RemediationSettings)
