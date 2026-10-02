"""MCP tools for the community-spec framework."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from darnit.core.logging import get_logger

if TYPE_CHECKING:
    from darnit.config.framework_schema import RemediationConfig
    from darnit.remediation.executor import RemediationResult

logger = get_logger("darnit_csl.mcp_tools")

_PLACEHOLDER_RE = re.compile(
    r"(?i)(real name|real@email|example\.(com|org|net)|\bTODO\b|\bFIXME\b|\bTBD\b"
    r"|<name>|<email>|your name|firstname|lastname|insert name|name one|name two"
    r"|john doe|jane doe|_{5,}|\[Ideally list two different individuals)"
)


_MAILING_LIST_RE = re.compile(
    r"(?i)(@googlegroups\.com|@groups\.|@lists?\.|[._-]lists?@|listserv|majordomo"
    r"|\bno-?reply\b|@.*\.(?:groups|mailman)\b)"
)


def _looks_like_mailing_list(value: str) -> bool:
    """True if the contact is a group address rather than a named individual."""
    return bool(_MAILING_LIST_RE.search(value))


def _looks_like_placeholder(value: str) -> bool:
    """True if the value is empty or still looks like unfilled template text."""
    return not value.strip() or bool(_PLACEHOLDER_RE.search(value))


_URL_RE = re.compile(r"https?://")

_COC_CANDIDATES = (
    "CODE_OF_CONDUCT.md",
    "CODE-OF-CONDUCT.md",
    "code-of-conduct.md",
    "code_of_conduct.md",
    ".github/CODE_OF_CONDUCT.md",
    ".github/CODE-OF-CONDUCT.md",
    "docs/CODE_OF_CONDUCT.md",
    "docs/CODE-OF-CONDUCT.md",
)


def _find_existing_coc(repo: Path) -> str | None:
    """Relative path of an existing Code of Conduct file in the repo, if any."""
    for rel in _COC_CANDIDATES:
        if (repo / rel).is_file():
            return rel
    return None


_PARAMETERS = {
    "csl_spec_name": "spec_name",
    "csl_working_group_scope": "scope",
    "csl_coc_contacts": "coc_contacts",
    "csl_code_license": "code_license",
    "csl_governance_mode": "governance_mode",
    "csl_governance_reference": "governance_reference",
    "csl_coc_policy": "coc_policy",
    "csl_coc_reference": "coc_reference",
}

_ORDER = ["CSL-01.01", "CSL-01.02", "CSL-02.01", "CSL-03.01", "CSL-04.01", "CSL-05.01"]

_README_CANDIDATES = ("README.md", "README.rst", "readme.md", "Readme.md", "README.txt")
_MARKDOWN_LINKS = (
    "\n## Governance & Licensing\n"
    "- [Scope](governance/02-scope.md)\n"
    "- [Notices](governance/03-notices.md)\n"
    "- [License](governance/04-license.md)\n"
    "- [Governance](governance/05-governance.md)\n"
)
_RST_LINKS = (
    "\nGovernance & Licensing\n----------------------\n\n"
    "- `Scope <governance/02-scope.md>`_\n"
    "- `Notices <governance/03-notices.md>`_\n"
    "- `License <governance/04-license.md>`_\n"
    "- `Governance <governance/05-governance.md>`_\n"
)


def _readme_links(repo: Path) -> RemediationConfig | None:
    """The README edit linking the governance files, as a remediation the executor previews and writes.

    None when the README already links the scope file.
    """
    from darnit.config.framework_schema import HandlerInvocation, RemediationConfig

    readme = next((name for name in _README_CANDIDATES if (repo / name).is_file()), None)
    text = (repo / readme).read_bytes().decode("utf-8") if readme else "# Specification\n"
    if "02-scope.md" in text:
        return None
    path = readme or "README.md"
    block = _RST_LINKS if path.lower().endswith(".rst") else _MARKDOWN_LINKS
    return RemediationConfig(
        handlers=[HandlerInvocation(handler="file_create", path=path, content=text + block, overwrite=True)]
    )


def _preview_report(repo: Path, previews: list[tuple[str, RemediationResult]]) -> str:
    lines = [
        f"# CSL remediation preview for {repo.name}",
        "",
        "Nothing was written. Re-run with dry_run=False to write exactly these changes.",
    ]
    for cid, preview in previews:
        for item in preview.plan:
            for change in item.file_changes:
                if not change.changes:
                    lines += ["", f"## {cid}: {change.path} unchanged ({change.reason})"]
                    continue
                content = (change.content or "").rstrip("\n")
                lines += ["", f"## {cid}: {change.action} {change.path}", "", "```", content, "```"]
        if not preview.success:
            lines += ["", f"## {cid}: error", "", preview.message]
    return "\n".join(lines)


async def remediate_community_spec(
    local_path: str,
    scope: str | None = None,
    coc_contacts: str | None = None,
    code_license: str | None = None,
    governance_mode: str | None = None,
    governance_reference: str | None = None,
    coc_policy: str | None = None,
    coc_reference: str | None = None,
    spec_name: str | None = None,
    add_readme_links: bool = True,
    dry_run: bool = True,
) -> str:
    """Write the Community Specification License (CSL 1.0) file set into a repo.

    Each parameter other than ``local_path``, ``add_readme_links`` and
    ``dry_run`` is a person's decision recorded under a CSL context key. An
    omitted one is taken from confirmed project context only; if that has
    none either, the tool writes nothing and reports
    ``confirmation required: <key>`` (feature 042, FR-008).

    With ``dry_run`` (the default) nothing is written: the result lists every
    file the remediation would create or change, with its content. With
    ``dry_run=False`` the remediation executor writes exactly those files,
    including the README links, and records them in the run manifest whose
    run id the result reports (feature 043, framework-design 15.8).
    """
    from darnit.config import load_framework_config
    from darnit.config.context_resolve import resolve_context
    from darnit.config.context_storage import framework_definitions
    from darnit.remediation.executor import RemediationExecutor
    from darnit.tools.audit import run_sieve_audit

    repo = Path(local_path).resolve()
    if not repo.exists():
        return f"Error: repository path not found: {repo}"

    fw_path = Path(__file__).parent / "community-spec.toml"
    fw = load_framework_config(fw_path)
    resolved = resolve_context(str(repo), framework_definitions(fw), detect=False)
    confirmed = resolved.usable()

    def decided(value: str | None, key: str) -> str | None:
        return value if value is not None else confirmed.get(key)

    scope = decided(scope, "csl_working_group_scope")
    coc_contacts = decided(coc_contacts, "csl_coc_contacts")
    code_license = decided(code_license, "csl_code_license")
    governance_mode = decided(governance_mode, "csl_governance_mode")
    governance_reference = decided(governance_reference, "csl_governance_reference")
    coc_policy = decided(coc_policy, "csl_coc_policy")
    coc_reference = decided(coc_reference, "csl_coc_reference")
    spec_name = decided(spec_name, "csl_spec_name")

    if coc_policy is not None:
        coc_policy = coc_policy.strip().lower()

    # Org-first: a project that already has a Code of Conduct (its own file,
    # an org community repo, or a foundation CoC such as CNCF / LF / JDF)
    # must point at it rather than naming individuals.
    existing_coc = _find_existing_coc(repo)
    if coc_policy != "org" and existing_coc:
        return (
            f"Error: this repository already has a Code of Conduct at "
            f"'{existing_coc}'. Re-run with coc_policy='org' and coc_reference "
            "set to one markdown sentence linking that document. Nothing was "
            "written."
        )

    if coc_policy == "org":
        if coc_reference is None or _looks_like_placeholder(coc_reference) or not _URL_RE.search(coc_reference):
            return (
                "Error: coc_policy='org' requires coc_reference: one markdown "
                "sentence linking the project's existing Code of Conduct (the "
                "repo's own file, the org's community repo, or a foundation "
                "CoC such as CNCF / LF / JDF). Check those locations first; "
                "only fall back to named individuals when no such CoC exists. "
                "Nothing was written."
            )
        # The linked CoC defines the reporting procedure; no inline contacts.
        coc_contacts = ""
    elif coc_contacts is not None:
        if _looks_like_placeholder(coc_contacts):
            return (
                f"Error: coc_contacts looks like a placeholder ({coc_contacts!r}). "
                "CSL requires a real Code of Conduct contact, ideally two named "
                "individuals with emails. Nothing was written."
            )

        if _looks_like_mailing_list(coc_contacts):
            return (
                f"Error: coc_contacts is a group address ({coc_contacts!r}). CSL asks "
                "for named individuals rather than a generic mailing list, so that "
                "someone filing a complaint knows exactly who receives it. Ask the "
                "project who should be listed. Nothing was written."
            )

    # The csl_scope template supplies the "# Scope" heading and the closing
    # "Any changes of Scope are not retroactive." line. A caller that drafts a
    # full scope document will include both, so strip them here rather than
    # emitting each one twice.
    if scope is not None:
        scope = re.sub(r"\A#\s*Scope\s*\n+", "", scope.strip())
        scope = re.sub(
            r"\n*Any changes of Scope are not retroactive\.\s*\Z", "", scope
        ).strip()

    decisions = {
        "csl_spec_name": spec_name,
        "csl_working_group_scope": scope,
        "csl_coc_contacts": coc_contacts,
        "csl_code_license": code_license,
        "csl_governance_mode": governance_mode,
        "csl_governance_reference": governance_reference,
        "csl_coc_policy": coc_policy,
        "csl_coc_reference": coc_reference,
    }
    context_values = {key: value for key, value in decisions.items() if value is not None}

    executor = RemediationExecutor(
        local_path=str(repo), owner="", repo="",
        templates=fw.templates, context_values=context_values,
        framework_path=str(fw_path),
        unconfirmed_keys=resolved.unusable_keys(),
    )

    remediations = [
        (cid, fw.controls[cid].remediation)
        for cid in _ORDER
        if cid in fw.controls and fw.controls[cid].remediation is not None
    ]
    if add_readme_links and (readme_step := _readme_links(repo)) is not None:
        remediations.append(("CSL-06.01", readme_step))
    previews = [(cid, executor.execute(cid, remediation, dry_run=True)) for cid, remediation in remediations]
    needed = sorted({planned.confirmation_required for _, planned in previews if planned.confirmation_required})
    if needed:
        return "\n".join([
            "Error: these decisions are needed before any file is written. Ask the "
            "person for each one and pass their answer as the named parameter; do "
            "not choose a value for them.",
            *(f"- confirmation required: {key} (parameter {_PARAMETERS[key]})" for key in needed),
            "Nothing was written.",
            "To keep an answer for later runs, record it with this server's "
            "confirm_project_data(<key>=<the person's answer>, owner=..., repo=...).",
        ])

    if dry_run:
        return _preview_report(repo, previews)

    written: list[str] = []
    not_written: list[str] = []
    errors: list[str] = []
    for cid, remediation in remediations:
        try:
            res = executor.execute(cid, remediation, dry_run=False)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cid}: {e}")
            continue
        written += [c.path for c in res.file_changes if c.changes]
        not_written += [f"{c.path} ({c.reason})" for c in res.file_changes if c.reason == "user_changes_present"]
        if not res.success:
            errors.append(f"{cid}: {res.message}")

    results, _ = run_sieve_audit(
        owner="", repo="", local_path=str(repo), default_branch="main",
        apply_user_config=False, framework_name="community-spec", stop_on_llm=False,
    )
    lines = [f"# CSL remediation for {repo.name}", "",
             f"Files written: {', '.join(written) if written else 'none'}"]
    if executor.run_id:
        lines.append(f"Run id: {executor.run_id}")
    if not_written:
        lines += ["", "Not written (uncommitted changes in the file):"] + [f"- {p}" for p in not_written]
    if errors:
        lines += ["", "Errors:"] + [f"- {e}" for e in errors]
    lines += ["", "## Re-audit"]
    lines += [f"- {r.get('id')}: {r.get('status')}" for r in sorted(results, key=lambda r: r.get("id", ""))]
    return "\n".join(lines)
