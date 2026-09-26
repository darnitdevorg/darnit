"""Whether the repository an audit targets is trusted (feature 040, FR-016).

The identity used for the decision comes from the operator's target or from
CI platform metadata, never from the checkout's own remotes (FR-016a). A
repository is trusted when that identity is in the operator's
``trust.repos`` and, in CI, an operator CI rule permits the triggering event.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from darnit.trust.ci import REASON_UNKNOWN_EVENT, apply_ci_rules, detect_ci_run
from darnit.trust.identity import IdentitySource, RepositoryIdentity, canonical_identity

if TYPE_CHECKING:
    from darnit.config.operator.schema import OperatorConfig


@dataclass(frozen=True)
class TrustDecision:
    repository: RepositoryIdentity | None
    trusted: bool
    reason: str
    ci_facts: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def report(self) -> dict[str, Any]:
        """The ``trust`` block every audit report carries."""
        return {
            "repository": self.repository.canonical if self.repository else None,
            "identity_source": self.repository.source.value if self.repository else None,
            "trusted": self.trusted,
            "reason": self.reason,
            "ci_facts": dict(self.ci_facts),
            "warnings": list(self.warnings),
        }


def format_trust(trust: dict[str, Any]) -> str:
    """One-line summary of a ``trust`` report block."""
    repository = trust.get("repository") or "unknown repository"
    source = trust.get("identity_source")
    source_note = f" [{source}]" if source and source != "operator_target" else ""
    state = "trusted" if trust.get("trusted") else "untrusted"
    return f"{repository}{source_note} {state} ({trust.get('reason')})"


def target_from_owner_repo(owner: str | None, repo: str | None, host: str | None = None) -> str | None:
    """Operator target named by an owner/repo pair (and optional host)."""
    if not owner or not repo:
        return None
    return f"{host or 'github.com'}/{owner}/{repo}"


def owner_repo_from_identity(canonical: str) -> tuple[str, str]:
    """Split ``host/namespace/name`` into ``(namespace, name)``."""
    parts = canonical.split("/")
    return "/".join(parts[1:-1]), parts[-1]


def decide_trust(
    target: str | None,
    operator: OperatorConfig,
    checkout: str | Path | None,
    env: Mapping[str, str] | None = None,
) -> TrustDecision:
    """Decide whether the audited repository is trusted for this run.

    Args:
        target: Repository identity the operator named (``--repo`` or MCP
            tool arguments), or None.
        operator: Operator configuration.
        checkout: Path of the audited checkout.
        env: Environment to read CI metadata from (default: the process environment).
    """
    from darnit.core.utils import detect_checkout_identity

    hosts = operator.trust.case_insensitive_hosts
    trusted_repos = {c for c in (canonical_identity(r, hosts) for r in operator.trust.repos) if c}
    hint = detect_checkout_identity(str(checkout), hosts) if checkout is not None else None
    target_canonical = canonical_identity(target, hosts) if target else None
    operator_identity = (
        RepositoryIdentity(target_canonical, IdentitySource.OPERATOR_TARGET) if target_canonical else None
    )

    warnings: list[str] = []
    if target and target_canonical is None:
        warnings.append(f"operator target {target!r} is not a repository identity")
    if operator_identity and hint and hint.canonical != operator_identity.canonical:
        warnings.append(
            f"operator target {operator_identity.canonical} does not match the checkout's "
            f"origin remote {hint.canonical}"
        )

    run = detect_ci_run(env, hosts)
    if run is not None:
        repository = (
            RepositoryIdentity(run.repository, IdentitySource.CI_METADATA)
            if run.repository
            else operator_identity or hint
        )
        if run.platform == "unknown":
            return TrustDecision(repository, False, REASON_UNKNOWN_EVENT, run.facts, tuple(warnings))
        if run.default_branch_push and operator_identity and operator_identity.canonical != run.repository:
            return TrustDecision(
                repository, False, "ci: target does not match CI repository", run.facts, tuple(warnings)
            )
        trusted, reason = apply_ci_rules(run, trusted_repos, operator.trust, checkout)
        return TrustDecision(repository, trusted, reason, run.facts, tuple(warnings))

    if operator_identity is not None:
        trusted = operator_identity.canonical in trusted_repos
        return TrustDecision(
            operator_identity, trusted, "listed; local run" if trusted else "not listed", {}, tuple(warnings)
        )
    if hint is not None:
        return TrustDecision(hint, False, "identity from checkout only", {}, tuple(warnings))
    return TrustDecision(None, False, "no repository identity", {}, tuple(warnings))
