"""Project data confirmation tool for OpenSSF Baseline.

Allows users to record project-specific context that cannot be auto-detected,
such as whether a project has subprojects or which CI system is used, and to
confirm a repository's pending not-applicable claims on the operator side
(feature 040).
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


def confirm_project_data_impl(
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
    confirm_not_applicable: list[str] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    host: str | None = None,
    framework_name: str | None = None,
) -> str:
    """Record user-confirmed project data in .project.yaml.

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
        confirm_not_applicable: Control IDs whose pending not-applicable claim
                         the operator confirms. Recorded operator-side, never in the repository.
        owner: Owner of the repository whose claims are confirmed.
        repo: Name of the repository whose claims are confirmed.
        host: Git host of owner/repo (default github.com).
        framework_name: Framework whose controls the claims name.

    Returns:
        Confirmation of what was recorded
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    claims_result = (
        confirm_not_applicable_impl(
            resolved_path, confirm_not_applicable, owner=owner, repo=repo, host=host, framework_name=framework_name
        )
        if confirm_not_applicable
        else ""
    )

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

    if not updates and claims_result:
        return claims_result
    if not updates:
        return """ℹ️ No data values provided.

**Usage:**
```python
confirm_project_data(
    local_path=".",
    has_subprojects=False,  # No related repos
    has_releases=True,      # We make releases
    ci_provider="gitlab",   # Using GitLab CI instead of GitHub Actions
    maintainers=["@user1", "@user2"],  # Project maintainers
    security_contact="security@example.com",  # Security contact
    governance_model="meritocracy",  # Governance model
)
```

**Available data keys:**
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

    # Update data values (only those provided)
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

    # Round-trip verification: read back persisted values to catch path-mismatch bugs
    from darnit.config.context_storage import load_stored_context

    verified_values: list[str] = []
    try:
        readback = load_stored_context(resolved_path)
        # Flatten all categories into a single dict of key -> value
        all_values: dict[str, object] = {}
        for cat_values in readback.values():
            for k, v in cat_values.items():
                all_values[k] = v.value

        # Check each value we just saved
        check_pairs: list[tuple[str, object]] = []
        if has_subprojects is not None:
            check_pairs.append(("has_subprojects", has_subprojects))
        if has_releases is not None:
            check_pairs.append(("has_releases", has_releases))
        if is_library is not None:
            check_pairs.append(("is_library", is_library))
        if has_compiled_assets is not None:
            check_pairs.append(("has_compiled_assets", has_compiled_assets))
        if ci_provider is not None:
            # ci_provider is stored as "provider" in the ci category
            check_pairs.append(("provider", ci_provider))
        if maintainers is not None:
            check_pairs.append(("maintainers", maintainers))
        if security_contact is not None:
            check_pairs.append(("security_contact", security_contact))
        if governance_model is not None:
            check_pairs.append(("governance_model", governance_model))

        for key, expected in check_pairs:
            actual = all_values.get(key)
            if actual == expected:
                verified_values.append(f"  - ✅ `{key}`: {actual}")
            else:
                verified_values.append(f"  - ❌ `{key}`: expected {expected!r}, got {actual!r}")
    except Exception as e:
        verified_values.append(f"  - ⚠️ Round-trip verification failed: {e}")

    updates_str = '\n'.join(updates)
    verified_str = '\n'.join(verified_values)
    claims_section = f"{claims_result}\n\n" if claims_result else ""
    return claims_section + f"""✅ Project data updated in .project.yaml

**Recorded:**
{updates_str}

**Verified (round-trip read-back):**
{verified_str}

**File:** {config_path}

These values improve audit accuracy and are used by remediation to generate project-specific files.
Re-run the audit to see the updated status:
`audit_openssf_baseline(local_path="{resolved_path}")`
"""


def confirm_not_applicable_impl(
    local_path: str,
    control_ids: list[str],
    *,
    owner: str | None,
    repo: str | None,
    host: str | None = None,
    framework_name: str | None,
) -> str:
    """Confirm pending not-applicable claims in the operator-side store (feature 040, FR-019, FR-019a).

    Each confirmation is bound to the repository the operator names, the
    control, the claim, and a digest of the claim's current reason and
    evidence; it lapses on expiry or when either changes. A claim that
    evidence contradicts is not confirmed.
    """
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.tools.audit import prepare_claim_confirmations
    from darnit.trust.confirmations import record_confirmation
    from darnit.trust.decision import decide_trust, target_from_owner_repo

    if not framework_name:
        return "Error: no framework is configured for confirming claims."
    try:
        operator_config = resolve_operator_config(local_path)
    except OperatorConfigError as e:
        return f"Error: {e}"

    decision = decide_trust(target_from_owner_repo(owner, repo, host), operator_config.config, local_path)
    identity = decision.repository
    if identity is None or not identity.trusted_eligible:
        return (
            "Error: name the repository whose claims you are confirming (owner, repo, and host when "
            "not github.com). A checkout's own remotes cannot identify it."
        )

    try:
        prepared = prepare_claim_confirmations(
            local_path, control_ids, framework_name, operator_config.config, owner, repo
        )
    except ValueError as e:
        return f"Error: {e}"

    lines = [f"Not-applicable claims for {identity.canonical}:"]
    for control_id in control_ids:
        entry = prepared.get(control_id)
        if entry is None:
            lines.append(f"- {control_id}: no not-applicable claim found; nothing confirmed")
            continue
        claim, digest, contradiction = entry
        if contradiction:
            lines.append(f"- {control_id}: not confirmed; {contradiction['summary']}")
            continue
        try:
            confirmation = record_confirmation(
                identity.canonical, control_id, claim.claim, digest, operator_config.config, checkout=local_path
            )
        except (OSError, ValueError) as e:
            lines.append(f"- {control_id}: not confirmed; {e}")
            continue
        lines.append(
            f"- {control_id}: confirmed by {confirmation.confirmed_by} until {confirmation.expires_at} "
            f"(claim in {claim.location}: {claim.reason or 'no reason given'})"
        )
    lines.append("")
    lines.append(
        "A confirmation applies until it expires or the claim or its evidence changes. Re-run the audit to see it."
    )
    return "\n".join(lines)
