"""Project context confirmation tool for OpenSSF Baseline.

Allows users to record project-specific context that cannot be auto-detected,
such as whether a project has subprojects or which CI system is used.
"""


from darnit.config.loader import (
    init_project_config,
    load_project_config,
    save_project_config,
)
from darnit.config.schema import (
    BaselineExtension,
    ProjectContext,
)
from darnit.core.utils import validate_local_path

VALID_CI_PROVIDERS = ["github", "gitlab", "jenkins", "circleci", "azure", "travis", "none", "other"]
VALID_GOVERNANCE_MODELS = ["bdfl", "meritocracy", "democracy", "corporate", "foundation", "committee", "other"]


def confirm_project_context_impl(
    local_path: str = ".",
    # Existing parameters (backward compatible)
    has_subprojects: bool | None = None,
    has_releases: bool | None = None,
    is_library: bool | None = None,
    has_compiled_assets: bool | None = None,
    ci_provider: str | None = None,
    # New parameters for governance and security
    maintainers: list[str] | str | None = None,
    security_contact: str | None = None,
    governance_model: str | None = None,
) -> str:
    """Record user-confirmed project context in .project.yaml.

    Updates the x-openssf-baseline.context section with user-confirmed values
    that affect how controls are evaluated.

    Args:
        local_path: Path to the repository
        has_subprojects: Does this project have subprojects or related repositories?
        has_releases: Does this project make official releases?
        is_library: Is this a library/framework consumed by other projects?
        has_compiled_assets: Does this project release compiled binaries?
        ci_provider: What CI/CD system does this project use?
                    Options: github, gitlab, jenkins, circleci, azure, travis, none, other
        maintainers: Project maintainers - list of GitHub usernames or path to MAINTAINERS file.
                    Examples: ["@user1", "@user2"] or "MAINTAINERS.md"
        security_contact: Security contact for vulnerability reports.
                         Email address, URL, or reference to SECURITY.md section.
        governance_model: Governance model used by this project.
                         Options: bdfl, meritocracy, democracy, corporate, foundation, committee, other

    Returns:
        Confirmation of what was recorded
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    # Validate ci_provider if provided
    if ci_provider is not None:
        if ci_provider.lower() not in VALID_CI_PROVIDERS:
            return f"❌ Invalid ci_provider: {ci_provider}. Valid options: {', '.join(VALID_CI_PROVIDERS)}"
        ci_provider = ci_provider.lower()

    # Validate governance_model if provided
    if governance_model is not None:
        if governance_model.lower() not in VALID_GOVERNANCE_MODELS:
            return f"❌ Invalid governance_model: {governance_model}. Valid options: {', '.join(VALID_GOVERNANCE_MODELS)}"
        governance_model = governance_model.lower()

    # Check if any values were provided
    updates = []
    if has_subprojects is not None:
        updates.append(f"  - has_subprojects: {has_subprojects}")
    if has_releases is not None:
        updates.append(f"  - has_releases: {has_releases}")
    if is_library is not None:
        updates.append(f"  - is_library: {is_library}")
    if has_compiled_assets is not None:
        updates.append(f"  - has_compiled_assets: {has_compiled_assets}")
    if ci_provider is not None:
        updates.append(f"  - ci_provider: {ci_provider}")
    if maintainers is not None:
        if isinstance(maintainers, list):
            updates.append(f"  - maintainers: {maintainers}")
        else:
            updates.append(f"  - maintainers: {maintainers}")
    if security_contact is not None:
        updates.append(f"  - security_contact: {security_contact}")
    if governance_model is not None:
        updates.append(f"  - governance_model: {governance_model}")

    if not updates:
        return """ℹ️ No context values provided.

**Usage:**
```python
confirm_project_context(
    local_path=".",
    has_subprojects=False,  # No related repos
    has_releases=True,      # We make releases
    ci_provider="gitlab",   # Using GitLab CI instead of GitHub Actions
    maintainers=["@user1", "@user2"],  # Project maintainers
    security_contact="security@example.com",  # Security contact
    governance_model="meritocracy",  # Governance model
)
```

**Available context keys:**
- `has_subprojects`: Does this project have subprojects or related repositories?
- `has_releases`: Does this project make official releases?
- `is_library`: Is this a library/framework consumed by other projects?
- `has_compiled_assets`: Does this project release compiled binaries?
- `ci_provider`: What CI/CD system? Options: github, gitlab, jenkins, circleci, azure, travis, none, other
- `maintainers`: Project maintainers - list of GitHub usernames or path to MAINTAINERS file
- `security_contact`: Security contact for vulnerability reports (email, URL, or file reference)
- `governance_model`: Governance model - bdfl, meritocracy, democracy, corporate, foundation, committee, other
"""

    # Load existing config or create new one
    config = load_project_config(resolved_path)
    if config is None:
        config = init_project_config(resolved_path)

    # Ensure baseline extension exists
    if config.x_openssf_baseline is None:
        config.x_openssf_baseline = BaselineExtension()

    # Ensure context exists
    if config.x_openssf_baseline.context is None:
        config.x_openssf_baseline.context = ProjectContext()

    context = config.x_openssf_baseline.context

    # Update context values (only those provided)
    if has_subprojects is not None:
        context.has_subprojects = has_subprojects
    if has_releases is not None:
        context.has_releases = has_releases
    if is_library is not None:
        context.is_library = is_library
    if has_compiled_assets is not None:
        context.has_compiled_assets = has_compiled_assets
    if ci_provider is not None:
        context.ci_provider = ci_provider
    if maintainers is not None:
        context.maintainers = maintainers
    if security_contact is not None:
        context.security_contact = security_contact
    if governance_model is not None:
        context.governance_model = governance_model

    # Save config
    try:
        config_path = save_project_config(config, resolved_path)
    except Exception as e:
        return f"❌ Error saving config: {e}"

    updates_str = '\n'.join(updates)
    return f"""✅ Project context updated in .project.yaml

**Recorded:**
{updates_str}

**File:** {config_path}

These confirmations will be used by future audits to give more accurate results.
Re-run the audit to see the updated status:
`audit_openssf_baseline(local_path="{resolved_path}")`
"""
