"""remediate_community_spec previews by default and writes through the executor (feature 043 US5, T054).

Contract 3.4 and framework-design 15.8: ``dry_run = True`` by default; the
README edit is a ``FileChange`` in the preview and in the run manifest.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest

from darnit.remediation import manifest
from darnit.remediation.plan import content_digest
from tests.conftest_helpers import assert_unchanged, snapshot

pytestmark = pytest.mark.unit

COMPLETE = {
    "scope": "This Working Group standardizes the Foo metadata format.",
    "coc_contacts": "Jane Roe (jane@realcorp.io), John Poe (john@realcorp.io)",
    "code_license": "MIT",
    "governance_mode": "csl",
    "coc_policy": "csl",
}
README = "# Foo\n\nA format.\n"


def _run(repo: Path, **params: Any) -> str:
    from darnit_csl.mcp_tools import remediate_community_spec

    return asyncio.run(remediate_community_spec(local_path=str(repo), **COMPLETE, **params))


def _files(repo: Path) -> dict[str, str]:
    return {p.relative_to(repo).as_posix(): p.read_text(encoding="utf-8") for p in repo.rglob("*") if p.is_file()}


def test_dry_run_defaults_to_true() -> None:
    from darnit_csl.mcp_tools import remediate_community_spec

    assert inspect.signature(remediate_community_spec).parameters["dry_run"].default is True


def test_preview_writes_nothing_and_lists_the_readme_edit(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    before = snapshot(tmp_path)

    out = _run(tmp_path)

    assert_unchanged(tmp_path, before)
    assert manifest.load_run(manifest.repository_identity(tmp_path), checkout=tmp_path) is None
    assert "Nothing was written" in out
    assert "CSL-06.01: modify README.md" in out
    assert "- [Scope](governance/02-scope.md)" in out
    assert "create governance/04-license.md" in out


def test_apply_writes_the_previewed_files_and_records_them(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    preview = _run(tmp_path)

    out = _run(tmp_path, dry_run=False)

    files = _files(tmp_path)
    assert files["README.md"].startswith(README)
    assert "- [Scope](governance/02-scope.md)" in files["README.md"]
    for path in files:
        if path != "README.md" and not path.startswith(".project/"):
            assert f"create {path}" in preview, path
    run = manifest.load_run(manifest.repository_identity(tmp_path), checkout=tmp_path)
    assert run is not None
    recorded = {f.path: f.after_digest for f in run.files}
    assert recorded["README.md"] == content_digest(files["README.md"])
    assert "governance/04-license.md" in recorded
    assert f"Run id: {run.run_id}" in out


def test_readme_already_linking_is_left_alone(tmp_path: Path) -> None:
    linked = "# Foo\n- [Scope](governance/02-scope.md)\n"
    (tmp_path / "README.md").write_text(linked, encoding="utf-8")

    out = _run(tmp_path)
    _run(tmp_path, dry_run=False)

    assert "README.md" not in out
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == linked


def test_missing_readme_is_created(tmp_path: Path) -> None:
    out = _run(tmp_path)
    _run(tmp_path, dry_run=False)

    assert "CSL-06.01: create README.md" in out
    assert (tmp_path / "README.md").read_text(encoding="utf-8").startswith("# Specification\n")


def test_replacing_an_existing_scope_needs_the_previewed_digest(tmp_path: Path) -> None:
    """CSL-02.01 overwrites an existing scope document, so it is ``safe = false`` (FR-024)."""
    import re

    scope = tmp_path / "governance" / "02-scope.md"
    scope.parent.mkdir()
    scope.write_text("# Scope\n\n[Include a detailed description]\n\nOur own notes.\n", encoding="utf-8")
    original = scope.read_bytes()

    preview = _run(tmp_path)
    match = re.search(r"## CSL-02\.01: needs the person's approval.*?approve=\['(sha256:[0-9a-f]+)'\]", preview, re.S)
    assert match, preview

    unapproved = _run(tmp_path, dry_run=False)
    assert scope.read_bytes() == original
    assert f"CSL-02.01: approve={match.group(1)}" in unapproved

    _run(tmp_path, dry_run=False, approve=[match.group(1)])
    assert COMPLETE["scope"] in scope.read_text(encoding="utf-8")


def test_approve_parameter_defaults_to_none() -> None:
    from darnit_csl.mcp_tools import remediate_community_spec

    assert inspect.signature(remediate_community_spec).parameters["approve"].default is None
