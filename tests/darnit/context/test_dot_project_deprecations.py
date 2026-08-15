"""Feature 030 FR-010 verification: `cncf_slack_channel` deprecation warning.

Locks the warning behavior in both directions:
  (a) PRESENCE (US1 acceptance scenario 2): a `.project/project.yaml`
      that still uses `cncf_slack_channel` triggers a `DeprecationWarning`
      whose message names the old key, the replacement, and the current
      spec version.
  (b) ABSENCE (US1 acceptance scenario 3): a repo that has already
      migrated to `slack_channels` (or omits the key entirely) MUST NOT
      be nagged. No `DeprecationWarning` fires on load.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from darnit.context.dot_project import DotProjectReader


def _write_project_yaml(tmp_path: Path, contents: str) -> Path:
    """Write `contents` as `<tmp_path>/.project/project.yaml` and return `tmp_path`."""
    dest_dir = tmp_path / ".project"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "project.yaml").write_text(contents)
    return tmp_path


def test_cncf_slack_channel_emits_deprecation_warning(tmp_path: Path) -> None:
    """PRESENCE: the deprecation warning fires with the required content."""
    repo = _write_project_yaml(
        tmp_path,
        """\
name: has-old-key
repositories:
  - example/repo
cncf_slack_channel: "#legacy-channel"
""",
    )

    reader = DotProjectReader(str(repo))
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        config = reader.read()

    dep_warnings = [w for w in record if issubclass(w.category, DeprecationWarning)]
    assert len(dep_warnings) >= 1, "at least one DeprecationWarning MUST fire"

    matched = [
        w for w in dep_warnings
        if "cncf_slack_channel" in str(w.message)
        and "slack_channels" in str(w.message)
        and "1.2.0" in str(w.message)
    ]
    assert matched, (
        "warning message MUST name the old key, the replacement, and the "
        f"spec version 1.2.0; got {[str(w.message) for w in dep_warnings]!r}"
    )

    # The old-key value still populates the scalar attribute.
    assert config is not None
    assert config.cncf_slack_channel == "#legacy-channel"


def test_no_warning_when_cncf_slack_channel_absent(tmp_path: Path) -> None:
    """ABSENCE: a migrated repo (or one that never had the field) MUST NOT
    be nagged."""
    repo = _write_project_yaml(
        tmp_path,
        """\
name: migrated
repositories:
  - example/repo
slack_channels:
  - name: "#modern-channel"
    workspace: cncf
    primary: true
""",
    )

    reader = DotProjectReader(str(repo))
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        config = reader.read()

    dep_warnings = [w for w in record if issubclass(w.category, DeprecationWarning)]
    assert not dep_warnings, (
        "MUST NOT emit a DeprecationWarning when cncf_slack_channel is absent; "
        f"got {[str(w.message) for w in dep_warnings]!r}"
    )

    # Scalar attribute stays empty when the old key is absent.
    assert config is not None
    assert config.cncf_slack_channel == ""
