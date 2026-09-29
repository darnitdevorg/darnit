"""Tests for context storage abstraction layer.

Tests the unified interface for loading and saving context values
with provenance tracking.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import OriginKind, Standing
from darnit.config.context_storage import (
    _run_detect_pipeline,
    get_context_definitions,
    get_pending_context,
)
from darnit.config.context_writes import record_value_confirmation, record_value_confirmations
from darnit.config.operator.schema import OperatorConfig

# Feature 042 (FR-002, FR-009, FR-011): save_context_value/save_context_values
# wrote bare values with no record of who confirmed them and are gone. Values
# are written only by the single writer, as confirmations.
#
# Feature 042 (FR-006): the legacy readers load_context, load_stored_context,
# get_context_value, get_raw_value, and is_context_confirmed returned stored
# values as user-confirmed and are gone. Stored values are read only by the
# resolver; consumers read its usable mapping, and a stored value without a
# confirmation record is a candidate.
TARGET = "github.com/example-org/project"
TRUSTING = OperatorConfig.model_validate({"schema_version": 1, "trust": {"repos": [TARGET]}})


def save_context_value(local_path: str, key: str, value: object):
    result = record_value_confirmation(local_path, key, value, target=TARGET, operator=TRUSTING, env={})
    assert result.outcome == "confirmed", result
    return result


def save_context_values(local_path: str, values: dict):
    return record_value_confirmations(local_path, values, target=TARGET, operator=TRUSTING, env={})


def _resolved(local_path: str):
    return resolve_context(local_path, detect=False, operator=OperatorConfig.model_validate({"schema_version": 1}))


def usable(local_path: str) -> dict:
    return _resolved(local_path).usable()


class TestStoredValues:
    """Stored values are read by the resolver, under canonical names, as candidates."""

    def test_empty_repo(self, tmp_path: Path) -> None:
        assert usable(str(tmp_path)) == {}

    def test_stored_values_are_candidates(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  has_releases: true
  has_subprojects: false
  is_library: true
  ci_provider: github
""")
        resolved = _resolved(str(tmp_path))

        assert resolved.usable() == {}
        for key, value in {
            "has_releases": True,
            "has_subprojects": False,
            "is_library": True,
            "ci_provider": "github",
        }.items():
            assert resolved.values[key].standing is Standing.CANDIDATE
            assert resolved.values[key].value == value
            assert resolved.values[key].origin.kind is OriginKind.STORED_UNCONFIRMED

    def test_governance_and_security_values(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  maintainers:
    - "@alice"
    - "@bob"
  governance_model: democracy
  security_contact: security@real-project.org
""")
        resolved = _resolved(str(tmp_path))

        assert resolved.values["maintainers"].value == ["@alice", "@bob"]
        assert resolved.values["governance_model"].value == "democracy"
        assert resolved.values["security_contact"].value == "security@real-project.org"
        assert resolved.usable() == {}

    def test_maintainers_as_path(self, tmp_path: Path) -> None:
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "darnit.yaml").write_text("context:\n  maintainers: MAINTAINERS.md\n")

        assert _resolved(str(tmp_path)).values["maintainers"].value == "MAINTAINERS.md"


class TestSaveContextValue:
    """Tests for save_context_value function."""

    def test_save_new_value(self, tmp_path: Path) -> None:
        """Test saving a new context value."""
        # Initialize git repo for detection
        (tmp_path / ".git").mkdir()

        result = save_context_value(str(tmp_path), "has_releases", True)

        assert (tmp_path / result.file).exists()
        assert not (tmp_path / ".project" / "project.yaml").exists()

        assert usable(str(tmp_path))["has_releases"] is True

    def test_save_updates_existing(self, tmp_path: Path) -> None:
        """Test that saving updates existing config."""
        (tmp_path / ".git").mkdir()
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: existing-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  has_releases: false
""")

        save_context_value(str(tmp_path), "has_releases", True)

        assert usable(str(tmp_path))["has_releases"] is True

        # Verify project.yaml untouched (FR-020, FR-021)
        assert (project_dir / "project.yaml").read_text() == "name: existing-project\n"

    def test_save_unknown_key_is_refused(self, tmp_path: Path) -> None:
        """A key the framework does not define is not written (FR-018; was: saved under `custom`)."""
        (tmp_path / ".git").mkdir()

        result = record_value_confirmation(
            str(tmp_path), "unknown_key", "value", target=TARGET, operator=TRUSTING, env={}
        )

        assert result.outcome == "refused"
        assert not (tmp_path / ".project").exists()


