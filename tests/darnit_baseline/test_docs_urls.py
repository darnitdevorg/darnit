"""Every OSPS control links to its requirement in the Baseline version darnit implements (#494).

Control ``docs_url`` values used to point at ``versions/2025-10-10`` with
``#OSPS-AC-01.01``-style fragments, while the framework implements
``OSPS v2026.02.19`` (``[metadata] spec_version``) and the Baseline site's
anchors look like ``#osps-ac-0101``. So every link opened the wrong
version's page at the top. The expected URL is built by the same helpers the
SARIF formatter uses for ``helpUri``, so the two cannot drift apart.
"""

from __future__ import annotations

import pytest

from darnit.config.merger import load_framework_by_name
from darnit_baseline.formatters.sarif import _baseline_rule_anchor, _baseline_spec_url


@pytest.fixture(scope="module")
def framework():
    return load_framework_by_name("openssf-baseline")


@pytest.mark.unit
def test_anchor_matches_the_baseline_site_format() -> None:
    assert _baseline_rule_anchor("OSPS-AC-01.01") == "osps-ac-0101"
    assert _baseline_rule_anchor("OSPS-VM-06.02") == "osps-vm-0602"


@pytest.mark.unit
def test_spec_url_follows_spec_version(framework) -> None:
    slug = framework.metadata.spec_version.replace("OSPS", "").replace("v", "").strip().replace(".", "-")
    assert _baseline_spec_url(framework.metadata.spec_version) == f"https://baseline.openssf.org/versions/{slug}"


@pytest.mark.unit
def test_every_osps_control_links_to_its_requirement(framework) -> None:
    spec_url = _baseline_spec_url(framework.metadata.spec_version)
    wrong = {
        cid: control.docs_url
        for cid, control in framework.controls.items()
        if cid.startswith("OSPS-") and control.docs_url != f"{spec_url}#{_baseline_rule_anchor(cid)}"
    }
    assert not wrong, f"docs_url does not match {spec_url}#<anchor> for: {wrong}"
