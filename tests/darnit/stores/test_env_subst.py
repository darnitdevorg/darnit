"""Unit tests for :func:`darnit.core.env_subst.substitute_dollar_vars`.

Feature 033 T007: covers the extracted helper's contract plus regression
tests reproducing the previous inputs from feature 025 (mcp handler args)
and feature 031 (mcp env block) to prove behavior is unchanged after the
T005/T006 migrations.
"""

from __future__ import annotations

import pytest

from darnit.core.env_subst import substitute_dollar_vars


class TestBasicSubstitution:
    def test_single_var(self):
        assert substitute_dollar_vars("$FOO", {"FOO": "bar"}) == "bar"

    def test_multiple_vars(self):
        assert (
            substitute_dollar_vars("$A/$B", {"A": "1", "B": "2"}) == "1/2"
        )

    def test_var_mixed_with_literal(self):
        assert (
            substitute_dollar_vars("hello $NAME world", {"NAME": "you"})
            == "hello you world"
        )

    def test_var_at_start_middle_end(self):
        env = {"X": "x"}
        assert substitute_dollar_vars("$Xabc", env) == ""  # $Xabc is a whole varname
        assert substitute_dollar_vars("$X abc", env) == "x abc"
        assert substitute_dollar_vars("$X.abc", env) == "x.abc"


class TestEscape:
    def test_double_dollar_is_literal(self):
        assert substitute_dollar_vars("$$FOO", {"FOO": "bar"}) == "$FOO"

    def test_double_dollar_no_env(self):
        assert substitute_dollar_vars("$$", {}) == "$"

    def test_double_dollar_mixed(self):
        assert (
            substitute_dollar_vars("cost: $$5 for $FOO", {"FOO": "socks"})
            == "cost: $5 for socks"
        )


class TestTokenTerminator:
    def test_slash_terminates_name(self):
        assert (
            substitute_dollar_vars("$FOO/bar", {"FOO": "one"}) == "one/bar"
        )

    def test_dot_terminates_name(self):
        assert (
            substitute_dollar_vars("$FOO.tar", {"FOO": "one"}) == "one.tar"
        )

    def test_alphanumeric_stays_in_name(self):
        # $OWNER123 is a single varname; verify substitution.
        assert (
            substitute_dollar_vars("$OWNER123", {"OWNER123": "octo"})
            == "octo"
        )

    def test_underscore_stays_in_name(self):
        assert (
            substitute_dollar_vars("$FOO_BAR", {"FOO_BAR": "yes"}) == "yes"
        )


class TestLoneDollar:
    def test_lone_dollar_kept(self):
        assert substitute_dollar_vars("$", {}) == "$"

    def test_dollar_followed_by_non_name(self):
        assert substitute_dollar_vars("$!", {}) == "$!"


class TestMissingModes:
    def test_missing_empty_default(self):
        assert substitute_dollar_vars("$UNSET", {}) == ""

    def test_missing_empty_explicit(self):
        assert substitute_dollar_vars("$UNSET", {}, missing="empty") == ""

    def test_missing_raise(self):
        with pytest.raises(KeyError) as exc:
            substitute_dollar_vars("$UNSET", {}, missing="raise")
        assert exc.value.args[0] == "UNSET"

    def test_missing_leave(self):
        assert (
            substitute_dollar_vars("$UNSET", {}, missing="leave") == "$UNSET"
        )

    def test_missing_leave_mixed(self):
        assert (
            substitute_dollar_vars(
                "hi $OWNER and $UNKNOWN", {"OWNER": "octo"}, missing="leave"
            )
            == "hi octo and $UNKNOWN"
        )


class TestEnvDefault:
    def test_default_env_is_os_environ(self, monkeypatch):
        monkeypatch.setenv("DARNIT_TEST_VAR", "from-env")
        assert substitute_dollar_vars("$DARNIT_TEST_VAR") == "from-env"

    def test_explicit_env_overrides_os_environ(self, monkeypatch):
        monkeypatch.setenv("DARNIT_TEST_VAR", "from-env")
        assert (
            substitute_dollar_vars("$DARNIT_TEST_VAR", {"DARNIT_TEST_VAR": "explicit"})
            == "explicit"
        )


# ---------------------------------------------------------------------------
# Regression: feature 025 (mcp handler args via _substitute_mcp_args)
# ---------------------------------------------------------------------------


class TestFeature025Regression:
    """The mcp-handler-args helper uses substitute_dollar_vars with the four
    context-derived tokens (OWNER/REPO/BRANCH/PATH) and ``missing="leave"``
    for unknown tokens. Reproduce common templates from that codepath."""

    def test_repo_url_template(self):
        env = {"OWNER": "octo", "REPO": "hello", "BRANCH": "main", "PATH": "/tmp"}
        assert (
            substitute_dollar_vars(
                "github.com/$OWNER/$REPO", env, missing="leave"
            )
            == "github.com/octo/hello"
        )

    def test_unknown_token_left_literal(self):
        env = {"OWNER": "octo"}
        assert (
            substitute_dollar_vars(
                "$OWNER/$UNKNOWN_TOKEN", env, missing="leave"
            )
            == "octo/$UNKNOWN_TOKEN"
        )


# ---------------------------------------------------------------------------
# Regression: feature 031 (mcp pool env block)
# ---------------------------------------------------------------------------


class TestFeature031Regression:
    """The mcp-pool env block uses substitute_dollar_vars with the pool's
    curated env and ``missing="empty"`` for unset vars."""

    def test_env_value_substituted(self):
        env = {"GH_TOKEN": "ghp_realtoken", "HOME": "/h"}
        assert (
            substitute_dollar_vars("$GH_TOKEN", env, missing="empty")
            == "ghp_realtoken"
        )

    def test_env_unset_var_empty(self):
        env = {"GH_TOKEN": "ghp_realtoken"}
        assert substitute_dollar_vars("$UNSET_VAR", env, missing="empty") == ""

    def test_env_composed_value(self):
        env = {"HOME": "/h", "USER": "octo"}
        assert (
            substitute_dollar_vars("$HOME/$USER/.config", env)
            == "/h/octo/.config"
        )