class TestSaveContextValues:
    """Tests for save_context_values function."""

    def test_save_multiple_values(self, tmp_path: Path) -> None:
        """Test saving multiple values at once."""
        (tmp_path / ".git").mkdir()

        save_context_values(
            str(tmp_path),
            {
                "has_releases": True,
                "is_library": False,
                "ci_provider": "github",
            },
        )

        assert usable(str(tmp_path)) == {"has_releases": True, "is_library": False, "ci_provider": "github"}


class TestGetContextDefinitions:
    """Tests for get_context_definitions function."""

    def test_loads_from_framework(self) -> None:
        """Test loading definitions from framework TOML."""
        # Use the actual repo path (current working directory should work)
        definitions = get_context_definitions(".")

        # Should have definitions from openssf-baseline.toml
        assert len(definitions) > 0

        # Check specific definitions exist
        assert "maintainers" in definitions
        assert "security_contact" in definitions
        assert "ci_provider" in definitions

    def test_definition_structure(self) -> None:
        """Test that definitions have correct structure."""
        definitions = get_context_definitions(".")

        if "maintainers" in definitions:
            maintainers = definitions["maintainers"]
            assert maintainers.type == "list_or_path"
            assert "maintainer" in maintainers.prompt.lower()
            assert len(maintainers.affects) > 0


