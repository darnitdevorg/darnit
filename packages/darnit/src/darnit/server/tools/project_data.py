"""Project data confirmation tool for OpenSSF Baseline.

Allows users to record project-specific context that cannot be auto-detected,
such as whether a project has subprojects or which CI system is used, and to
confirm a repository's pending not-applicable claims on the operator side
(feature 040), and to confirm PASS candidates from model judgments
(feature 041).
"""


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
    confirm_pass_candidate: list[str] | None = None,
) -> str:
    """Record a person's confirmation of project data values.

    Each value is recorded with who confirmed it and when (feature 042): in
    ``.project/darnit.yaml`` when the operator trusts the repository named by
    ``owner``/``repo``/``host``, otherwise operator-side. Without a repository
    identity from the operator or CI, values are refused.

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
        owner: Owner of the repository whose values or claims are confirmed.
        repo: Name of the repository whose values or claims are confirmed.
        host: Git host of owner/repo (default github.com).
        framework_name: Framework whose controls the claims name.
        confirm_pass_candidate: Control IDs whose PASS candidate (a positive
                         model judgment) the operator confirms for the current
                         evidence. Recorded operator-side, never in the repository.

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
    if confirm_pass_candidate:
        candidates_result = confirm_pass_candidates_impl(
            resolved_path, confirm_pass_candidate, owner=owner, repo=repo, host=host, framework_name=framework_name
        )
        claims_result = f"{claims_result}\n\n{candidates_result}" if claims_result else candidates_result

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

    values = {
        "has_subprojects": has_subprojects,
        "has_releases": has_releases,
        "is_library": is_library,
        "has_compiled_assets": has_compiled_assets,
        "ci_provider": ci_provider,
        "maintainers": maintainers,
        "security_contact": security_contact,
        "governance_model": governance_model,
    }
    values = {key: value for key, value in values.items() if value is not None}

    if not values and claims_result:
        return claims_result
    if not values:
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

    from darnit.config.context_writes import record_value_confirmations
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.trust.decision import target_from_owner_repo

    try:
        operator_config = resolve_operator_config(resolved_path)
    except OperatorConfigError as e:
        return f"Error: {e}"

    results = record_value_confirmations(
        resolved_path, values, target=target_from_owner_repo(owner, repo, host), operator=operator_config.config
    )
    lines = ["Project data:"]
    for result in results:
        if result.outcome == "confirmed" and result.location == "repository":
            lines.append(f"- {result.key}: confirmed, recorded in {result.file}")
        elif result.outcome == "confirmed":
            lines.append(f"- {result.key}: confirmed, recorded operator-side (nothing written to the repository)")
        else:
            lines.append(f"- {result.key}: refused: {result.reason}")
            lines.extend(f"  - {error}" for error in result.errors)
    if any(result.outcome == "confirmed" for result in results):
        lines.append("")
        lines.append(f'Re-run the audit to see the updated status: `audit_openssf_baseline(local_path="{resolved_path}")`')
    claims_section = f"{claims_result}\n\n" if claims_result else ""
    return claims_section + "\n".join(lines)


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

    target = target_from_owner_repo(owner, repo, host)
    decision = decide_trust(target, operator_config.config, local_path)
    identity = decision.repository
    if identity is None or not identity.trusted_eligible:
        return (
            "Error: name the repository whose claims you are confirming (owner, repo, and host when "
            "not github.com). A checkout's own remotes cannot identify it."
        )

    try:
        prepared = prepare_claim_confirmations(
            local_path, control_ids, framework_name, operator_config.config, owner, repo, target
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


def confirm_pass_candidates_impl(
    local_path: str,
    control_ids: list[str],
    *,
    owner: str | None,
    repo: str | None,
    host: str | None = None,
    framework_name: str | None,
) -> str:
    """Confirm stored PASS candidates in the operator-side store (feature 041, FR-011, FR-012).

    Each confirmation is bound to the repository the operator names, the
    control, claim ``pass_candidate``, and the evidence digest of the
    control's judged content as an audit gathers it now. Only a stored
    candidate for exactly that evidence can be confirmed; the confirmation
    lapses on expiry or when the content or the control's rubric changes.
    """
    from darnit.config.operator.loader import OperatorConfigError, resolve_operator_config
    from darnit.tools.audit import judgment_consultations
    from darnit.trust.confirmations import load_candidates, record_confirmation
    from darnit.trust.decision import decide_trust, target_from_owner_repo
    from darnit.trust.judgments import PASS_CANDIDATE_CLAIM, evidence_digest

    if not framework_name:
        return "Error: no framework is configured for confirming PASS candidates."
    try:
        operator_config = resolve_operator_config(local_path)
    except OperatorConfigError as e:
        return f"Error: {e}"

    target = target_from_owner_repo(owner, repo, host)
    identity = decide_trust(target, operator_config.config, local_path).repository
    if identity is None or not identity.trusted_eligible:
        return (
            "Error: name the repository whose PASS candidates you are confirming (owner, repo, and host when "
            "not github.com). A checkout's own remotes cannot identify it."
        )

    try:
        consultations = judgment_consultations(local_path, control_ids, framework_name, operator_config, owner, repo, target)
    except Exception as e:  # noqa: BLE001 - reported to the operator, nothing confirmed
        return f"Error: could not re-gather the evidence: {e}"

    candidates = load_candidates(identity.canonical, checkout=local_path)
    lines = [f"PASS candidates for {identity.canonical}:"]
    for control_id in control_ids:
        consultation = consultations.get(control_id)
        if consultation is None:
            lines.append(f"- {control_id}: does not reach a model judgment step; nothing confirmed")
            continue
        digest = evidence_digest(consultation)
        candidate = next(
            (
                c
                for c in candidates
                if c.control_id == control_id and c.claim == PASS_CANDIDATE_CLAIM and c.evidence_digest == digest
            ),
            None,
        )
        if candidate is None:
            lines.append(f"- {control_id}: no PASS candidate for the current evidence; nothing confirmed")
            continue
        try:
            confirmation = record_confirmation(
                identity.canonical,
                control_id,
                PASS_CANDIDATE_CLAIM,
                digest,
                operator_config.config,
                checkout=local_path,
            )
        except (OSError, ValueError) as e:
            lines.append(f"- {control_id}: not confirmed; {e}")
            continue
        lines.append(
            f"- {control_id}: confirmed by {confirmation.confirmed_by} until {confirmation.expires_at} "
            f"(judgment by {candidate.candidate.get('model') or 'unknown model'}: "
            f"{candidate.candidate.get('reasoning', '')})"
        )
    lines.append("")
    lines.append(
        "A confirmation applies until it expires or the judged content or the control's rubric changes. "
        "Re-run the audit to see it."
    )
    return "\n".join(lines)
