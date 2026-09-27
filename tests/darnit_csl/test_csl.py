"""Tests for the darnit-csl (Community Specification License) plugin."""

from __future__ import annotations

from pathlib import Path

import pytest
from darnit_csl import get_framework_path, register
from darnit_csl.implementation import CommunitySpecImplementation

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Plugin protocol + TOML validity
# ---------------------------------------------------------------------------


class TestImplementation:
    def test_register_returns_instance(self) -> None:
        impl = register()
        assert isinstance(impl, CommunitySpecImplementation)

    def test_identity(self) -> None:
        impl = CommunitySpecImplementation()
        assert impl.name == "community-spec"
        assert impl.spec_version == "CSL 1.0"

    def test_framework_path_exists(self) -> None:
        path = get_framework_path()
        assert path.is_file()
        assert path.name == "community-spec.toml"

    def test_framework_config_loads_and_validates(self) -> None:
        from darnit.config import load_framework_config, validate_framework_config

        cfg = load_framework_config(get_framework_path())
        assert cfg.metadata.name == "community-spec"
        # 7 controls, all templates resolvable
        assert len(cfg.controls) == 7
        assert validate_framework_config(cfg) == []

    def test_templates_resolve_on_disk(self) -> None:
        base = get_framework_path().parent
        for name in (
            "csl_cla",
            "csl_license",
            "csl_scope",
            "csl_notices",
            "csl_license_dual",
            "csl_governance",
            "csl_governance_reference",
        ):
            assert (base / "templates" / f"{name}.tmpl").is_file()


# ---------------------------------------------------------------------------
# Content-validity audit: the novel logic (missing / placeholder / filled)
# ---------------------------------------------------------------------------


def _status(cid: str, repo: Path, framework_name: str = "community-spec") -> str:
    """Run a single control through the canonical audit pipeline; return its status."""
    from darnit.tools.audit import run_sieve_audit

    results, _ = run_sieve_audit(
        owner="o",
        repo="r",
        local_path=str(repo),
        default_branch="main",
        apply_user_config=False,
        framework_name=framework_name,
        stop_on_llm=False,
    )
    match = [r for r in results if r.get("id") == cid]
    assert match, f"no result for {cid}"
    return match[0].get("status", "UNKNOWN")


SCOPE_PLACEHOLDER = (
    "# Scope\n\n[Include a detailed description of this Working Group's Scope.]\n\n"
    "Any changes of Scope are not retroactive.\n"
)
SCOPE_FILLED = (
    "# Scope\n\nThis Working Group standardizes the Foo format.\n\n"
    "Any changes of Scope are not retroactive.\n"
)
NOTICES_BLANK = (
    "# Notices\n\n## Code of Conduct\n\n"
    "Contact for Code of Conduct issues or inquiries:  _________________\n"
)
NOTICES_FILLED = (
    "# Notices\n\n## Code of Conduct\n\n"
    "Contact for Code of Conduct issues or inquiries:  Jane (@jane), John (@john)\n"
)
NOTICES_WITH_GUIDANCE = (
    "# Notices\n\n## Code of Conduct\n\n"
    "Contact for Code of Conduct issues or inquiries:  Jane (@jane), John (@john)\n\n"
    "[Ideally list two different individuals above (not a generic mailing list) "
    "as someone submitting a Code of Conduct complaint will want to know exactly "
    "who is receiving the complaint. We recommend two individuals in the case one "
    "of the individuals is the subject of or directly involved in the subject of a complaint.]\n"
)


class TestScopeContentAudit:
    """CSL-02.01 must distinguish missing / placeholder / filled."""

    def test_missing_fails(self, tmp_path: Path) -> None:
        assert _status("CSL-02.01", tmp_path) == "FAIL"

    def test_placeholder_fails(self, tmp_path: Path) -> None:
        gov = tmp_path / "governance"
        gov.mkdir()
        (gov / "02-scope.md").write_text(SCOPE_PLACEHOLDER)
        assert _status("CSL-02.01", tmp_path) == "FAIL"

    def test_filled_needs_judgment(self, tmp_path: Path) -> None:
        # Feature 041: a keyword match is evidence, not a PASS; content awaits a judgment.
        gov = tmp_path / "governance"
        gov.mkdir()
        (gov / "02-scope.md").write_text(SCOPE_FILLED)
        assert _status("CSL-02.01", tmp_path) == "WARN"


