"""Step ceilings and declarations (feature 041, contracts/step-declarations.md).

Each step type registers a ceiling; a step narrows it with ``concludes`` and
exceeds it only with a ``promotion``. Loading rejects declarations that break
the rules, naming the framework, control, step index, and outcome.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from darnit.config.control_loader import validate_step_authority
from darnit.config.framework_schema import HandlerInvocation
from darnit.core.errors import AuthorityViolation
from darnit.sieve.handler_registry import (
    SieveHandlerRegistry,
    effective_outcomes,
    get_sieve_handler_registry,
)

PASS_FAIL = frozenset({"pass", "fail"})
FAIL_ONLY = frozenset({"fail"})
NOTHING = frozenset()


def _noop(config, context):  # noqa: ARG001
    raise AssertionError("not called")


class TestBuiltinCeilings:
    @pytest.mark.parametrize(
        ("handler", "ceiling", "existence_ceiling"),
        [
            ("file_exists", FAIL_ONLY, PASS_FAIL),
            ("regex", FAIL_ONLY, PASS_FAIL),
            ("pattern", FAIL_ONLY, PASS_FAIL),
            ("exec", PASS_FAIL, None),
            ("mcp", PASS_FAIL, None),
            ("llm_eval", NOTHING, None),
            ("llm_extract", NOTHING, None),
            ("manual", NOTHING, None),
            ("manual_steps", NOTHING, None),
        ],
    )
    def test_registered_ceiling(self, handler, ceiling, existence_ceiling) -> None:
        info = get_sieve_handler_registry().get(handler)
        assert info is not None
        assert info.ceiling == ceiling
        assert info.existence_ceiling == existence_ceiling

    def test_unregistered_ceiling_defaults_to_evidence_only(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register("plugin_thing", phase="deterministic", handler_fn=_noop)
        info = reg.get("plugin_thing")
        assert info.ceiling == NOTHING
        assert info.existence_ceiling is None

    def test_ceiling_rejects_unknown_outcome(self) -> None:
        reg = SieveHandlerRegistry()
        with pytest.raises(ValueError):
            reg.register("bad", phase="deterministic", handler_fn=_noop, ceiling={"pass", "maybe"})


class TestEffectiveSet:
    def _info(self, name: str):
        return get_sieve_handler_registry().get(name)

    def test_default_is_ceiling(self) -> None:
        assert effective_outcomes(self._info("file_exists"), HandlerInvocation(handler="file_exists")) == FAIL_ONLY
        assert effective_outcomes(self._info("exec"), HandlerInvocation(handler="exec")) == PASS_FAIL
        assert effective_outcomes(self._info("llm_eval"), HandlerInvocation(handler="llm_eval")) == NOTHING

    def test_existence_selects_existence_ceiling(self) -> None:
        step = HandlerInvocation(handler="file_exists", existence=True)
        assert effective_outcomes(self._info("file_exists"), step) == PASS_FAIL

    def test_concludes_narrows(self) -> None:
        step = HandlerInvocation(handler="exec", concludes=["fail"])
        assert effective_outcomes(self._info("exec"), step) == FAIL_ONLY
        step = HandlerInvocation(handler="exec", concludes=[])
        assert effective_outcomes(self._info("exec"), step) == NOTHING

    def test_concludes_never_widens_without_promotion(self) -> None:
        step = HandlerInvocation(handler="pattern", concludes=["pass", "fail"])
        assert effective_outcomes(self._info("pattern"), step) == FAIL_ONLY

    def test_promotion_widens(self) -> None:
        step = HandlerInvocation(
            handler="pattern",
            concludes=["pass", "fail"],
            promotion={"outcome": "pass", "corpus": "c-1", "note": "0 false PASS"},
        )
        assert effective_outcomes(self._info("pattern"), step) == PASS_FAIL

    def test_legacy_suggestive_is_evidence_only(self) -> None:
        step = HandlerInvocation(handler="exec", authority="suggestive")
        assert effective_outcomes(self._info("exec"), step) == NOTHING

    def test_unknown_existence_on_non_presence_falls_back_to_ceiling(self) -> None:
        step = HandlerInvocation(handler="exec", existence=True)
        assert effective_outcomes(self._info("exec"), step) == PASS_FAIL


class TestSchema:
    def test_concludes_values(self) -> None:
        with pytest.raises(ValidationError):
            HandlerInvocation(handler="exec", concludes=["warn"])

    def test_promotion_outcome_is_pass_only(self) -> None:
        with pytest.raises(ValidationError):
            HandlerInvocation(handler="exec", promotion={"outcome": "fail", "corpus": "c-1"})

    def test_promotion_requires_corpus(self) -> None:
        with pytest.raises(ValidationError):
            HandlerInvocation(handler="pattern", promotion={"outcome": "pass"})

    def test_promotion_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValidationError):
            HandlerInvocation(handler="pattern", promotion={"outcome": "pass", "corpus": "c", "by": "me"})

    def test_step_fields_are_not_handler_config(self) -> None:
        step = HandlerInvocation(handler="pattern", files=["README.md"], concludes=["fail"], existence=True)
        assert "concludes" not in (step.model_extra or {})
        assert "existence" not in (step.model_extra or {})
        assert step.model_extra == {"files": ["README.md"]}


class TestLoadTimeValidation:
    def _reject(self, step: HandlerInvocation, *fragments: str) -> None:
        with pytest.raises(AuthorityViolation) as excinfo:
            validate_step_authority("fw-test", "CTRL-01", [HandlerInvocation(handler="manual"), step])
        text = str(excinfo.value)
        for fragment in ("fw-test", "CTRL-01", "pass[1]", *fragments):
            assert fragment in text, (fragment, text)

    def test_valid_declarations_accepted(self) -> None:
        validate_step_authority(
            "fw-test",
            "CTRL-01",
            [
                HandlerInvocation(handler="file_exists", files=["LICENSE"], existence=True),
                HandlerInvocation(handler="pattern", files=["README.md"], fail_on_miss=True),
                HandlerInvocation(handler="exec", command=["true"], concludes=["fail"]),
                HandlerInvocation(
                    handler="pattern",
                    concludes=["pass", "fail"],
                    promotion={"outcome": "pass", "corpus": "c-1"},
                ),
                HandlerInvocation(handler="llm_eval", prompt="p"),
                HandlerInvocation(handler="manual", steps=["s"]),
            ],
        )

    def test_widening_without_promotion_rejected(self) -> None:
        self._reject(HandlerInvocation(handler="pattern", concludes=["pass"]), "pass")

    def test_existence_on_non_presence_step_rejected(self) -> None:
        self._reject(HandlerInvocation(handler="exec", existence=True), "existence")

    def test_fail_on_miss_on_non_pattern_rejected(self) -> None:
        self._reject(HandlerInvocation(handler="file_exists", fail_on_miss=True), "fail_on_miss")

    def test_fail_on_miss_without_fail_rejected(self) -> None:
        self._reject(HandlerInvocation(handler="pattern", fail_on_miss=True, concludes=[]), "fail_on_miss", "fail")

    def test_fail_on_status_only_on_gh_api(self) -> None:
        self._reject(HandlerInvocation(handler="exec", fail_on_status=[404]), "fail_on_status")

    def test_fail_on_status_without_fail_rejected(self) -> None:
        self._reject(
            HandlerInvocation(handler="gh_api", endpoint="/x", fail_on_status=[404], concludes=["pass"]),
            "fail_on_status",
            "fail",
        )

    def test_promotion_on_model_judgment_rejected(self) -> None:
        self._reject(
            HandlerInvocation(
                handler="llm_eval",
                concludes=["pass"],
                promotion={"outcome": "pass", "corpus": "c-1"},
            ),
            "pass",
        )

    def test_legacy_dispositive_on_empty_ceiling_rejected(self) -> None:
        self._reject(HandlerInvocation(handler="llm_eval", authority="dispositive"), "dispositive")

    def test_legacy_asserted_rejected(self) -> None:
        self._reject(HandlerInvocation(handler="file_exists", authority="asserted"), "asserted")

    def test_legacy_unknown_authority_rejected(self) -> None:
        self._reject(HandlerInvocation(handler="file_exists", authority="definitely"), "definitely")

    def test_unknown_handler_rejected(self) -> None:
        # Feature 044, FR-009: an unregistered step type fails loading.
        self._reject(HandlerInvocation(handler="not_registered_xyz"), "not_registered_xyz")
