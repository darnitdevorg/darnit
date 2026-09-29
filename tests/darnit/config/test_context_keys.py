"""Canonical context key names, vocabularies, and value digests (feature 042, FR-018, research R9)."""

from __future__ import annotations

import pytest

from darnit.config.context_keys import canonical_key, coerce_value, in_vocabulary, normalize_value, value_digest
from darnit.config.context_schema import ContextDefinition, ContextType


@pytest.mark.unit
class TestCanonicalNames:
    @pytest.mark.parametrize("stored", ["ci.provider", "provider", "ci_provider"])
    def test_ci_provider_names(self, stored: str) -> None:
        assert canonical_key(stored) == "ci_provider"

    def test_other_keys_unchanged(self) -> None:
        assert canonical_key("maintainers") == "maintainers"
        assert canonical_key("csl_code_license") == "csl_code_license"


@pytest.mark.unit
class TestVocabulary:
    @pytest.mark.parametrize(
        ("legacy", "canonical"),
        [
            ("github_actions", "github"),
            ("gitlab_ci", "gitlab"),
            ("azure_pipelines", "azure"),
            ("bitbucket_pipelines", "other"),
            ("github", "github"),
        ],
    )
    def test_legacy_ci_provider_spellings(self, legacy: str, canonical: str) -> None:
        assert normalize_value("ci_provider", legacy) == canonical

    def test_unknown_ci_provider_is_no_value(self) -> None:
        assert normalize_value("ci_provider", "unknown") is None

    def test_legacy_spelling_under_legacy_name(self) -> None:
        assert normalize_value(canonical_key("provider"), "gitlab_ci") == "gitlab"

    def test_vocabulary_comes_from_the_definition(self) -> None:
        definition = ContextDefinition(type=ContextType.ENUM, prompt="?", values=["github", "gitlab"])

        assert in_vocabulary("github", definition)
        assert not in_vocabulary("github_actions", definition)

    def test_non_enum_has_no_vocabulary(self) -> None:
        definition = ContextDefinition(type=ContextType.STRING, prompt="?")

        assert in_vocabulary("anything", definition)

    @pytest.mark.parametrize(("answer", "value"), [("true", True), ("Yes", True), ("false", False), ("no", False)])
    def test_boolean_answers(self, answer: str, value: bool) -> None:
        assert coerce_value(ContextDefinition(type=ContextType.BOOLEAN, prompt="?"), answer) is value

    def test_boolean_answer_outside_vocabulary(self) -> None:
        with pytest.raises(ValueError):
            coerce_value(ContextDefinition(type=ContextType.BOOLEAN, prompt="?"), "maybe")


@pytest.mark.unit
class TestValueDigest:
    def test_format(self) -> None:
        digest = value_digest("maintainers", ["@alice", "@bob"])

        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64

    def test_maintainers_order_does_not_matter(self) -> None:
        assert value_digest("maintainers", ["@alice", "@bob"]) == value_digest("maintainers", ["@bob", "@alice"])

    @pytest.mark.parametrize(
        ("key", "first", "second"),
        [
            ("maintainers", ["@alice", "@bob"], ["@alice", "@carol"]),
            ("maintainers", ["@alice"], ["@alice", "@bob"]),
            ("security_contact", "security@a.example", "security@b.example"),
            ("has_releases", True, False),
            ("governance_model", "bdfl", "foundation"),
        ],
    )
    def test_any_content_change_changes_it(self, key: str, first: object, second: object) -> None:
        assert value_digest(key, first) != value_digest(key, second)

    def test_stable(self) -> None:
        assert value_digest("security_contact", "security@a.example") == value_digest(
            "security_contact", "security@a.example"
        )

    def test_uses_the_canonical_vocabulary(self) -> None:
        assert value_digest("ci_provider", "github_actions") == value_digest("ci_provider", "github")

    def test_key_is_part_of_nothing_but_the_value(self) -> None:
        assert value_digest("has_releases", True) == value_digest("is_library", True)
