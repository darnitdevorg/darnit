"""SkillInvocationBackend Protocol conformance tests (feature 029 T019).

Covers SC-005: every registered backend + NoopBackend satisfies the
Protocol via `isinstance` check. Guards against a refactor that
accidentally breaks the Protocol shape.
"""

from __future__ import annotations

import inspect

import pytest

from tests.darnit.parity.tier2.backends import BACKEND_REGISTRY
from tests.darnit.parity.tier2.backends.base import SkillInvocationBackend
from tests.darnit.parity.tier2.backends.noop import NoopBackend


class TestSC005AllRegisteredBackendsConform:
    @pytest.mark.parametrize("name", list(BACKEND_REGISTRY))
    def test_registered_backend_satisfies_protocol(self, name: str) -> None:
        cls = BACKEND_REGISTRY[name]
        instance = cls()
        assert isinstance(instance, SkillInvocationBackend), (
            f"{name!r} ({cls.__name__}) does not satisfy SkillInvocationBackend"
        )

    def test_noop_backend_satisfies_protocol(self) -> None:
        """NoopBackend isn't in BACKEND_REGISTRY but must still conform."""
        assert isinstance(NoopBackend(), SkillInvocationBackend)


class TestBackendShapeInvariants:
    @pytest.mark.parametrize("name", list(BACKEND_REGISTRY))
    def test_backend_has_non_empty_name_attribute(self, name: str) -> None:
        cls = BACKEND_REGISTRY[name]
        assert isinstance(cls.name, str)
        assert cls.name  # non-empty

    @pytest.mark.parametrize("name", list(BACKEND_REGISTRY))
    def test_backend_has_check_env_classmethod(self, name: str) -> None:
        cls = BACKEND_REGISTRY[name]
        assert inspect.ismethod(cls.check_env), f"{name}.check_env must be a classmethod (contract B-3)"

    @pytest.mark.parametrize("name", list(BACKEND_REGISTRY))
    def test_backend_has_async_invoke(self, name: str) -> None:
        cls = BACKEND_REGISTRY[name]
        assert inspect.iscoroutinefunction(cls.invoke), f"{name}.invoke must be an async method (contract B-2)"
