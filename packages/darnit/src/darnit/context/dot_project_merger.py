"""Merge org-level and local .project/ configurations.

Implements section-level merge where local config overrides org-level
defaults. When a local repo has a `.project/` directory, its values take
precedence over the org-level `.project` repository values.

Merge strategy: local overrides org at the **section** level.
- If local has `security:`, that entire section wins (org security ignored).
- If local does NOT have `security:`, org's `security:` is used.
- Scalar fields (name, description, etc.) follow the same rule: local wins.
- List fields (maintainers, repositories) use local if present, else org.

Example:
    from darnit.context.dot_project_merger import merge_configs

    merged = merge_configs(org_config=org, local_config=local)
"""

from __future__ import annotations

import logging

from darnit.context.dot_project import ProjectConfig

logger = logging.getLogger(__name__)

# Sections that merge at the section level (local wins entirely if present)
_SECTION_FIELDS = frozenset({
    "security",
    "governance",
    "legal",
    "documentation",
    "landscape",
})

# Scalar fields where local wins if non-empty
_SCALAR_FIELDS = frozenset({
    "name",
    "description",
    "schema_version",
    "type",
    "slug",
    "project_lead",
    "cncf_slack_channel",
    "website",
    "artwork",
})

# List fields where local wins if non-empty
_LIST_FIELDS = frozenset({
    "repositories",
    "mailing_lists",
    "maturity_log",
    "audits",
    "maintainers",
    "maintainer_teams",
    "maintainer_entries",
})

# Dict fields where local wins if non-empty
_DICT_FIELDS = frozenset({
    "social",
    "package_managers",
    "extensions",
})


def merge_configs(
    org_config: ProjectConfig | None,
    local_config: ProjectConfig,
) -> ProjectConfig:
    """Merge org-level config with local config.

    Local config takes precedence at the section level. If a section
    or field is present in local, it completely overrides the org value.
    If absent in local, the org value is used as a default.

    Args:
        org_config: Config from the org-level .project repo (defaults)
        local_config: Config from the local repo's .project/ directory

    Returns:
        Merged ProjectConfig (a new instance; inputs are not modified)
    """
    if org_config is None:
        return local_config

    # Start with a copy of org config as the base
    merged = _shallow_copy_config(org_config)

    # Override scalar fields if local has them
    for field_name in _SCALAR_FIELDS:
        local_value = getattr(local_config, field_name, "")
        if local_value:
            setattr(merged, field_name, local_value)

    # Override section fields if local has them (section-level override)
    for field_name in _SECTION_FIELDS:
        local_value = getattr(local_config, field_name, None)
        if local_value is not None:
            setattr(merged, field_name, local_value)

    # Override list fields if local has non-empty lists
    for field_name in _LIST_FIELDS:
        local_value = getattr(local_config, field_name, [])
        if local_value:
            setattr(merged, field_name, list(local_value))

    # Override dict fields if local has non-empty dicts
    for field_name in _DICT_FIELDS:
        local_value = getattr(local_config, field_name, {})
        if local_value:
            setattr(merged, field_name, dict(local_value))

    # Override adopters if local has it
    if local_config.adopters is not None:
        merged.adopters = local_config.adopters

    # Override maintainer metadata if local has it
    if local_config.maintainer_org:
        merged.maintainer_org = local_config.maintainer_org
    if local_config.maintainer_project_id:
        merged.maintainer_project_id = local_config.maintainer_project_id

    # Merge _extra fields (local overrides keys present in both)
    merged_extra = dict(org_config._extra)
    merged_extra.update(local_config._extra)
    merged._extra = merged_extra

    # Preserve local source path
    merged._source_path = local_config._source_path

    logger.debug(
        "Merged org config (%s) with local config (%s)",
        org_config.name or "unnamed",
        local_config.name or "unnamed",
    )

    return merged


def _shallow_copy_config(config: ProjectConfig) -> ProjectConfig:
    """Create a shallow copy of a ProjectConfig."""
    return ProjectConfig(
        name=config.name,
        repositories=list(config.repositories),
        description=config.description,
        schema_version=config.schema_version,
        type=config.type,
        slug=config.slug,
        project_lead=config.project_lead,
        cncf_slack_channel=config.cncf_slack_channel,
        website=config.website,
        artwork=config.artwork,
        adopters=config.adopters,
        mailing_lists=list(config.mailing_lists),
        maturity_log=list(config.maturity_log),
        audits=list(config.audits),
        social=dict(config.social),
        package_managers=dict(config.package_managers),
        security=config.security,
        governance=config.governance,
        legal=config.legal,
        documentation=config.documentation,
        landscape=config.landscape,
        extensions=dict(config.extensions),
        maintainers=list(config.maintainers),
        maintainer_teams=list(config.maintainer_teams),
        maintainer_entries=list(config.maintainer_entries),
        maintainer_org=config.maintainer_org,
        maintainer_project_id=config.maintainer_project_id,
        _extra=dict(config._extra),
        _source_path=config._source_path,
    )
