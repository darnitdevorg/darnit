"""Reads stay inside the audited repository (framework-design.md 3.0.4).

A file of the repository that is a symbolic link resolving outside it is
never read and never counts as present; a step that skips it records the
repository entry that leads outside in ``skipped_outside_repository``. A link
that stays inside the repository is followed as usual.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from darnit.core.repo_files import (
    OutsideRepositoryError,
    escaping_entry,
    open_in_repository,
    read_repository_text,
    resolve_in_repository,
    within_repository,
)
from darnit.sieve.builtin_handlers import (
    file_create_handler,
    file_exists_handler,
    llm_eval_handler,
    llm_extract_handler,
    regex_handler,
)
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus

MARKER = "outsidemarker7f3a"


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory beside the repository holding content the audit must never see."""
    path = tmp_path / "outside"
    path.mkdir()
    (path / "secret.txt").write_text(
        f"# Security\nReport to {MARKER}@example.com\n- @{MARKER}\n{MARKER} vulnerability disclosure\n",
        encoding="utf-8",
    )
    (path / "notes.md").write_text(f"{MARKER} in a linked directory\n", encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path, outside: Path) -> Path:
    path = tmp_path / "repo"
    (path / "docs").mkdir(parents=True)
    (path / "docs" / "README.md").write_text("# Project\nvulnerability disclosure inside\n", encoding="utf-8")
    (path / "SECURITY.md").symlink_to(outside / "secret.txt")
    (path / "README.md").symlink_to("docs/README.md")
    (path / "linked").symlink_to(outside, target_is_directory=True)
    return path


@pytest.fixture
def ctx(repo: Path) -> HandlerContext:
    return HandlerContext(
        local_path=str(repo),
        owner="testorg",
        repo="testrepo",
        default_branch="main",
        control_id="TEST-01",
    )


def _dump(result) -> str:
    return json.dumps({"evidence": result.evidence, "details": result.details, "message": result.message}, default=str)


class TestRepoFiles:
    def test_inside_file_and_inside_link(self, repo: Path) -> None:
        assert within_repository(repo, "docs/README.md")
        assert within_repository(repo, "README.md")
        assert read_repository_text(repo, "README.md").startswith("# Project")

    def test_link_to_outside_file(self, repo: Path) -> None:
        assert not within_repository(repo, "SECURITY.md")
        assert not within_repository(repo, repo / "SECURITY.md")
        with pytest.raises(OutsideRepositoryError) as exc:
            read_repository_text(repo, "SECURITY.md")
        assert exc.value.entry == "SECURITY.md"
        assert MARKER not in str(exc.value)
        assert "outside/secret.txt" not in str(exc.value)

    def test_error_is_an_oserror(self, repo: Path) -> None:
        with pytest.raises(OSError):
            resolve_in_repository(repo, "SECURITY.md")

    def test_entry_through_a_linked_directory_names_the_link(self, repo: Path) -> None:
        assert escaping_entry(repo, "linked/notes.md") == "linked"
        assert escaping_entry(repo, str(repo / "linked" / "notes.md")) == "linked"

    def test_absolute_path_outside(self, repo: Path, outside: Path) -> None:
        assert not within_repository(repo, outside / "secret.txt")

    def test_dangling_link_outside(self, repo: Path, tmp_path: Path) -> None:
        (repo / "GONE.md").symlink_to(tmp_path / "does-not-exist")
        assert not within_repository(repo, "GONE.md")

    def test_relative_link_climbing_out(self, repo: Path) -> None:
        (repo / "UP.md").symlink_to("../outside/secret.txt")
        assert not within_repository(repo, "UP.md")

    def test_open_for_writing_is_refused(self, repo: Path) -> None:
        with pytest.raises(ValueError):
            open_in_repository(repo, "docs/new.md", "w")

    def test_repository_root_behind_a_link(self, repo: Path, tmp_path: Path) -> None:
        alias = tmp_path / "alias"
        alias.symlink_to(repo, target_is_directory=True)
        assert within_repository(alias, "docs/README.md")
        assert not within_repository(alias, "SECURITY.md")


