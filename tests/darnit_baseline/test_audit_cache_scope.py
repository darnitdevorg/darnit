"""The Baseline audit tool tells the cache when a profile narrowed the audit (#542)."""

from __future__ import annotations

import subprocess

import pytest


@pytest.mark.parametrize(("profile", "expected"), [("level1_quick", True), (None, False)])
def test_profile_audit_is_recorded_as_filtered(tmp_path, monkeypatch, profile, expected) -> None:
    captured: dict = {}

    def recording_audit(**kwargs):
        captured.update(kwargs)
        return [], {}

    monkeypatch.setattr("darnit.tools.audit.run_sieve_audit", recording_audit)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    from darnit_baseline.tools import audit_openssf_baseline

    try:
        audit_openssf_baseline(local_path=str(tmp_path), profile=profile, auto_init_config=False)
    except Exception:  # noqa: BLE001 - only the arguments handed to the audit matter here
        pass

    assert captured["cache_filtered"] is expected
