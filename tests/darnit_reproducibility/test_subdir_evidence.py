"""Issue #536: bounded requirements discovery and aggregation."""

from collections.abc import Callable
from pathlib import Path

import pytest
from darnit_reproducibility.handlers import repro_deps_pinned_handler

from darnit.sieve.handler_registry import HandlerResultStatus

from .conftest import repro_ctx

PINNED = f"numpy==1.26.4 --hash=sha256:{'a' * 64}\n"


@pytest.fixture
def repo_tree(tmp_path: Path) -> Callable[[dict[str, str]], Path]:
    def build(files: dict[str, str]) -> Path:
        for name, contents in files.items():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
        return tmp_path

    return build


@pytest.mark.parametrize(
    "name",
    ["requirements.txt", "requirements/base.txt", "deps/requirements/base.txt", "deps/test-requirements-dev.txt"],
)
def test_pinned_requirements_at_root_and_in_subdirectories(repo_tree, name: str) -> None:
    repo = repo_tree({name: PINNED})
    result = repro_deps_pinned_handler({}, repro_ctx(repo))
    assert result.status == HandlerResultStatus.PASS
    assert result.evidence["inspected_file"] == name


@pytest.mark.parametrize("loose_name", ["requirements/0-loose.txt", "requirements/z-loose.txt"])
def test_three_pinned_files_and_one_loose_file_fail(repo_tree, loose_name: str) -> None:
    repo = repo_tree({
        "requirements.txt": PINNED,
        "requirements/base.txt": PINNED,
        "deps/requirements-dev.txt": PINNED,
        loose_name: "requests>=2.0\n",
    })
    result = repro_deps_pinned_handler({}, repro_ctx(repo))
    assert result.status == HandlerResultStatus.FAIL
    assert loose_name in result.message
    assert len(result.evidence["requirements_files_inspected"]) == 4


def test_all_pinned_files_pass(repo_tree) -> None:
    repo = repo_tree({"requirements/base.txt": PINNED, "requirements/dev.txt": PINNED})
    result = repro_deps_pinned_handler({}, repro_ctx(repo))
    assert result.status == HandlerResultStatus.PASS
    assert len(result.evidence["requirements_files_inspected"]) == 2


@pytest.mark.parametrize("contents", ["numpy==1.26.4\n", "-r missing.txt\n"])
def test_hashless_or_uninspectable_file_prevents_pass(repo_tree, contents: str) -> None:
    repo = repo_tree({"requirements/base.txt": PINNED, "requirements/dev.txt": contents})
    assert repro_deps_pinned_handler({}, repro_ctx(repo)).status == HandlerResultStatus.INCONCLUSIVE


def test_dependency_aggregation_does_not_stop_at_scan_limit(repo_tree) -> None:
    files = {f"requirements/{i:02}.txt": PINNED for i in range(31)}
    files["requirements/z-loose.txt"] = "requests\n"
    repo = repo_tree(files)
    assert repro_deps_pinned_handler({}, repro_ctx(repo)).status == HandlerResultStatus.FAIL


@pytest.mark.parametrize("name", ["deps/uv.lock", "packages/app/package-lock.json"])
def test_nested_lock_does_not_hide_unpinned_requirements(repo_tree, name: str) -> None:
    repo = repo_tree({name: "not lock-file syntax", "requirements/base.txt": "requests\n"})
    result = repro_deps_pinned_handler({}, repro_ctx(repo))
    assert result.status == HandlerResultStatus.FAIL


def test_unreadable_directory_is_inconclusive(repo_tree, monkeypatch) -> None:
    repo = repo_tree({"hidden/requirements.txt": PINNED})
    original = Path.iterdir

    def iterdir(path):
        if path == repo / "hidden":
            raise PermissionError("access denied")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    result = repro_deps_pinned_handler({}, repro_ctx(repo))
    assert result.status == HandlerResultStatus.INCONCLUSIVE
    assert "Could not search" in result.message


def test_root_lock_short_circuits_directory_search(repo_tree, monkeypatch) -> None:
    repo = repo_tree({"uv.lock": "", "hidden/requirements.txt": "requests\n"})

    def fail_search(path):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "iterdir", fail_search)
    result = repro_deps_pinned_handler({}, repro_ctx(repo))
    assert result.status == HandlerResultStatus.PASS
    assert result.evidence["loose_manifests_found"] == []


@pytest.mark.parametrize("directory", ["a/b/c", ".hidden", "a/.hidden", "vendor", "a/node_modules", "build", "docs", "examples", "a/docs", "a/examples"])
def test_too_deep_and_excluded_directories_do_not_count(repo_tree, directory: str) -> None:
    repo = repo_tree({f"{directory}/requirements.txt": PINNED})
    assert repro_deps_pinned_handler({}, repro_ctx(repo)).status == HandlerResultStatus.INCONCLUSIVE


def test_symlinked_directories_do_not_count(repo_tree) -> None:
    root = repo_tree({"outside/requirements.txt": PINNED})
    repo = root / "repo"
    repo.mkdir()
    try:
        (repo / "linked").symlink_to(root / "outside", target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        pytest.skip("creating symlinks requires Windows developer mode or elevated privileges")
    assert repro_deps_pinned_handler({}, repro_ctx(repo)).status == HandlerResultStatus.INCONCLUSIVE


@pytest.mark.parametrize("directory", ["docs", "examples", "app/docs", "app/examples"])
def test_excluded_loose_requirements_do_not_override_pinned(repo_tree, directory: str) -> None:
    repo = repo_tree({"requirements.txt": PINNED, f"{directory}/requirements.txt": "requests\n"})
    assert repro_deps_pinned_handler({}, repro_ctx(repo)).status == HandlerResultStatus.PASS