class TestGetPendingContext:
    """Tests for get_pending_context function."""

    def test_returns_pending_for_empty_config(self, tmp_path: Path) -> None:
        """Test that all context is pending when no config exists."""
        (tmp_path / ".git").mkdir()

        # Note: This will try to load framework config which may not work
        # in a temp directory without proper setup
        pending = get_pending_context(str(tmp_path))

        # Should return empty list if framework can't be loaded
        # (which is expected in temp dir)
        assert isinstance(pending, list)

    def test_excludes_confirmed_context(self, tmp_path: Path) -> None:
        """Test that confirmed context is excluded from pending."""
        (tmp_path / ".git").mkdir()
        save_context_values(str(tmp_path), {"has_releases": True, "ci_provider": "github"})

        pending = get_pending_context(str(tmp_path))

        # has_releases and ci_provider should not be in pending
        pending_keys = [p.key for p in pending]
        assert "has_releases" not in pending_keys
        assert "ci_provider" not in pending_keys

    def test_stored_values_without_records_stay_pending(self, tmp_path: Path) -> None:
        """Feature 042 (FR-010): a bare stored value is a candidate, not a confirmation."""
        (tmp_path / ".git").mkdir()
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "darnit.yaml").write_text("context:\n  governance_model: bdfl\n  maintainers: ['@a']\n")

        pending = {p.key: p for p in get_pending_context(str(tmp_path))}

        assert pending["maintainers"].candidate.origin.kind == "stored_unconfirmed"
        assert pending["governance_model"].candidate.value == "bdfl"

    def test_writes_nothing(self, tmp_path: Path) -> None:
        """Feature 042 (FR-001): listing pending context never writes."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".github" / "workflows").mkdir(parents=True)

        get_pending_context(str(tmp_path))

        assert not (tmp_path / ".project").exists()


class TestSaveNewContextFields:
    """Tests for saving new governance and security context fields."""

    def test_save_maintainers_list(self, tmp_path: Path) -> None:
        """Test saving maintainers as a list."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "maintainers", ["@user1", "@user2"])

        assert usable(str(tmp_path))["maintainers"] == ["@user1", "@user2"]

    def test_save_maintainers_path(self, tmp_path: Path) -> None:
        """Test saving maintainers as a file path."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "maintainers", "MAINTAINERS.md")

        assert usable(str(tmp_path))["maintainers"] == "MAINTAINERS.md"

    def test_save_security_contact(self, tmp_path: Path) -> None:
        """Test saving security contact."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "security_contact", "security@real-project.org")

        assert usable(str(tmp_path))["security_contact"] == "security@real-project.org"

    def test_save_governance_model(self, tmp_path: Path) -> None:
        """Test saving governance model."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "governance_model", "bdfl")

        assert usable(str(tmp_path))["governance_model"] == "bdfl"

    def test_maintainers_round_trip(self, tmp_path: Path) -> None:
        """Confirmed maintainers read back as a confirmed, usable value."""
        (tmp_path / ".git").mkdir()
        maintainers = ["@alice", "@bob", "@charlie"]

        save_context_value(str(tmp_path), "maintainers", maintainers)

        resolved = _resolved(str(tmp_path))
        assert resolved.values["maintainers"].standing is Standing.CONFIRMED
        assert resolved.usable()["maintainers"] == maintainers


class TestRunDetectPipelineHasReleases:
    """Tests for has_releases detect pipeline (FR-2)."""

    def _make_invocation(self, **kwargs):
        from darnit.config.framework_schema import HandlerInvocation

        return HandlerInvocation(**kwargs)

    def test_detects_changelog(self, tmp_path: Path) -> None:
        """has_releases detected when CHANGELOG.md exists."""
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n## v1.0.0\n")
        pipeline = [
            self._make_invocation(
                handler="file_exists", files=["CHANGELOG.md", "CHANGELOG", "CHANGES.md", "CHANGES"], value_if_pass=True
            ),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is True
        assert "file_exists" in result.detection_method

    def test_detects_changes_file(self, tmp_path: Path) -> None:
        """has_releases detected when CHANGES file exists."""
        (tmp_path / "CHANGES").write_text("Changes\n")
        pipeline = [
            self._make_invocation(
                handler="file_exists", files=["CHANGELOG.md", "CHANGELOG", "CHANGES.md", "CHANGES"], value_if_pass=True
            ),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is True

    def test_detects_release_workflow(self, tmp_path: Path) -> None:
        """has_releases detected when release workflow exists."""
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "release.yml").write_text("on: release\n")
        pipeline = [
            self._make_invocation(handler="file_exists", files=[".github/workflows/release*"], value_if_pass=True),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is True

    def test_no_evidence_returns_none(self, tmp_path: Path) -> None:
        """has_releases returns None when no release evidence exists."""
        pipeline = [
            self._make_invocation(handler="file_exists", files=[".github/workflows/release*"], value_if_pass=True),
            self._make_invocation(handler="file_exists", files=["CHANGELOG.md", "CHANGELOG"], value_if_pass=True),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is None

    def test_value_if_fail_fires_on_last_detector_fail(self, tmp_path: Path) -> None:
        """When the last detector fails and has value_if_fail, it fires.

        Reproducibility fix: a flaky `gh release list` (non-zero exit, empty
        stdout with an expr, or ERROR) previously left the key missing from
        context, which caused when-clause matching to skip controls
        nondeterministically across audit runs. With value_if_fail wired,
        the failure resolves to a stable false.
        """
        pipeline = [
            self._make_invocation(handler="file_exists", files=[".github/workflows/release*"], value_if_pass=True),
            self._make_invocation(handler="file_exists", files=["CHANGELOG.md", "CHANGELOG"], value_if_pass=True),
            self._make_invocation(
                handler="exec",
                command=["false"],  # deterministic non-zero exit
                pass_exit_codes=[0],
                value_if_pass=True,
                value_if_fail=False,
            ),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is False
        assert "fail_fallback" in result.detection_method

    def test_value_if_fail_fires_when_expr_evaluates_false(self, tmp_path: Path) -> None:
        """PASS-with-expr-false (INCONCLUSIVE post-CEL) also triggers value_if_fail.

        This is the "gh release list succeeded but returned empty stdout"
        case -- the repo genuinely has no releases. Pre-fix: INCONCLUSIVE
        propagated to end-of-chain and returned None. Post-fix: value_if_fail
        stabilises this to false.
        """
        with patch("darnit.sieve.builtin_handlers.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            pipeline = [
                self._make_invocation(
                    handler="exec",
                    command=["gh", "release", "list", "--repo", "$OWNER/$REPO", "--limit", "1"],
                    pass_exit_codes=[0],
                    expr='output.stdout != ""',
                    value_if_pass=True,
                    value_if_fail=False,
                ),
            ]
            result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is False
        assert "fail_fallback" in result.detection_method

    def test_value_if_fail_short_circuits_middle_detector(self, tmp_path: Path) -> None:
        """value_if_fail on a middle detector fires and skips subsequent detectors.

        Documents the short-circuit semantic: if a TOML author sets
        value_if_fail on a non-last detector, later detectors are not tried
        when that detector fails. If a chain-level fallback is desired
        instead, put value_if_fail on the last detector.
        """
        (tmp_path / "CHANGELOG.md").write_text("# changelog\n")
        pipeline = [
            self._make_invocation(
                handler="exec",
                command=["false"],
                pass_exit_codes=[0],
                value_if_pass=True,
                value_if_fail=False,
            ),
            # This later detector WOULD pass but should not be reached.
            self._make_invocation(handler="file_exists", files=["CHANGELOG.md"], value_if_pass=True),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is False, "short-circuit: middle detector's value_if_fail must fire"

    def test_earlier_pass_still_wins_over_later_value_if_fail(self, tmp_path: Path) -> None:
        """PASS-first-wins semantics preserved: earlier detector's success skips fail-fallback.

        Guards against a regression where the fix accidentally makes
        value_if_fail from later detectors override earlier successes.
        """
        (tmp_path / "CHANGELOG.md").write_text("# changelog\n")
        pipeline = [
            self._make_invocation(handler="file_exists", files=["CHANGELOG.md"], value_if_pass=True),
            self._make_invocation(
                handler="exec",
                command=["false"],
                pass_exit_codes=[0],
                value_if_pass=True,
                value_if_fail=False,
            ),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is True


class TestRunDetectPipelinePlatform:
    """Tests for platform detect pipeline (FR-3)."""

    def _make_invocation(self, **kwargs):
        from darnit.config.framework_schema import HandlerInvocation

        return HandlerInvocation(**kwargs)

    @patch("darnit.sieve.builtin_handlers.subprocess.run")
    def test_detects_github_from_remote(self, mock_run, tmp_path: Path) -> None:
        """platform detected as 'github' when remote contains github.com."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/owner/repo.git\n",
            stderr="",
        )
        pipeline = [
            self._make_invocation(
                handler="exec",
                command=["git", "remote", "get-url", "origin"],
                pass_exit_codes=[0],
                expr='output.stdout.contains("github.com")',
                value_if_pass="github",
            ),
        ]
        result = _run_detect_pipeline("platform", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value == "github"

    @patch("darnit.sieve.builtin_handlers.subprocess.run")
    def test_detects_gitlab_from_remote(self, mock_run, tmp_path: Path) -> None:
        """platform detected as 'gitlab' when remote contains gitlab.com."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://gitlab.com/owner/repo.git\n",
            stderr="",
        )
        pipeline = [
            self._make_invocation(
                handler="exec",
                command=["git", "remote", "get-url", "origin"],
                pass_exit_codes=[0],
                expr='output.stdout.contains("github.com")',
                value_if_pass="github",
            ),
            self._make_invocation(
                handler="exec",
                command=["git", "remote", "get-url", "origin"],
                pass_exit_codes=[0],
                expr='output.stdout.contains("gitlab.com")',
                value_if_pass="gitlab",
            ),
        ]
        result = _run_detect_pipeline("platform", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value == "gitlab"

    def test_falls_back_to_github_dir(self, tmp_path: Path) -> None:
        """platform detected as 'github' from .github/ directory when no remote."""
        (tmp_path / ".github").mkdir()
        pipeline = [
            self._make_invocation(handler="file_exists", files=[".github"], value_if_pass="github"),
        ]
        result = _run_detect_pipeline("platform", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value == "github"

    @patch("darnit.sieve.builtin_handlers.subprocess.run")
    def test_no_remote_no_github_dir_returns_none(self, mock_run, tmp_path: Path) -> None:
        """platform returns None when no remote and no .github/ directory."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        pipeline = [
            self._make_invocation(
                handler="exec",
                command=["sh", "-c", "git remote get-url origin 2>/dev/null | grep -q github.com"],
                pass_exit_codes=[0],
                value_if_pass="github",
            ),
            self._make_invocation(
                handler="exec",
                command=["sh", "-c", "git remote get-url origin 2>/dev/null | grep -q gitlab.com"],
                pass_exit_codes=[0],
                value_if_pass="gitlab",
            ),
            self._make_invocation(handler="file_exists", files=[".github"], value_if_pass="github"),
        ]
        result = _run_detect_pipeline("platform", pipeline, str(tmp_path), "owner", "repo")
        assert result is None