class TestNoticesContentAudit:
    """CSL-03.01 must fail when the CoC contact line is still blank."""

    def test_blank_contact_fails(self, tmp_path: Path) -> None:
        gov = tmp_path / "governance"
        gov.mkdir()
        (gov / "03-notices.md").write_text(NOTICES_BLANK)
        assert _status("CSL-03.01", tmp_path) == "FAIL"

    def test_filled_contact_needs_judgment(self, tmp_path: Path) -> None:
        # Feature 041: a keyword match is evidence, not a PASS; content awaits a judgment.
        gov = tmp_path / "governance"
        gov.mkdir()
        (gov / "03-notices.md").write_text(NOTICES_FILLED)
        assert _status("CSL-03.01", tmp_path) == "WARN"

    def test_leftover_guidance_text_fails(self, tmp_path: Path) -> None:
        # Real contacts but the bracketed drafting guidance was never removed.
        gov = tmp_path / "governance"
        gov.mkdir()
        (gov / "03-notices.md").write_text(NOTICES_WITH_GUIDANCE)
        assert _status("CSL-03.01", tmp_path) == "FAIL"


CSL_LICENSE_TEXT = (
    "# Community Specification License 1.0\n\n"
    "**The Purpose of this License.** This License sets forth the terms ...\n"
)
APACHE_LICENSE_TEXT = "                                 Apache License\n                           Version 2.0\n"


