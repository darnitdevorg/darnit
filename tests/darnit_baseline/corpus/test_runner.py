"""Self-tests for the corpus runner (feature 041 T038).

A synthetic framework, independent of the Baseline TOML, checks that the
runner fails on a false PASS by a promoted step and names the step and the
fixture, that a fixture directory holding only ``labels.toml`` is measured
with no code change, that platform recordings are served offline, and that
a fixture's stand-in tools and plugin registrations (feature 044) take effect
only for that fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.darnit_baseline.corpus.runner import (
    CorpusError,
    Framework,
    KnownFalsePass,
    corpus_version,
    framework_from_toml,
    gate,
    load_fixture,
    run_corpus,
)

SYNTHETIC_TOML = """
[metadata]
name = "corpus-selftest"
display_name = "Corpus self-test"
version = "0.0.1"
spec_version = "t"

[controls."SYN-01"]
name = "PromotedPresence"
description = "A presence step promoted to conclude PASS"
level = 1
domain = "SY"

[[controls."SYN-01".passes]]
handler = "file_exists"
files = ["README.md"]
promotion = { outcome = "pass", corpus = "selftest", note = "promoted for the runner self-test" }

[controls."SYN-02"]
name = "Presence"
description = "A presence step that may conclude only FAIL"
level = 1
domain = "SY"

[[controls."SYN-02".passes]]
handler = "file_exists"
files = ["README.md"]

[controls."SYN-03"]
name = "PlatformApi"
description = "A gh_api step"
level = 1
domain = "SY"

[[controls."SYN-03".passes]]
handler = "gh_api"
endpoint = "/repos/$OWNER/$REPO"
expr = "response.body.private == false"

[controls."SYN-04"]
name = "PlatformExec"
description = "An exec step calling gh api"
level = 1
domain = "SY"

[[controls."SYN-04".passes]]
handler = "exec"
command = ["gh", "api", "/repos/$OWNER/$REPO"]
output_format = "json"
expr = "output.json.private == false"

[controls."SYN-05"]
name = "Tool"
description = "An exec step running a stand-in tool"
level = 1
domain = "SY"

[[controls."SYN-05".passes]]
handler = "exec"
command = ["corpus-tool"]
output_format = "json"
expr = "output.json.ok"
expr_decides = true

[controls."SYN-06"]
name = "Review"
description = "A control only a person can conclude"
level = 1
domain = "SY"

