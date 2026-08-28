"""Regression guard for issue #402.

Every `llm_eval` pass in `openssf-baseline.toml` previously declared
`files_to_include = ["$FOUND_FILE"]`. When the deterministic tier
(pattern/regex) resolved INCONCLUSIVE -- i.e., no candidate file
matched -- the `$FOUND_FILE` variable was never bound, so llm_eval
fired with `file_contents = {}` and the LLM had nothing to reason
about. In a 29-repo survey the LLM tier produced 9 non-answers, one
per PENDING_LLM consultation.

Fix (issue #402 option 1, TOML-only): every `llm_eval` pass now
enumerates real candidate paths so the handler's on-disk skip logic
can populate `file_contents` even without a preceding `file_exists`
PASS. This test locks that fix in place -- if a new `llm_eval` block
ships with lone `$FOUND_FILE`, we want it to fail here rather than in
a live audit's empty consultation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore

_FRAMEWORK_TOML = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "darnit-baseline"
    / "src"
    / "darnit_baseline"
    / "openssf-baseline.toml"
)


def _iter_llm_eval_passes():
    """Yield (control_id, pass_index, pass_dict) for every llm_eval pass."""
    with open(_FRAMEWORK_TOML, "rb") as f:
        framework = tomllib.load(f)
    for control_id, control in framework.get("controls", {}).items():
        for i, p in enumerate(control.get("passes", [])):
            if p.get("handler") == "llm_eval":
                yield control_id, i, p


class TestLLMEvalFilesToInclude:
    def test_no_pass_ships_lone_found_file(self):
        """FR: `files_to_include` MUST enumerate real candidate paths.

        A bare `["$FOUND_FILE"]` produces `file_contents = {}` when the
        preceding pass didn't set `gathered_evidence["found_file"]`
        (which is the common case for `pattern` -> `llm_eval` shapes
        that skip `file_exists`).
        """
        offenders: list[str] = []
        for control_id, idx, p in _iter_llm_eval_passes():
            fti = p.get("files_to_include", [])
            if fti == ["$FOUND_FILE"]:
                offenders.append(f"{control_id} pass[{idx}]")
        assert not offenders, (
            "The following llm_eval passes ship with lone $FOUND_FILE, "
            "which produces empty file_contents when the deterministic "
            "tier resolves INCONCLUSIVE (see issue #402). Enumerate real "
            "candidate paths instead.\n\n"
            + "\n".join(f"  - {o}" for o in offenders)
        )

    def test_every_llm_eval_declares_files_to_include(self):
        """No llm_eval pass may omit `files_to_include` entirely."""
        missing: list[str] = []
        for control_id, idx, p in _iter_llm_eval_passes():
            if "files_to_include" not in p:
                missing.append(f"{control_id} pass[{idx}]")
        assert not missing, (
            "Every llm_eval pass MUST declare `files_to_include` so the "
            "handler can gather file content for the consultation. "
            "Missing on:\n\n" + "\n".join(f"  - {m}" for m in missing)
        )

    def test_files_to_include_within_handler_cap(self):
        """Handler caps at `files_to_include[:5]` (`builtin_handlers.py`).

        Declaring more than 5 is not an error but silently drops entries.
        Flag it here so an author knows to prune.
        """
        overcapped: list[str] = []
        for control_id, idx, p in _iter_llm_eval_passes():
            fti = p.get("files_to_include", [])
            if len(fti) > 5:
                overcapped.append(
                    f"{control_id} pass[{idx}] has {len(fti)} entries"
                )
        assert not overcapped, (
            "llm_eval handler caps files_to_include at 5 entries; "
            "additional entries are silently dropped. Prune:\n\n"
            + "\n".join(f"  - {o}" for o in overcapped)
        )
