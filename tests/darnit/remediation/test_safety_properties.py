"""Every remediation safety property is enforced or absent (feature 043 US5, T049; SC-007, FR-024, FR-025).

framework-design 4.1 and 15.3: ``safe = false`` means every step that may
act requires individual approval by its ``PlanItem.digest`` in a batch apply,
under every remediation policy including ``auto``. ``requires_confirmation``,
``dry_run_supported`` and ``dry_run_command`` were never enforced and are
removed: a TOML declaring one fails validation naming the replacement, and
``validate_sync`` rejects it in shipped TOML.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from darnit.config.framework_schema import FrameworkConfig, HandlerInvocation, RemediationConfig
from darnit.config.operator.schema import RemediationSettings
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationExecutor
from darnit.remediation.platform import PlatformSession, ResolvedPolicy
from tests.conftest_helpers import assert_unchanged, snapshot

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

OWNER, REPO = "o", "r"
REPOSITORY = "github.com/o/r"

FILE_CREATE = HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Security\n")
MANUAL = HandlerInvocation(handler="manual", steps=["Ask a maintainer"])


def _executor(repo: Path, **kwargs) -> RemediationExecutor:
    return RemediationExecutor(local_path=str(repo), owner=OWNER, repo=REPO, **kwargs)


def _unsafe(*handlers: HandlerInvocation) -> RemediationConfig:
    return RemediationConfig(handlers=list(handlers), safe=False)


def _policy(mode: str) -> ResolvedPolicy:
    return ResolvedPolicy(
        settings=RemediationSettings(platform=mode, high_impact=mode), operator_config_digest=None, operator="alice"
    )


def _framework(remediation: dict) -> dict:
    return {
        "metadata": {"name": "t", "display_name": "T", "version": "1"},
        "controls": {"T-01": {"name": "T", "description": "t", "remediation": remediation}},
    }


@pytest.mark.unit
class TestUnsafeRemediation:
    def test_preview_flags_individual_approval(self, tmp_path: Path) -> None:
        result = _executor(tmp_path).execute("T-01", _unsafe(FILE_CREATE), dry_run=True)

        [item] = result.plan
        assert item.requires_individual_approval is True

    def test_batch_apply_without_its_digest_writes_nothing(self, tmp_path: Path) -> None:
        preview = _executor(tmp_path).execute("T-01", _unsafe(FILE_CREATE), dry_run=True)
        before = snapshot(tmp_path)

        result = _executor(tmp_path).execute("T-01", _unsafe(FILE_CREATE), dry_run=False)

        assert_unchanged(tmp_path, before)
        assert result.success is False
        assert result.changed is False
        assert result.needs_approval == [preview.plan[0].digest]
        assert manifest.load_run(REPOSITORY, checkout=tmp_path) is None

    def test_apply_with_its_digest_writes_the_previewed_change(self, tmp_path: Path) -> None:
        preview = _executor(tmp_path).execute("T-01", _unsafe(FILE_CREATE), dry_run=True)

        result = _executor(tmp_path, approvals=[preview.plan[0].digest]).execute(
            "T-01", _unsafe(FILE_CREATE), dry_run=False
        )

        assert result.success and result.changed
        assert result.needs_approval == []
        assert (tmp_path / "SECURITY.md").read_text(encoding="utf-8") == "# Security\n"

    def test_digest_passed_through_the_platform_session_approves(self, tmp_path: Path) -> None:
        preview = _executor(tmp_path).execute("T-01", _unsafe(FILE_CREATE), dry_run=True)
        session = PlatformSession(REPOSITORY, policy=_policy("prompt"), approvals=[preview.plan[0].digest])

        result = _executor(tmp_path, platform=session).execute("T-01", _unsafe(FILE_CREATE), dry_run=False)

        assert result.changed

    @pytest.mark.parametrize("mode", ["auto", "prompt", "manual"])
    def test_no_policy_approves_it(self, tmp_path: Path, mode: str) -> None:
        session = PlatformSession(REPOSITORY, policy=_policy(mode))
        before = snapshot(tmp_path)

        result = _executor(tmp_path, platform=session).execute("T-01", _unsafe(FILE_CREATE), dry_run=False)

        assert_unchanged(tmp_path, before)
        assert result.changed is False
        assert result.needs_approval

    def test_an_approval_of_another_item_does_not_cover_it(self, tmp_path: Path) -> None:
        other = _executor(tmp_path).execute(
            "T-02", _unsafe(HandlerInvocation(handler="file_create", path="OTHER.md", content="x\n")), dry_run=True
        )

        result = _executor(tmp_path, approvals=[other.plan[0].digest]).execute(
            "T-01", _unsafe(FILE_CREATE), dry_run=False
        )

        assert result.changed is False
        assert not (tmp_path / "SECURITY.md").exists()

    def test_a_digest_previewed_against_another_state_does_not_approve(self, tmp_path: Path) -> None:
        stale = _executor(tmp_path).execute(
            "T-01",
            _unsafe(HandlerInvocation(handler="file_create", path="SECURITY.md", content="# Old\n")),
            dry_run=True,
        )

        result = _executor(tmp_path, approvals=[stale.plan[0].digest]).execute(
            "T-01", _unsafe(FILE_CREATE), dry_run=False
        )

        assert result.changed is False
        assert not (tmp_path / "SECURITY.md").exists()

    def test_no_step_of_the_control_runs_while_one_needs_approval(self, tmp_path: Path) -> None:
        not_previewable = HandlerInvocation(handler="exec", command=["touch", "RAN"])
        config = RemediationConfig(handlers=[FILE_CREATE, not_previewable])
        before = snapshot(tmp_path)

        result = _executor(tmp_path).execute("T-01", config, dry_run=False)

        assert_unchanged(tmp_path, before)
        assert len(result.needs_approval) == 1

    def test_manual_steps_need_no_approval(self, tmp_path: Path) -> None:
        preview = _executor(tmp_path).execute("T-01", _unsafe(MANUAL), dry_run=True)
        result = _executor(tmp_path).execute("T-01", _unsafe(MANUAL), dry_run=False)

        assert preview.plan[0].requires_individual_approval is False
        assert result.needs_approval == []
        assert result.success


REMOVED = {
    "requires_confirmation": (True, "safe = false"),
    "dry_run_supported": (True, "plan mode"),
    "dry_run_command": (["uv", "lock", "--dry-run"], "plan mode"),
}


@pytest.mark.unit
class TestRemovedProperties:
    @pytest.mark.parametrize("name", sorted(REMOVED))
    def test_absent_from_the_schema(self, name: str) -> None:
        assert name not in RemediationConfig.model_fields

    @pytest.mark.parametrize("name", sorted(REMOVED))
    def test_on_the_remediation_fails_validation_naming_the_replacement(self, name: str) -> None:
        value, replacement = REMOVED[name]

        with pytest.raises(ValidationError) as exc:
            FrameworkConfig.model_validate(_framework({name: value, "handlers": [{"handler": "manual"}]}))

        message = str(exc.value)
        assert name in message
        assert replacement in message
        assert "T-01" in message

    @pytest.mark.parametrize("name", sorted(REMOVED))
    def test_on_a_step_fails_validation_naming_the_replacement(self, name: str) -> None:
        value, replacement = REMOVED[name]
        step = {"handler": "exec", "command": ["uv", "lock"], name: value}

        with pytest.raises(ValidationError) as exc:
            FrameworkConfig.model_validate(_framework({"handlers": [step]}))

        assert name in str(exc.value)
        assert replacement in str(exc.value)

    def test_safe_is_kept_and_enforced(self) -> None:
        assert RemediationConfig.model_fields["safe"].default is True


def _validate_sync(paths: list[Path]):
    from validate_sync import validate_remediation_properties

    return validate_remediation_properties(paths)


def _toml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "framework.toml"
    path.write_text(
        '[metadata]\nname = "t"\ndisplay_name = "T"\nversion = "1"\n\n'
        '[controls."T-01"]\nname = "T"\ndescription = "t"\n\n' + body,
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
class TestValidateSync:
    def test_shipped_tomls_pass(self) -> None:
        result = _validate_sync(None)

        assert result.passed, result.details

    @pytest.mark.parametrize(
        "body",
        [
            '[controls."T-01".remediation]\nrequires_confirmation = true\n',
            '[controls."T-01".remediation]\ndry_run_supported = true\n',
            '[[controls."T-01".remediation.handlers]]\nhandler = "exec"\ncommand = ["uv", "lock"]\n'
            'dry_run_command = ["uv", "lock", "--dry-run"]\n',
            '[[controls."T-01".remediation.handlers]]\nhandler = "api_call"\nendpoint = "/x"\n',
            '[controls."T-01".remediation.api_call]\nendpoint = "/x"\n',
        ],
        ids=["requires_confirmation", "dry_run_supported", "dry_run_command", "api_call", "api_call_table"],
    )
    def test_rejects_removed_property(self, tmp_path: Path, body: str) -> None:
        result = _validate_sync([_toml(tmp_path, body)])

        assert not result.passed
        assert "T-01" in result.details
