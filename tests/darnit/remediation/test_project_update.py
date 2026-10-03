"""Tests for project_update remediation support.

Tests that the RemediationExecutor correctly applies project_update
after successful remediations, and that the project_update handler, applied
by the executor, works for nested dotted paths.
"""

import pytest

from darnit.config.framework_schema import (
    HandlerInvocation,
    ProjectUpdateRemediationConfig,
    RemediationConfig,
)
from darnit.remediation.executor import (
    RemediationExecutor,
    _set_nested_value,
    plan_project_update,
)


class TestSetNestedValue:
    """Tests for the _set_nested_value helper."""

    def test_single_key_dict(self):
        """Set a top-level key in a dict."""
        obj = {}
        _set_nested_value(obj, "key", "value")
        assert obj["key"] == "value"

    def test_nested_dict(self):
        """Set a nested key in a dict."""
        obj = {}
        _set_nested_value(obj, "a.b.c", "deep")
        assert obj["a"]["b"]["c"] == "deep"

    def test_existing_intermediate(self):
        """Set a nested key when intermediate dicts exist."""
        obj = {"a": {"b": {}}}
        _set_nested_value(obj, "a.b.c", "value")
        assert obj["a"]["b"]["c"] == "value"

    def test_overwrite_value(self):
        """Overwrite an existing value."""
        obj = {"a": {"b": "old"}}
        _set_nested_value(obj, "a.b", "new")
        assert obj["a"]["b"] == "new"


class TestProjectUpdateRemediationConfig:
    """Tests for ProjectUpdateRemediationConfig schema."""

    def test_create_with_set(self):
        """Create config with set values."""
        config = ProjectUpdateRemediationConfig(
            set={"security.policy.path": "SECURITY.md"}
        )
        assert config.set == {"security.policy.path": "SECURITY.md"}

    def test_create_empty(self):
        """Create config with no set values."""
        config = ProjectUpdateRemediationConfig()
        assert config.set == {}

    def test_create_if_missing_default(self):
        """create_if_missing defaults to True."""
        config = ProjectUpdateRemediationConfig()
        assert config.create_if_missing is True


class TestExecutorProjectUpdate:
    """Tests for RemediationExecutor project_update integration."""

    def test_project_update_applied_after_handler(self, tmp_path):
        """project_update is applied after successful handler execution."""
        from darnit.sieve.handler_registry import (
            HandlerResult,
            HandlerResultStatus,
            get_sieve_handler_registry,
        )

        # Register a test handler that always succeeds
        registry = get_sieve_handler_registry()

        def _test_handler(config, ctx):
            return HandlerResult(status=HandlerResultStatus.PASS, message="OK")

        # The handler has no side effects; without supports_plan it would need
        # individual approval in an apply (FR-023, 043 US5).
        registry.register(
            "_test_pu_handler", "deterministic", _test_handler,
            ceiling={"pass", "fail"},
            supports_plan=True,
        )

        try:
            executor = RemediationExecutor(
                local_path=str(tmp_path),
                owner="testowner",
                repo="testrepo",
            )

            config = RemediationConfig(
                handlers=[
                    HandlerInvocation(handler="_test_pu_handler"),
                ],
                project_update=ProjectUpdateRemediationConfig(
                    set={"security.policy.path": "SECURITY.md"},
                ),
            )

            result = executor.execute("TEST-01", config, dry_run=False)
            assert result.success
            assert "project_update" in result.details
        finally:
            registry._handlers.pop("_test_pu_handler", None)

    def test_project_update_dry_run_preview(self, tmp_path):
        """Dry run shows project_update preview.

        The handler carries content: a preview runs the apply's logic, so a
        missing template would fail it (FR-021).
        """
        executor = RemediationExecutor(
            local_path=str(tmp_path),
            owner="testowner",
            repo="testrepo",
        )

        config = RemediationConfig(
            handlers=[
                HandlerInvocation(
                    handler="file_create",
                    path="README.md",
                    content="# Readme\n",
                ),
            ],
            project_update=ProjectUpdateRemediationConfig(
                set={"documentation.readme.path": "README.md"},
            ),
        )

        result = executor.execute("TEST-01", config, dry_run=True)
        assert result.success
        assert "project_update" in result.details
        assert "would set" in result.details["project_update"]

    def test_project_update_not_applied_on_failure(self, tmp_path):
        """project_update is NOT applied when remediation fails."""
        executor = RemediationExecutor(
            local_path=str(tmp_path),
            owner="testowner",
            repo="testrepo",
        )

        # Config with a handler that won't be found → failure
        config = RemediationConfig(
            handlers=[
                HandlerInvocation(handler="_nonexistent_handler_xyz"),
            ],
            project_update=ProjectUpdateRemediationConfig(
                set={"documentation.readme.path": "README.md"},
            ),
        )

        result = executor.execute("TEST-01", config, dry_run=False)
        assert not result.success
        # project_update should NOT be in details
        assert "project_update" not in result.details

    def test_project_update_without_handlers(self, tmp_path):
        """project_update alone (no handlers) doesn't run."""
        executor = RemediationExecutor(
            local_path=str(tmp_path),
            owner="testowner",
            repo="testrepo",
        )

        # Config with only project_update, no handlers
        config = RemediationConfig(
            project_update=ProjectUpdateRemediationConfig(
                set={"key": "value"},
            ),
        )

        # Should fall through to "no remediation handlers configured"
        result = executor.execute("TEST-01", config, dry_run=False)
        assert not result.success
        assert result.remediation_type == "none"


