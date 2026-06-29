"""Human feedback handlers for the Darnit agentic workflow.

When the agent hits a control it cannot automatically verify, it needs
to ask a human. This module defines a pluggable interface so the agent
does not care whether it is running interactively (CLI prompts) or
non-interactively (collects questions for later, e.g. GitHub issues).

Usage:
    # Interactive — pauses and prompts the user
    feedback = InteractiveFeedback()
    answer = feedback.ask("OSPS-GV-01.01", "Who are the maintainers?")

    # Non-interactive — collects questions, prints at the end
    feedback = NonInteractiveFeedback()
    answer = feedback.ask("OSPS-GV-01.01", "Who are the maintainers?")
    # answer is None — question is queued for later
    feedback.summarize()  # prints all collected questions
"""

from dataclasses import dataclass

from darnit.core.logging import get_logger

logger = get_logger("agent.feedback")


# =============================================================================
# Data model
# =============================================================================

@dataclass
class FeedbackQuestion:
    """A question that needs a human answer."""
    control_id: str
    question: str
    details: str = ""
    answer: str | None = None


# =============================================================================
# Base interface
# =============================================================================

class HumanFeedback:
    """Base class for human feedback handlers.

    Subclasses implement ask() to handle questions in different ways.
    The agent calls ask() and either gets an answer back (interactive)
    or None (non-interactive — question is queued for later).
    """

    def ask(self, control_id: str, question: str, details: str = "") -> str | None:
        """Ask a human a question about a control.

        Returns the answer string if available, None if deferred.
        """
        raise NotImplementedError

    def has_pending(self) -> bool:
        """Returns True if there are unanswered questions."""
        return False

    def summarize(self) -> list[FeedbackQuestion]:
        """Return all collected questions (answered or not)."""
        return []


# =============================================================================
# Interactive — prompts the user in the terminal
# =============================================================================

class InteractiveFeedback(HumanFeedback):
    """Pauses the run and prompts the user directly in the terminal.

    Best for: running darnit manually on a developer machine.
    """

    def __init__(self) -> None:
        self._answered: list[FeedbackQuestion] = []

    def ask(self, control_id: str, question: str, details: str = "") -> str | None:
        """Print the question and wait for user input."""
        print(f"\n? {control_id}: {question}")
        if details:
            print(f"  {details}")
        print("  (press Enter to skip)")

        try:
            answer = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            # Non-interactive environment or user cancelled
            logger.debug(f"Input not available for {control_id}, skipping")
            answer = ""

        q = FeedbackQuestion(
            control_id=control_id,
            question=question,
            details=details,
            answer=answer if answer else None,
        )
        self._answered.append(q)

        if answer:
            logger.info(f"Received answer for {control_id}")
            return answer

        logger.info(f"No answer provided for {control_id}, skipping")
        return None

    def has_pending(self) -> bool:
        return any(q.answer is None for q in self._answered)

    def summarize(self) -> list[FeedbackQuestion]:
        return self._answered


# =============================================================================
# Non-interactive — collects questions for later
# =============================================================================

class NonInteractiveFeedback(HumanFeedback):
    """Collects all questions without prompting, outputs them at the end.

    Best for: CI environments, headless runs, or when questions should
    be posted as GitHub issues for async human review.
    """

    def __init__(self) -> None:
        self._questions: list[FeedbackQuestion] = []

    def ask(self, control_id: str, question: str, details: str = "") -> str | None:
        """Queue the question — never blocks, always returns None."""
        q = FeedbackQuestion(
            control_id=control_id,
            question=question,
            details=details,
            answer=None,
        )
        self._questions.append(q)
        logger.info(f"Queued feedback question for {control_id}")
        return None

    def has_pending(self) -> bool:
        return len(self._questions) > 0

    def summarize(self) -> list[FeedbackQuestion]:
        return self._questions

    def format_summary(self) -> str:
        """Format all questions as a readable block for printing or posting."""
        if not self._questions:
            return "No human feedback required."

        lines = [f"Human feedback required ({len(self._questions)} items):"]
        for q in self._questions:
            lines.append(f"\n  Control: {q.control_id}")
            lines.append(f"  Question: {q.question}")
            if q.details:
                lines.append(f"  Details: {q.details}")
        return "\n".join(lines)


# =============================================================================
# Factory
# =============================================================================

def get_feedback_handler(mode: str) -> HumanFeedback:
    """Return the right feedback handler for the given mode.

    Args:
        mode: "interactive" or "noninteractive"

    Returns:
        A HumanFeedback instance ready to use.
    """
    if mode == "interactive":
        return InteractiveFeedback()
    elif mode == "noninteractive":
        return NonInteractiveFeedback()
    else:
        logger.warning(f"Unknown feedback mode '{mode}', defaulting to noninteractive")
        return NonInteractiveFeedback()
