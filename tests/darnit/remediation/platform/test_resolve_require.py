"""Tests for platform requirement resolution and context placeholder validation."""

from __future__ import annotations

import logging

import pytest

from darnit.config.framework_schema import FrameworkConfig
from darnit.remediation.platform import (
    PlatformRequirement,
    UnresolvedContextError,
    platform_requests,
    resolve_platform_require,
)


@pytest.mark.unit
def test_resolve_platform_require_resolved_list() -> None:
    """Verify context list resolves to clean list of required checks."""
    require = {"require_status_checks": ["${context.required_status_checks}"]}
    context = {"required_status_checks": ["build", "test", "lint"]}

    resolved = resolve_platform_require(require, context)
    assert resolved == {"require_status_checks": ["build", "test", "lint"]}


@pytest.mark.unit
def test_resolve_platform_require_string_with_commas() -> None:
    """Verify matrix check names containing commas and parentheses are preserved without splitting."""
    require = {"require_status_checks": ["${context.required_status_checks}"]}
    matrix_check = "test (ubuntu-latest, 3.12)"
    context = {"required_status_checks": [matrix_check, "build"]}

    resolved = resolve_platform_require(require, context)
    assert resolved == {"require_status_checks": ["test (ubuntu-latest, 3.12)", "build"]}
    assert len(resolved["require_status_checks"]) == 2
    assert resolved["require_status_checks"][0] == matrix_check

    # Also verify when context value is passed as a single string
    context_str = {"required_status_checks": matrix_check}
    resolved_str = resolve_platform_require(require, context_str)
    assert resolved_str == {"require_status_checks": [matrix_check]}


@pytest.mark.unit
def test_resolve_platform_require_missing_key_raises() -> None:
    """Verify missing or unconfirmed key raises UnresolvedContextError (ValueError) and never leaks placeholder."""
    require = {"require_status_checks": ["${context.required_status_checks}"]}

    with pytest.raises(UnresolvedContextError, match="Unresolved context placeholder") as exc:
        resolve_platform_require(require, {})
    assert isinstance(exc.value, ValueError)
    assert exc.value.key == "required_status_checks"
    assert exc.value.placeholder == "${context.required_status_checks}"

    with pytest.raises(UnresolvedContextError):
        resolve_platform_require(require, None)

    with pytest.raises(UnresolvedContextError):
        resolve_platform_require(require, {"other_key": "val"})


@pytest.mark.unit
def test_resolve_platform_require_empty_value_raises() -> None:
    """Verify empty list or empty string in context raises ValueError."""
    require = {"require_status_checks": ["${context.required_status_checks}"]}

    with pytest.raises(ValueError, match="empty list"):
        resolve_platform_require(require, {"required_status_checks": []})

    with pytest.raises(ValueError, match="empty string"):
        resolve_platform_require(require, {"required_status_checks": ""})


@pytest.mark.unit
def test_model_check_requirement_rejects_string() -> None:
    """Verify PlatformRequirement model validator rejects string values (reverted relaxation)."""
    with pytest.raises(ValueError, match="non-empty list"):
        PlatformRequirement(
            target="branch_protection",
            require={"require_status_checks": "${context.required_status_checks}"},
        )


@pytest.mark.unit
def test_platform_requests_logs_unconfirmed_and_invalid_requirements(caplog: pytest.LogCaptureFixture) -> None:
    """Verify platform_requests logs deferred/dropped placeholder requirements cleanly."""
    framework = FrameworkConfig.model_validate(
        {
            "metadata": {"name": "t", "display_name": "T", "version": "1"},
            "controls": {
                "QA-1": {
                    "name": "QA",
                    "description": "Status checks",
                    "remediation": {
                        "handlers": [
                            {
                                "handler": "platform_setting",
                                "target": "branch_protection",
                                "require": {"require_status_checks": ["${context.required_status_checks}"]},
                            }
                        ]
                    },
                }
            },
        }
    )

    with caplog.at_level(logging.DEBUG, logger="darnit.remediation.platform.engine"):
        assert platform_requests(framework, ["QA-1"], context={}) == []
        assert any("no usable context available" in r.message for r in caplog.records)

        caplog.clear()
        assert platform_requests(framework, ["QA-1"], context={"other": "x"}) == []
        assert any("unconfirmed context key 'required_status_checks'" in r.message for r in caplog.records)

        caplog.clear()
        assert platform_requests(framework, ["QA-1"], context={"required_status_checks": []}) == []
        assert any(
            r.levelno == logging.WARNING and "Dropping invalid platform requirement" in r.message
            for r in caplog.records
        )