[[controls."SYN-06".passes]]
handler = "manual"
steps = ["Review it"]
"""


@pytest.fixture()
def framework(tmp_path: Path) -> Framework:
    path = tmp_path / "selftest.toml"
    path.write_text(SYNTHETIC_TOML, encoding="utf-8")
    return framework_from_toml(path)


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    return root


def _fixture(root: Path, name: str, labels: str, files: dict[str, str] | None = None) -> Path:
    path = root / name
    path.mkdir()
    for rel, content in (files or {}).items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (path / "labels.toml").write_text(f'[fixture]\ndescription = "{name}"\n\n{labels}', encoding="utf-8")
    return path


def _label(control_id: str, expected: str) -> str:
    return f'[labels."{control_id}"]\nexpected = "{expected}"\nwhy = "self-test"\n\n'


def test_promoted_step_fooled_by_fixture_fails_and_names_step_and_fixture(framework: Framework, corpus: Path) -> None:
    _fixture(corpus, "todo-readme", _label("SYN-01", "NOT_PASS"), {"README.md": "TODO\n"})

    report = run_corpus(framework, corpus)
    unexpected, stale = gate(report, [])

    assert len(unexpected) == 1 and not stale
    message = unexpected[0].describe()
    for fragment in ("corpus-selftest", "SYN-01", "pass[0]", "file_exists", "todo-readme"):
        assert fragment in message, (fragment, message)


def test_known_false_pass_is_allowed_and_stale_entries_are_reported(framework: Framework, corpus: Path) -> None:
    _fixture(corpus, "todo-readme", _label("SYN-01", "NOT_PASS"), {"README.md": "TODO\n"})
    report = run_corpus(framework, corpus)
    known = KnownFalsePass("corpus-selftest", "todo-readme", "SYN-01", 0, "file_exists", "T000", "self-test")
    gone = KnownFalsePass("corpus-selftest", "other", "SYN-01", 0, "file_exists", "T000", "self-test")

    unexpected, stale = gate(report, [known, gone])

    assert unexpected == []
    assert stale == [gone]


def test_fixture_with_only_labels_is_measured_without_code_change(framework: Framework, corpus: Path) -> None:
    _fixture(corpus, "with-readme", _label("SYN-02", "PASS"), {"README.md": "# Project\n"})
    before = run_corpus(framework, corpus)
    version_before = corpus_version(corpus)

    _fixture(corpus, "bare", _label("SYN-01", "FAIL") + _label("SYN-02", "FAIL"))
    after = run_corpus(framework, corpus)

    assert "bare" not in before.fixtures and "bare" in after.fixtures
    assert corpus_version(corpus) != version_before
    bare = {c.control_id: c for c in after.controls if c.fixture == "bare"}
    assert bare["SYN-01"].status == "FAIL" and bare["SYN-01"].verdict == "correct"
    assert bare["SYN-02"].concluded_by == "file_exists" and bare["SYN-02"].verdict == "correct"
    fail_rows = [r for r in after.rows if r.control_id == "SYN-02" and r.outcome == "FAIL"]
    assert fail_rows and fail_rows[0].correct == 1


def test_promotion_eligibility_requires_zero_false_pass(framework: Framework, corpus: Path) -> None:
    _fixture(corpus, "good", _label("SYN-02", "PASS"), {"README.md": "# Project\n\nUsage: run it.\n"})
    eligible = {(s.control_id, s.step_index): s for s in run_corpus(framework, corpus).steps}
    assert eligible[("SYN-02", 0)].eligible_for_promotion
    assert not eligible[("SYN-01", 0)].eligible_for_promotion

    _fixture(corpus, "fooled", _label("SYN-02", "NOT_PASS"), {"README.md": "TODO\n"})
    report = run_corpus(framework, corpus)
    summary = {(s.control_id, s.step_index): s for s in report.steps}[("SYN-02", 0)]
    assert summary.false_pass == 1 and not summary.eligible_for_promotion
    assert gate(report, []) == ([], []), "a step that may not conclude PASS never violates the gate"


def test_platform_recordings_are_served_offline(framework: Framework, corpus: Path) -> None:
    recorded = (
        '[fixture.platform."/repos/$OWNER/$REPO"]\nstatus = 200\nbody = { private = false }\n\n'
        + _label("SYN-03", "PASS")
        + _label("SYN-04", "PASS")
    )
    _fixture(corpus, "public", recorded)
    _fixture(corpus, "unrecorded", _label("SYN-03", "NOT_PASS") + _label("SYN-04", "NOT_PASS"))

    results = {(c.fixture, c.control_id): c for c in run_corpus(framework, corpus).controls}

    assert results[("public", "SYN-03")].status == "PASS"
    assert results[("public", "SYN-03")].concluded_by == "gh_api"
    assert results[("public", "SYN-04")].status == "PASS"
    assert results[("public", "SYN-04")].concluded_by == "exec"
    assert results[("unrecorded", "SYN-03")].status == "ERROR"
    assert results[("unrecorded", "SYN-04")].status != "PASS"


def test_stand_in_tools_are_first_on_path(framework: Framework, corpus: Path) -> None:
    tool = "[fixture.tools.corpus-tool]\nstdout = '{\"ok\": false}'\nexit_code = 0\n\n"
    _fixture(corpus, "with-tool", tool + _label("SYN-05", "FAIL"))
    _fixture(corpus, "without-tool", _label("SYN-05", "FAIL"))

    results = {(c.fixture, c.control_id): c for c in run_corpus(framework, corpus).controls}

    assert results[("with-tool", "SYN-05")].status == "FAIL"
    assert results[("without-tool", "SYN-05")].status == "ERROR"


def test_stand_in_tool_writer_needs_no_monkeypatch(tmp_path: Path) -> None:
    """The runner and tests share one stand-in writer; the runner has no monkeypatch (044 review)."""
    import subprocess

    from tests.conftest_helpers import write_stand_in_tool

    tool = write_stand_in_tool(tmp_path, "corpus-tool", stdout='{"ok": true}', exit_code=3)
    run = subprocess.run([str(tool)], capture_output=True, text=True, timeout=30, check=False)

    assert (run.stdout, run.returncode) == ('{"ok": true}', 3)


def test_plugin_registration_is_refused_and_registry_restored(framework: Framework, corpus: Path) -> None:
    from darnit.sieve.handler_registry import get_sieve_handler_registry

    registry = get_sieve_handler_registry()
    manual = registry.get("manual")
    refused_before = list(registry.refused_registrations)
    plugin = '[fixture.plugin]\nname = "selftest-plugin"\nstep_types = { manual = "pass" }\n\n'
    _fixture(corpus, "hostile", plugin + _label("SYN-06", "NOT_PASS"))

    report = run_corpus(framework, corpus)

    assert report.fixtures["hostile"]["refused_registrations"] == ["manual"]
    assert {c.control_id: c for c in report.controls}["SYN-06"].status != "PASS"
    assert registry.get("manual") is manual
    assert registry.refused_registrations == refused_before


def test_corpus_version_covers_labels(corpus: Path) -> None:
    path = _fixture(corpus, "one", _label("SYN-02", "FAIL"))
    first = corpus_version(corpus)
    assert corpus_version(corpus) == first
    (path / "labels.toml").write_text((path / "labels.toml").read_text().replace("FAIL", "NOT_PASS"))
    assert corpus_version(corpus) != first


@pytest.mark.parametrize(
    "labels",
    [
        '[labels."SYN-01"]\nexpected = "MAYBE"\nwhy = "x"\n',
        '[labels."SYN-01"]\nexpected = "FAIL"\n',
        '[fixture.tools.t]\nexit_code = "0"\n',
        '[fixture.plugin]\nname = "p"\n',
        '[fixture.plugin]\nname = "p"\nstep_types = { manual = "maybe" }\n',
    ],
)
def test_invalid_labels_are_rejected(corpus: Path, labels: str) -> None:
    path = _fixture(corpus, "bad", labels)
    with pytest.raises(CorpusError):
        load_fixture(path)
