"""SC-002 enforcement: a resolver defined OUTSIDE the harness dir works
(feature 027 T021).

The whole extensibility contract of feature 027 lives here: a resolver that
lives outside `packages/darnit/src/darnit/harness/` must be discoverable and
invoked by the harness with NO edits under that directory.

We prove this by:
  1. Importing a `QuestionResolver` from
     `tests/darnit/harness/fixtures/mock_resolver_pkg/mock_resolver_pkg/resolvers.py`
     -- a location strictly outside `packages/darnit/src/darnit/harness/`.
  2. Injecting it into `HarnessRun.question_resolvers` and running the collect
     phase.
  3. Asserting the injected resolver's answer landed in the report.

Bonus proof: the fixture's `pyproject.toml` declares entry-points; a downstream
consumer that `uv pip install`s the fixture package would get the same resolver
via discovery. That path is covered by `test_resolver_discovery.py`; here we
only cover the direct-injection surface which is even stronger (proves the
Protocol works for any external code, discovery-mediated or not).
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

from darnit.harness.driver import HarnessRun
from darnit.harness.question_resolvers import QuestionResolver

# Make the fixture package importable without installing it.
_FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "mock_resolver_pkg"
).resolve()
if str(_FIXTURE_ROOT) not in sys.path:
    sys.path.insert(0, str(_FIXTURE_ROOT))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestExternalResolverExtensibility:
    def test_resolver_from_outside_harness_dir_is_invoked(
        self,
        minimal_llm_repo_tree: Path,
        harness_run_factory: Callable[..., HarnessRun],
    ) -> None:
        """SC-002: import a resolver from a directory OUTSIDE the harness
        subtree; use it via direct injection; assert its answer appears in
        the report."""
        # Import the fixture (proves the module lives outside the harness dir).
        from mock_resolver_pkg.resolvers import (  # type: ignore[import-not-found]
            build_answer,
        )

        # Sanity: the resolver's module path is under the fixture dir, NOT
        # under the harness dir. If somebody moves it, this assertion fails
        # loudly.
        instance = build_answer()
        module_file = sys.modules[type(instance).__module__].__file__ or ""
        assert "packages/darnit/src/darnit/harness" not in module_file, (
            f"fixture resolver leaked into harness dir: {module_file}"
        )
        assert isinstance(instance, QuestionResolver)

        # Now: run the driver's collect phase with this external resolver.
        run = harness_run_factory(str(minimal_llm_repo_tree))
        run.question_resolvers = [instance]

        fake_results = [
            {
                "id": "CTRL-01",
                "status": "FAIL",
                "authority": "dispositive",
                "level": 1,
                "feedback_questions": [
                    {
                        "control_id": "CTRL-01",
                        "context_key": "security_contact",
                        "question": "Who?",
                        "answered": False,
                    },
                ],
            },
        ]
        _updated, pending, answered, ctx = _run(run._collect_unanswered(fake_results))

        # Extensibility contract: external resolver's answer appears here.
        assert pending == []
        assert len(answered) == 1
        assert answered[0].origin == "mock_answer"
        assert ctx["security_contact"] == "fixed"
        # SC-003: authority=asserted preserved through the external Protocol
        # boundary.
        assert answered[0].authority == "asserted"
