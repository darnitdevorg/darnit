"""State definitions for the darnit run agent graph.

This module defines the shared state that flows between nodes in the
audit/collect_context/remediate pipeline.

Issue #146: feedback_questions were previously write-only — answers were stored
but never read by downstream nodes. This module makes the answer field explicit
and provides helpers so every node can consume collected feedback.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FeedbackQuestion:
    """A question asked of the user to resolve a WARN control.

    Answers written by collect_context are read by remediate and re-audit
    passes so that context-dependent controls can be re-evaluated correctly.
    """

    control_id: str          # The WARN control that triggered this question
    context_key: str         # Key to store the answer under (e.g. "has_releases")
    question: str            # Human-readable question text
    answer: str | None = None   # Populated by collect_context
    answered: bool = False   # True once the user has provided an answer


@dataclass
class AuditState:
    """Shared state for the darnit run agent graph.

    Flows through: audit → collect_context → audit (re-run) → remediate.

    Attributes:
        local_path: Absolute path to the repository being audited.
        owner: GitHub org/user (auto-detected from git if None).
        repo: Repository name (auto-detected from git if None).
        default_branch: Default branch of the repository.
        framework_name: Compliance framework to use (e.g. "openssf-baseline").
        level: Maximum maturity level to audit (1, 2, or 3).
        audit_results: Raw result dicts from the latest audit run.
        feedback_questions: Context questions for unresolvable WARN controls.
            Written by collect_context; READ by remediate and the re-audit pass
            so answers feed into ${context.*} variable substitution.
        remediation_results: Outcomes from the remediate node.
        context_values: Flattened key→value map built from answered feedback
            questions. Populated by collect_context; consumed by remediate.
        error: Set when a node encounters a fatal error.
    """

    local_path: str
    owner: str | None = None
    repo: str | None = None
    default_branch: str = "main"
    framework_name: str | None = None
    level: int = 3

    # Populated by the audit node
    audit_results: list[dict[str, Any]] = field(default_factory=list)

    # Issue #146 fix: feedback_questions are written AND read.
    # collect_context writes the answers; remediate reads them via
    # context_values to feed ${context.*} substitutions.
    feedback_questions: list[FeedbackQuestion] = field(default_factory=list)

    # Flattened {key: answer} map derived from answered feedback_questions.
    # Built by collect_context after the user provides answers so that
    # downstream nodes (remediate, re-audit) can consume context without
    # iterating over feedback_questions themselves.
    context_values: dict[str, Any] = field(default_factory=dict)

    # Populated by the remediate node
    remediation_results: list[dict[str, Any]] = field(default_factory=list)

    # Set on fatal errors
    error: str | None = None

    # -------------------------------------------------------------------------
    # Convenience helpers
    # -------------------------------------------------------------------------

    def failing_control_ids(self) -> list[str]:
        """Return IDs of controls whose latest status is FAIL."""
        return [r["id"] for r in self.audit_results if r.get("status") == "FAIL"]

    def warn_control_ids(self) -> list[str]:
        """Return IDs of controls whose latest status is WARN."""
        return [r["id"] for r in self.audit_results if r.get("status") == "WARN"]

    def has_unanswered_questions(self) -> bool:
        """Return True if any feedback question is still unanswered."""
        return any(not q.answered for q in self.feedback_questions)

    def collect_answered_context(self) -> dict[str, Any]:
        """Build a {context_key: answer} dict from all answered questions.

        Called by collect_context after answers are recorded so the result can
        be stored in context_values and persisted via save_context_values.
        """
        return {
            q.context_key: q.answer
            for q in self.feedback_questions
            if q.answered and q.answer is not None
        }
