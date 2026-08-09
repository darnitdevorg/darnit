"""Entry-point discovery for QuestionResolver plugins (feature 027 T017).

Resolves the `darnit.question_resolvers` entry-point group via
`importlib.metadata`. Matches the pattern used by `darnit.frameworks`
(compliance implementations).

Contract:
  - QR-14..QR-16 from contracts/question-resolver-protocol.md
  - Research decision R2 (importlib.metadata, lazy, warn-and-skip on failure)
"""

from __future__ import annotations

from importlib import metadata
from typing import Any

from darnit.core.logging import get_logger
from darnit.harness.question_resolvers import QuestionResolver

logger = get_logger("harness.resolver_discovery")

ENTRY_POINT_GROUP = "darnit.question_resolvers"


def discover_registered_resolvers() -> dict[str, QuestionResolver]:
    """Discover resolvers registered via Python entry points.

    Returns a dict mapping entry-point name -> resolver instance. Failures
    during `ep.load()` or the follow-up `isinstance()` check log a WARNING
    and are skipped; other entry points still register.
    """
    found: dict[str, QuestionResolver] = {}

    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        # Python 3.9 shape (kwargs not supported); we require 3.11+ so this
        # should not fire, but defensive fallback: filter manually.
        eps = [
            ep
            for ep in metadata.entry_points()  # type: ignore[call-arg]
            if getattr(ep, "group", None) == ENTRY_POINT_GROUP
        ]

    for ep in eps:
        try:
            factory = ep.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "resolver entry point %r failed to load: %s: %s",
                ep.name,
                type(exc).__name__,
                exc,
            )
            continue

        try:
            instance = factory()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "resolver entry point %r factory raised: %s: %s",
                ep.name,
                type(exc).__name__,
                exc,
            )
            continue

        if not isinstance(instance, QuestionResolver):
            logger.warning(
                "resolver entry point %r produced %s which does not satisfy "
                "the QuestionResolver Protocol",
                ep.name,
                type(instance).__name__,
            )
            continue

        found[ep.name] = instance

    return found


def build_default_resolver_chain(interactive: bool) -> list[Any]:
    """Build the CLI's canonical resolver chain.

    Contract QR-21 + research.md R7:
      - Discover all entry-point registered resolvers.
      - If interactive=True: put `interactive_terminal` first (raise if absent).
      - Append every OTHER resolver in discovery order.

    Returns a list of resolver instances. The list may be empty when
    interactive=False and no third-party resolvers are registered.
    """
    all_resolvers = discover_registered_resolvers()

    # Always remove `interactive_terminal` from the general pool -- it's
    # only included in the chain when interactive=True is explicit. A
    # fleet operator running non-interactive should never trigger a prompt.
    terminal = all_resolvers.pop("interactive_terminal", None)

    chain: list[Any] = []

    if interactive:
        if terminal is None:
            from darnit.harness.driver import HarnessSetupError

            raise HarnessSetupError(
                "interactive channel unavailable "
                "(the `interactive_terminal` resolver entry point is not registered)",
            )
        chain.append(terminal)

    # Every other resolver in stable entry-point discovery order.
    for _name, resolver in all_resolvers.items():
        chain.append(resolver)

    return chain


__all__ = (
    "discover_registered_resolvers",
    "build_default_resolver_chain",
    "ENTRY_POINT_GROUP",
)