def _apply_update(path, updates: dict, *, create: bool = True):
    config = RemediationConfig(
        handlers=[HandlerInvocation(handler="project_update", updates=updates, create_if_missing=create)]
    )
    return RemediationExecutor(local_path=str(path), owner="o", repo="r").execute("TEST-01", config, dry_run=False)


class TestProjectUpdateHandler:
    """The project_update handler plans the change; the executor writes it."""

    def test_creates_project_dir(self, tmp_path):
        """Creates .project/ directory if it doesn't exist."""
        result = _apply_update(tmp_path, {"security.policy.path": "SECURITY.md"})

        assert result.changed
        assert (tmp_path / ".project").exists()

    def test_skip_if_no_project_and_not_create(self, tmp_path):
        """Skip if no .project/ and create_if_missing=False."""
        result = _apply_update(tmp_path, {"security.policy.path": "SECURITY.md"}, create=False)

        assert not result.changed
        assert not (tmp_path / ".project").exists()

    def test_empty_updates_change_nothing(self, tmp_path):
        result = _apply_update(tmp_path, {})

        assert not result.changed
        assert not (tmp_path / ".project").exists()

    def test_does_not_overwrite_existing_config_on_validation_failure(self, tmp_path):
        """An invalid project file blocks the update; nothing is written (feature 042, FR-019).

        The update used to replace such a file with a blank
        ProjectConfig(name="unknown"), destroying existing data.
        """
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        project_yaml = project_dir / "project.yaml"
        project_yaml.write_text("name: test\nmaturity_log:\n  - phase: sandbox\n    date: not-a-date\n")
        darnit_yaml = project_dir / "darnit.yaml"
        darnit_yaml.write_text("context:\n  maintainers:\n  - '@alice'\n  - '@bob'\n")
        originals = {path: path.read_text() for path in (project_yaml, darnit_yaml)}

        with pytest.raises(ValueError, match="maturity_log"):
            plan_project_update(str(tmp_path), {"security.policy.path": "SECURITY.md"})
        result = _apply_update(tmp_path, {"security.policy.path": "SECURITY.md"})

        assert not result.success
        assert "maturity_log" in result.details["handlers"][0]["message"]
        assert {path: path.read_text() for path in originals} == originals
