"""Bounded container build-file discovery for issue #536."""

from pathlib import Path

import pytest
from darnit_reproducibility.handlers import repro_build_env_declared_handler

from darnit.sieve.handler_registry import HandlerResultStatus

from .conftest import repro_ctx

PINNED = f"FROM alpine@sha256:{'a' * 64}\n"


def write_file(root: Path, name: str, content: str) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


@pytest.mark.parametrize("name", ["Dockerfile", "docker/Dockerfile", "docker/prod/Dockerfile.release", "env/Containerfile.dev"])
def test_pinned_container_at_each_depth(tmp_path: Path, name: str) -> None:
    write_file(tmp_path, name, PINNED)
    result = repro_build_env_declared_handler({}, repro_ctx(tmp_path))
    assert result.status == HandlerResultStatus.PASS
    assert result.evidence["containers_inspected"] == [name]


@pytest.mark.parametrize("loose", ["Dockerfile", "docker/Dockerfile.prod"])
def test_any_floating_container_prevents_pass(tmp_path: Path, loose: str) -> None:
    pinned = "docker/Dockerfile.prod" if loose == "Dockerfile" else "Dockerfile"
    write_file(tmp_path, pinned, PINNED)
    write_file(tmp_path, loose, "FROM alpine:latest\n")
    write_file(tmp_path, "Vagrantfile", "config.vm.box = 'ubuntu/jammy64'\n")
    result = repro_build_env_declared_handler({}, repro_ctx(tmp_path))
    assert result.status == HandlerResultStatus.INCONCLUSIVE
    assert result.evidence["unpinned_images"] == [f"{loose}: alpine:latest"]


def test_all_containers_are_inspected(tmp_path: Path) -> None:
    write_file(tmp_path, "Dockerfile", PINNED)
    write_file(tmp_path, "docker/Containerfile", PINNED)
    result = repro_build_env_declared_handler({}, repro_ctx(tmp_path))
    assert result.status == HandlerResultStatus.PASS
    assert set(result.evidence["containers_inspected"]) == {"Dockerfile", "docker/Containerfile"}


def test_unreadable_container_prevents_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from darnit_reproducibility import handlers

    write_file(tmp_path, "Dockerfile", PINNED)
    write_file(tmp_path, "docker/Dockerfile", PINNED)
    read = handlers.read_repository_text

    def read_with_failure(root: Path, target: Path) -> str:
        if target.parent.name == "docker":
            raise PermissionError("access denied")
        return read(root, target)

    monkeypatch.setattr(handlers, "read_repository_text", read_with_failure)
    result = repro_build_env_declared_handler({}, repro_ctx(tmp_path))
    assert result.status == HandlerResultStatus.INCONCLUSIVE
    assert result.evidence["containers_unreadable"] == ["docker/Dockerfile"]


def test_unreadable_directory_prevents_deferred_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_file(tmp_path, "docker/Dockerfile", PINNED)
    write_file(tmp_path, "Vagrantfile", "config.vm.box = 'ubuntu/jammy64'\n")
    iterdir = Path.iterdir

    def fail_search(path: Path):
        if path == tmp_path / "docker":
            raise PermissionError("access denied")
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_search)
    result = repro_build_env_declared_handler({}, repro_ctx(tmp_path))
    assert result.status == HandlerResultStatus.INCONCLUSIVE
    assert "Could not search" in result.message


@pytest.mark.parametrize("directory", ["a/b/c", ".hidden", "vendor", "node_modules", "docs", "examples", "app/docs"])
def test_excluded_directories_are_not_searched(tmp_path: Path, directory: str) -> None:
    write_file(tmp_path, f"{directory}/Dockerfile", PINNED)
    assert repro_build_env_declared_handler({}, repro_ctx(tmp_path)).status == HandlerResultStatus.INCONCLUSIVE


def test_symlinked_directory_is_not_searched(tmp_path: Path) -> None:
    write_file(tmp_path, "outside/Dockerfile", PINNED)
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        (repo / "linked").symlink_to(tmp_path / "outside", target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        pytest.skip("creating symlinks requires Windows developer mode or elevated privileges")
    assert repro_build_env_declared_handler({}, repro_ctx(repo)).status == HandlerResultStatus.INCONCLUSIVE


def test_compose_alone_does_not_pass(tmp_path: Path) -> None:
    write_file(tmp_path, "docker/docker-compose.yml", "services:\n  app:\n    image: alpine:latest\n")
    assert repro_build_env_declared_handler({}, repro_ctx(tmp_path)).status == HandlerResultStatus.INCONCLUSIVE


def test_root_strong_declaration_keeps_precedence(tmp_path: Path) -> None:
    write_file(tmp_path, "flake.nix", "{}")
    write_file(tmp_path, "docker/Dockerfile", "FROM alpine:latest\n")
    assert repro_build_env_declared_handler({}, repro_ctx(tmp_path)).status == HandlerResultStatus.PASS
