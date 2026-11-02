"""Issue #536: bounded discovery, ALL requirements, and ANY build environment."""

from collections.abc import Callable
from pathlib import Path

import pytest
from darnit_reproducibility.handlers import (
    repro_build_env_declared_handler,
    repro_deps_pinned_handler,
)

from darnit.sieve.handler_registry import HandlerResultStatus

from .conftest import repro_ctx

PINNED = f"numpy==1.26.4 --hash=sha256:{'a' * 64}\n"
DOCKERFILE = f"FROM alpine@sha256:{'a' * 64}\n"


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
def test_nested_lock_still_short_circuits_without_reading(repo_tree, monkeypatch, name: str) -> None:
    repo = repo_tree({name: "not lock-file syntax", "requirements/base.txt": "requests\n"})

    def no_read(*args, **kwargs):
        pytest.fail("a lock file must short-circuit before any contents are read")

    monkeypatch.setattr("darnit_reproducibility.handlers.read_repository_text", no_read)
    result = repro_deps_pinned_handler({}, repro_ctx(repo))
    assert result.status == HandlerResultStatus.PASS
    assert name in result.message


@pytest.mark.parametrize(
    ("name", "contents"),
    [
        ("Dockerfile", DOCKERFILE),
        ("docker/Dockerfile", DOCKERFILE),
        ("docker/prod/Dockerfile.release", DOCKERFILE),
        ("containers/prod/Containerfile.dev", DOCKERFILE),
        ("docker/docker-compose.prod.yaml", "services: {}\n"),
        ("docker/docker-compose.yml", "services: {}\n"),
        ("env/flake.nix", "{}\n"),
        ("env/shell.nix", "{}\n"),
        ("env/.python-version", "3.11\n"),
        ("env/.nvmrc", "22\n"),
        ("env/.tool-versions", "python 3.11\n"),
        ("env/Vagrantfile", "config.vm.box = 'ubuntu/jammy64'\n"),
    ],
)
def test_environment_files_at_root_and_in_subdirectories(repo_tree, name: str, contents: str) -> None:
    repo = repo_tree({name: contents})
    result = repro_build_env_declared_handler({}, repro_ctx(repo))
    assert result.status == HandlerResultStatus.PASS
    assert any(item.startswith(f"{name} (") for item in result.evidence["env_files_found"])


def test_nested_devcontainer_directory_counts(repo_tree) -> None:
    repo = repo_tree({"app/.devcontainer/devcontainer.json": "{}\n"})
    assert repro_build_env_declared_handler({}, repro_ctx(repo)).status == HandlerResultStatus.PASS


@pytest.mark.parametrize("name", ["docker/prod/Dockerfile", "env/Vagrantfile"])
def test_any_qualifying_environment_wins_over_floating_container(repo_tree, name: str) -> None:
    repo = repo_tree({"Dockerfile": "FROM alpine:latest\n", name: DOCKERFILE})
    assert repro_build_env_declared_handler({}, repro_ctx(repo)).status == HandlerResultStatus.PASS


@pytest.mark.parametrize("directory", ["a/b/c", ".hidden", "a/.hidden", "vendor", "a/node_modules", "build"])
def test_too_deep_and_excluded_directories_do_not_count(repo_tree, directory: str) -> None:
    repo = repo_tree({f"{directory}/requirements.txt": PINNED, f"{directory}/Dockerfile": DOCKERFILE})
    assert repro_deps_pinned_handler({}, repro_ctx(repo)).status == HandlerResultStatus.INCONCLUSIVE
    assert repro_build_env_declared_handler({}, repro_ctx(repo)).status == HandlerResultStatus.INCONCLUSIVE


def test_symlinked_directories_do_not_count(repo_tree) -> None:
    root = repo_tree({"outside/requirements.txt": PINNED, "outside/Dockerfile": DOCKERFILE})
    repo = root / "repo"
    repo.mkdir()
    (repo / "linked").symlink_to(root / "outside", target_is_directory=True)
    assert repro_deps_pinned_handler({}, repro_ctx(repo)).status == HandlerResultStatus.INCONCLUSIVE
    assert repro_build_env_declared_handler({}, repro_ctx(repo)).status == HandlerResultStatus.INCONCLUSIVE