class TestLicenseContentDetection:
    """CSL-01.02 must detect the CSL license by content, under any filename
    (TUF ships it as LICENSE.md, Uptane as LICENSE), and must NOT match a
    non-CSL license."""

    def test_csl_license_named_license_md_passes(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE.md").write_text(CSL_LICENSE_TEXT)
        assert _status("CSL-01.02", tmp_path) == "PASS"

    def test_csl_license_named_license_no_ext_passes(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(CSL_LICENSE_TEXT)
        assert _status("CSL-01.02", tmp_path) == "PASS"

    def test_apache_license_fails(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(APACHE_LICENSE_TEXT)
        assert _status("CSL-01.02", tmp_path) == "FAIL"

    def test_no_license_fails(self, tmp_path: Path) -> None:
        assert _status("CSL-01.02", tmp_path) == "FAIL"

    def test_dual_license_reference_does_not_false_match(self, tmp_path: Path) -> None:
        # 04-license.md references the CSL by name in prose but is not the license.
        gov = tmp_path / "governance"
        gov.mkdir()
        (gov / "04-license.md").write_text(
            "# Licenses\n\nSpecifications are subject to the Community Specification License 1.0.\n"
        )
        assert _status("CSL-01.02", tmp_path) == "FAIL"


class TestClaContentDetection:
    """CSL-01.01 must detect the CLA by content under a non-canonical name."""

    def test_cla_named_cla_md_passes(self, tmp_path: Path) -> None:
        (tmp_path / "CLA.md").write_text(
            "# Community Specification Contributor License Agreement 1.0\n\nBy making a Contribution ...\n"
        )
        assert _status("CSL-01.01", tmp_path) == "PASS"

    def test_no_cla_fails(self, tmp_path: Path) -> None:
        assert _status("CSL-01.01", tmp_path) == "FAIL"


FULL_CSL_GOVERNANCE = (
    "# Community Specification Governance Policy 1.0\n\n"
    "This document provides the governance policy for specifications ...\n"
)
UMBRELLA_GOVERNANCE = (
    "# Governance\n\nThis Working Group develops specifications using the "
    "Community Specification process. The following Community Specification "
    "Roles apply: Maintainer, Editor, Participants.\n"
)
GENERIC_GOVERNANCE = (
    "# Governance\n\n## Project Roles\n\nContributors submit pull requests. "
    "Maintainers review and merge. Decisions are by lazy consensus.\n"
)


class TestGovernanceContentDetection:
    """CSL-05.01 must require CSL-specific governance, not just any GOVERNANCE.md."""

    def test_full_csl_policy_needs_judgment(self, tmp_path: Path) -> None:
        # Feature 041: a keyword match is evidence, not a PASS; content awaits a judgment.
        (tmp_path / "GOVERNANCE.md").write_text(FULL_CSL_GOVERNANCE)
        assert _status("CSL-05.01", tmp_path) == "WARN"

    def test_umbrella_reference_needs_judgment(self, tmp_path: Path) -> None:
        # References an umbrella governance but documents the CSL roles/process.
        (tmp_path / "GOVERNANCE.md").write_text(UMBRELLA_GOVERNANCE)
        assert _status("CSL-05.01", tmp_path) == "WARN"

    def test_generic_governance_fails(self, tmp_path: Path) -> None:
        # A generic GOVERNANCE.md that never mentions Community Specification.
        (tmp_path / "GOVERNANCE.md").write_text(GENERIC_GOVERNANCE)
        assert _status("CSL-05.01", tmp_path) == "FAIL"

    def test_no_governance_fails(self, tmp_path: Path) -> None:
        assert _status("CSL-05.01", tmp_path) == "FAIL"


# ---------------------------------------------------------------------------
# Remediation: template substitution + governance when-clause
# ---------------------------------------------------------------------------


def _executor(repo: Path, context_values: dict):
    from darnit.config import load_framework_config
    from darnit.remediation.executor import RemediationExecutor

    cfg = load_framework_config(get_framework_path())
    ex = RemediationExecutor(
        local_path=str(repo),
        owner="o",
        repo="r",
        templates=cfg.templates,
        context_values=context_values,
        framework_path=str(get_framework_path()),
    )
    return cfg, ex


class TestRemediation:
    def test_scope_filled_from_context(self, tmp_path: Path) -> None:
        cfg, ex = _executor(tmp_path, {"csl_working_group_scope": "Standardizes Foo."})
        res = ex.execute("CSL-02.01", cfg.controls["CSL-02.01"].remediation, dry_run=False)
        assert res.success
        out = (tmp_path / "governance" / "02-scope.md").read_text()
        assert "Standardizes Foo." in out
        assert "[Include a detailed description" not in out

    def test_scope_carries_llm_enhance(self, tmp_path: Path) -> None:
        cfg, ex = _executor(tmp_path, {})
        res = ex.execute("CSL-02.01", cfg.controls["CSL-02.01"].remediation, dry_run=False)
        assert any("llm_enhance" in h for h in res.details.get("handlers", []))

    def test_dual_license_uses_chosen_code_license(self, tmp_path: Path) -> None:
        cfg, ex = _executor(tmp_path, {"csl_code_license": "Apache-2.0"})
        ex.execute("CSL-04.01", cfg.controls["CSL-04.01"].remediation, dry_run=False)
        out = (tmp_path / "governance" / "04-license.md").read_text()
        assert "Apache-2.0 license" in out

    def test_dual_license_accepts_agpl(self, tmp_path: Path) -> None:
        cfg, ex = _executor(tmp_path, {"csl_code_license": "AGPL-3.0"})
        ex.execute("CSL-04.01", cfg.controls["CSL-04.01"].remediation, dry_run=False)
        out = (tmp_path / "governance" / "04-license.md").read_text()
        assert "AGPL-3.0 license" in out

    def test_governance_default_is_full_policy(self, tmp_path: Path) -> None:
        cfg, ex = _executor(tmp_path, {})
        ex.execute("CSL-05.01", cfg.controls["CSL-05.01"].remediation, dry_run=False)
        out = (tmp_path / "governance" / "05-governance.md").read_text()
        assert "Community Specification Governance Policy 1.0" in out

    def test_governance_umbrella_references_existing(self, tmp_path: Path) -> None:
        cfg, ex = _executor(
            tmp_path,
            {
                "csl_governance_mode": "umbrella",
                "csl_governance_reference": "CNCF governance (https://example.org/gov)",
            },
        )
        ex.execute("CSL-05.01", cfg.controls["CSL-05.01"].remediation, dry_run=False)
        out = (tmp_path / "governance" / "05-governance.md").read_text()
        assert "CNCF governance" in out
        assert "not superseded" in out
        # Must be the short reference stub, not the full verbatim policy body.
        assert "Ways of Working" not in out

    def test_notices_render_drops_guidance_and_fills_contacts(self, tmp_path: Path) -> None:
        cfg, ex = _executor(tmp_path, {"csl_coc_contacts": "Jane (@jane), John (@john)"})
        res = ex.execute("CSL-03.01", cfg.controls["CSL-03.01"].remediation, dry_run=False)
        assert res.success
        out = (tmp_path / "governance" / "03-notices.md").read_text()
        assert "Jane (@jane), John (@john)" in out
        assert "[Ideally list two different individuals" not in out
        assert "_____" not in out

    def test_cla_render_references_current_upstream_filenames(self, tmp_path: Path) -> None:
        cfg, ex = _executor(tmp_path, {})
        res = ex.execute("CSL-01.01", cfg.controls["CSL-01.01"].remediation, dry_run=False)
        assert res.success
        out = (tmp_path / "governance" / "00-contributor-license-agreement.md").read_text()
        for ref in (
            "01-community-specification-license-v1.md",
            "05-governance.md",
            "06-contributing.md",
            "08-code-of-conduct.md",
        ):
            assert ref in out, ref
        assert ".0_Community_Specification_License-v1.md" not in out
        assert "5._Governance.md" not in out

    def test_remediated_repo_reaudit(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text(
            "# Foo\n\n## Governance\n- [Scope](governance/02-scope.md)\n"
            "- [Notices](governance/03-notices.md)\n"
        )
        cfg, ex = _executor(
            tmp_path,
            {
                "csl_working_group_scope": "Standardizes Foo.",
                "csl_coc_contacts": "Jane (@jane), John (@john)",
            },
        )
        for cid in ("CSL-01.01", "CSL-01.02", "CSL-02.01", "CSL-03.01", "CSL-04.01", "CSL-05.01"):
            ex.execute(cid, cfg.controls[cid].remediation, dry_run=False)
        # Feature 041: the CLA and license documents exist, so they PASS; the
        # content controls have evidence but await a judgment, so they are WARN.
        for cid in ("CSL-01.01", "CSL-01.02"):
            assert _status(cid, tmp_path) == "PASS", cid
        for cid in ("CSL-02.01", "CSL-03.01", "CSL-04.01", "CSL-05.01", "CSL-06.01"):
            assert _status(cid, tmp_path) == "WARN", cid


# ---------------------------------------------------------------------------
# Optional (facultative) framework: community-spec-optional
# ---------------------------------------------------------------------------


class TestOptionalFramework:
    """The optional files (06/07/08) live in a separate framework so they never
    affect the required CSL score, and are presence-checked on demand."""

    def test_optional_framework_loads(self) -> None:
        from darnit_csl import get_optional_framework_path

        from darnit.config import (
            load_framework_config,
            validate_framework_config,
        )

        path = get_optional_framework_path()
        assert path.is_file()
        assert path.name == "community-spec-optional.toml"
        cfg = load_framework_config(path)
        assert cfg.metadata.name == "community-spec-optional"
        assert len(cfg.controls) == 3
        assert validate_framework_config(cfg) == []

    def test_required_framework_excludes_optional_controls(self) -> None:
        # The optional IDs must not leak into the required framework.
        from darnit.config import load_framework_config

        cfg = load_framework_config(get_framework_path())
        assert not any(cid.startswith("CSL-OPT-") for cid in cfg.controls)

    def test_contributing_detected(self, tmp_path: Path) -> None:
        (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n")
        assert _status("CSL-OPT-01", tmp_path, "community-spec-optional") == "PASS"

    def test_code_of_conduct_detected(self, tmp_path: Path) -> None:
        (tmp_path / "CODE_OF_CONDUCT.md").write_text("# Code of Conduct\n")
        assert _status("CSL-OPT-03", tmp_path, "community-spec-optional") == "PASS"

    def test_missing_optional_files_fail(self, tmp_path: Path) -> None:
        for cid in ("CSL-OPT-01", "CSL-OPT-02", "CSL-OPT-03"):
            assert _status(cid, tmp_path, "community-spec-optional") == "FAIL"


class TestOrgCocMode:
    ORG_REF = (
        "Example is a [CNCF](https://www.cncf.io/) project and follows the "
        "[Example Code of Conduct](https://github.com/example/community/blob/main/CODE-OF-CONDUCT.md)."
    )

    def test_org_render_has_reference_and_no_contact_line(self, tmp_path: Path) -> None:
        cfg, ex = _executor(tmp_path, {"csl_coc_policy": "org", "csl_coc_reference": self.ORG_REF})
        res = ex.execute("CSL-03.01", cfg.controls["CSL-03.01"].remediation, dry_run=False)
        assert res.success
        out = (tmp_path / "governance" / "03-notices.md").read_text()
        assert self.ORG_REF in out
        assert "Contact for Code of Conduct issues or inquiries" not in out
        assert "_____" not in out
        assert "[Ideally list two different individuals" not in out

    def test_org_reference_only_notices_is_not_a_placeholder(self, tmp_path: Path) -> None:
        # Feature 041: the filled-contact pattern matches (not FAIL); content awaits a judgment.
        gov = tmp_path / "governance"
        gov.mkdir()
        (gov / "03-notices.md").write_text(
            "# Notices\n\n## Code of Conduct\n\n" + self.ORG_REF + "\n\n## License Acceptance\n"
        )
        assert _status("CSL-03.01", tmp_path) == "WARN"

    def test_tool_rejects_individuals_when_repo_has_coc(self, tmp_path: Path) -> None:
        import asyncio

        from darnit_csl.mcp_tools import remediate_community_spec

        (tmp_path / "CODE_OF_CONDUCT.md").write_text("# CoC\n")
        out = asyncio.run(remediate_community_spec(
            local_path=str(tmp_path), scope="s",
            coc_contacts="Jane (@jane), John (@john)",
        ))
        assert out.startswith("Error:")
        assert "coc_policy='org'" in out

    def test_tool_org_requires_linked_reference(self, tmp_path: Path) -> None:
        import asyncio

        from darnit_csl.mcp_tools import remediate_community_spec

        out = asyncio.run(remediate_community_spec(
            local_path=str(tmp_path), scope="s", coc_policy="org", coc_reference="TODO",
        ))
        assert out.startswith("Error:")