class TestFileExists:
    def test_link_outside_is_not_found(self, ctx: HandlerContext) -> None:
        result = file_exists_handler({"files": ["SECURITY.md"]}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["skipped_outside_repository"] == ["SECURITY.md"]

    def test_glob_skips_link_outside(self, ctx: HandlerContext) -> None:
        result = file_exists_handler({"files": ["SECURITY*"]}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["skipped_outside_repository"] == ["SECURITY.md"]

    def test_depth_walk_skips_linked_directory(self, ctx: HandlerContext) -> None:
        result = file_exists_handler({"files": ["notes.md"], "max_depth": 2}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["skipped_outside_repository"] == ["linked"]

    def test_link_inside_is_found(self, ctx: HandlerContext) -> None:
        result = file_exists_handler({"files": ["README.md"]}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert "skipped_outside_repository" not in result.evidence


class TestRegex:
    def test_link_outside_is_not_read(self, ctx: HandlerContext) -> None:
        result = regex_handler({"files": ["SECURITY.md"], "pattern": r"Report to \S+"}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["skipped_outside_repository"] == ["SECURITY.md"]
        assert MARKER not in _dump(result)

    def test_glob_through_linked_directory_records_only_the_link(self, ctx: HandlerContext) -> None:
        result = regex_handler({"files": ["linked/*.md", "*.md"], "pattern": "disclosure"}, ctx)
        dumped = _dump(result)
        assert "notes.md" not in dumped
        assert "secret.txt" not in dumped
        assert f"{MARKER}@example.com" not in dumped
        assert result.evidence["skipped_outside_repository"] == ["linked", "SECURITY.md"]
        assert result.status == HandlerResultStatus.PASS  # README.md -> docs/README.md matched

    def test_found_file_outside_is_not_read(self, ctx: HandlerContext, repo: Path) -> None:
        ctx.gathered_evidence["found_file"] = str(repo / "SECURITY.md")
        result = regex_handler({"file": "$FOUND_FILE", "pattern": "Report"}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["skipped_outside_repository"] == ["SECURITY.md"]

    def test_exclude_mode_does_not_list_files_behind_a_link(self, ctx: HandlerContext) -> None:
        result = regex_handler({"exclude_files": ["linked/*.md"]}, ctx)
        assert result.evidence["files_found"] == 0
        assert result.evidence["skipped_outside_repository"] == ["linked"]
        assert "notes.md" not in _dump(result)


class TestLlmSteps:
    def test_llm_eval_does_not_bundle_a_link_outside(self, ctx: HandlerContext, repo: Path) -> None:
        ctx.gathered_evidence["found_file"] = str(repo / "SECURITY.md")
        ctx.gathered_evidence["resolved_files"] = [str(repo / "SECURITY.md"), str(repo / "README.md")]
        result = llm_eval_handler(
            {"prompt": "judge", "files_to_include": ["$FOUND_FILE", "SECURITY.md", "$RESOLVED_FILES"]}, ctx
        )
        contents = result.details["consultation_request"]["file_contents"]
        assert set(contents) == {"README.md"}
        assert MARKER not in _dump(result)
        assert result.evidence["skipped_outside_repository"] == ["SECURITY.md"]

    def test_llm_eval_fallback_does_not_read_outside(self, ctx: HandlerContext, repo: Path) -> None:
        ctx.gathered_evidence["resolved_files"] = [str(repo / "linked" / "notes.md")]
        result = llm_eval_handler({"prompt": "judge", "files_to_include": ["$FOUND_FILE"]}, ctx)
        assert result.details["consultation_request"]["file_contents"] == {}
        assert result.evidence["skipped_outside_repository"] == ["linked"]
        assert MARKER not in _dump(result)

    def test_llm_eval_absolute_path_outside(self, ctx: HandlerContext, outside: Path) -> None:
        result = llm_eval_handler({"prompt": "judge", "files_to_include": [str(outside / "secret.txt")]}, ctx)
        assert result.details["consultation_request"]["file_contents"] == {}
        assert MARKER not in _dump(result)

    def test_llm_extract_skips_links_outside(self, ctx: HandlerContext) -> None:
        result = llm_extract_handler({"prompt": "extract", "files": ["*.md", "linked/*"]}, ctx)
        contents = result.details["consultation_request"]["file_contents"]
        assert set(contents) == {"README.md"}
        assert result.evidence["skipped_outside_repository"] == ["SECURITY.md", "linked"]
        assert MARKER not in _dump(result)


class TestRemediationPlanning:
    def test_file_create_over_a_link_outside_is_an_error(self, ctx: HandlerContext) -> None:
        result = file_create_handler({"path": "SECURITY.md", "content": "new", "overwrite": True}, ctx)
        assert result.status == HandlerResultStatus.ERROR
        assert "outside the repository" in result.message
        assert MARKER not in _dump(result)


class TestCelFileExists:
    def _evaluate(self, repo: Path, path: str) -> bool:
        from darnit.sieve.cel_evaluator import CELEvaluator

        evaluator = CELEvaluator(repo_path=repo)
        result = evaluator.evaluate(evaluator.compile(f'file_exists("{path}")'), {})
        assert result.success is True
        return result.value

    def test_link_outside_does_not_exist(self, repo: Path) -> None:
        assert self._evaluate(repo, "SECURITY.md") is False
        assert self._evaluate(repo, "linked/notes.md") is False
        assert self._evaluate(repo, "../outside/secret.txt") is False

    def test_link_inside_exists(self, repo: Path) -> None:
        assert self._evaluate(repo, "README.md") is True


class TestFrameworkReaders:
    def test_utils_helpers(self, repo: Path) -> None:
        from darnit.core.utils import file_exists, read_file

        assert read_file(str(repo), "SECURITY.md") is None
        assert read_file(str(repo), "README.md").startswith("# Project")
        assert file_exists(str(repo), "SECURITY.md") is False
        assert file_exists(str(repo), "README.md") is True

    def test_context_detection_ignores_hint_files_outside(self, repo: Path, outside: Path) -> None:
        from darnit.context.sieve import ContextSieve

        (repo / "MAINTAINERS.md").symlink_to(outside / "secret.txt")
        (repo / "CODEOWNERS").symlink_to(outside / "secret.txt")
        sieve = ContextSieve()
        assert sieve._detect_maintainers_deterministic(str(repo)) == []
        assert sieve._detect_security_contact_deterministic(str(repo)) == []
        assert MARKER not in json.dumps(
            [s.value for s in sieve._detect_security_contact_heuristic(str(repo))], default=str
        )

    def test_context_detection_reads_hint_files_inside(self, repo: Path) -> None:
        from darnit.context.sieve import ContextSieve

        (repo / "docs" / "MAINTAINERS.md").write_text("- @insider\n", encoding="utf-8")
        (repo / "MAINTAINERS.md").symlink_to("docs/MAINTAINERS.md")
        signals = ContextSieve()._detect_maintainers_deterministic(str(repo))
        assert signals and "@insider" in json.dumps(signals[0].value)

    def test_hint_source_outside_is_not_parsed(self, repo: Path, outside: Path) -> None:
        from darnit.context.collection import resolve_context_value

        (repo / "MAINTAINERS.md").symlink_to(outside / "secret.txt")
        value, method = resolve_context_value(
            "maintainers", {"hint_sources": ["MAINTAINERS.md"], "source": "MAINTAINERS.md"}, repo
        )
        assert value is None and method is None

    def test_project_file_outside_is_invalid_and_unread(self, repo: Path, outside: Path) -> None:
        from darnit.config.loader import load_project_config_checked
        from darnit.context.dot_project import DotProjectReader

        (outside / "project.yaml").write_text(f"name: {MARKER}\nrepositories: [x]\n", encoding="utf-8")
        (repo / ".project").mkdir()
        (repo / ".project" / "project.yaml").symlink_to(outside / "project.yaml")
        files = load_project_config_checked(str(repo))
        assert files.project.state == "invalid"
        assert MARKER not in json.dumps(files.errors)
        with pytest.raises(ValueError) as exc:
            DotProjectReader(repo).read()
        assert MARKER not in str(exc.value)

    def test_project_claims_outside_are_not_read(self, repo: Path, outside: Path) -> None:
        from darnit.trust.assertions import _project_claims

        (outside / "darnit.yaml").write_text(
            "controls:\n  OSPS-AC-01.01:\n    status: not_applicable\n    reason: x\n", encoding="utf-8"
        )
        (repo / ".project").mkdir()
        (repo / ".project" / "darnit.yaml").symlink_to(outside / "darnit.yaml")
        assert _project_claims(repo) == []
