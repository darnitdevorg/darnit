"""darnit.harness: end-to-end audit driver (feature 026) + interactive resolvers (feature 027).

Public API surface -- re-exports from submodules so downstream consumers can
import from `darnit.harness` directly without knowing about internal layout.
"""

from darnit.harness.answer_sources import (
    AnswerResolver,
    AnswerSource,
    FileAnswerSource,
    ProjectYamlAnswerSource,
)
from darnit.harness.driver import (
    HarnessRun,
    HarnessRunTimeout,
    HarnessSetupError,
)
from darnit.harness.exit_codes import HarnessExitCode
from darnit.harness.interactive_resolver import InteractiveTerminalResolver
from darnit.harness.question_resolvers import (
    Answer,
    InteractiveAborted,
    QuestionResolver,
    ResolutionTrailEntry,
)
from darnit.harness.report import (
    AnsweredFeedbackEntry,
    HarnessReport,
    HarnessSummary,
    PendingFeedbackEntry,
)
from darnit.harness.resolver_discovery import (
    build_default_resolver_chain,
    discover_registered_resolvers,
)

__all__ = (
    # Feature 026: driver + report
    "HarnessRun",
    "HarnessRunTimeout",
    "HarnessSetupError",
    "HarnessExitCode",
    "HarnessReport",
    "HarnessSummary",
    "PendingFeedbackEntry",
    # Feature 026: answer sources
    "AnswerResolver",
    "AnswerSource",
    "FileAnswerSource",
    "ProjectYamlAnswerSource",
    # Feature 027: question resolvers
    "Answer",
    "AnsweredFeedbackEntry",
    "InteractiveAborted",
    "InteractiveTerminalResolver",
    "QuestionResolver",
    "ResolutionTrailEntry",
    "build_default_resolver_chain",
    "discover_registered_resolvers",
)
