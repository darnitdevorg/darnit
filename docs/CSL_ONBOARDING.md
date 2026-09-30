# CSL 1.0 onboarding with darnit

How to make any specification repository compliant with the
[Community Specification License 1.0](https://github.com/CommunitySpecification/1.0)
using the `community-spec` framework (`darnit-csl`), and reproduce the process
we used for DSSE, in-toto, TUF, and Uptane.

## What it produces

The required CSL file set, generated from templates and audited:

| File | Content |
|---|---|
| `governance/00-contributor-license-agreement.md` | CSL Contributor License Agreement 1.0 (verbatim, with working links to the upstream documents) |
| `governance/01-community-specification-license-v1.md` | Community Specification License 1.0 (verbatim) |
| `governance/02-scope.md` | The Working Group's Scope — **you draft this; it bounds the patent commitment** |
| `governance/03-notices.md` | Notices with the Code of Conduct pointer (org-first, see below) |
| `governance/04-license.md` | Dual license: CSL for the spec, your chosen license for source/sample code |
| `governance/05-governance.md` | Full CSL Governance Policy, or a stub referencing umbrella governance (e.g. CNCF) |
| `README` links | A "Governance & Licensing" section pointing at the files above |

Seven controls verify it: `CSL-01.01` (CLA), `CSL-01.02` (license, detected by
content under any filename), `CSL-02.01` (scope is real, not the bracketed
placeholder), `CSL-03.01` (notices name a real contact **or** point at an
org-level Code of Conduct — blanks, placeholder names, and leftover drafting
guidance all FAIL), `CSL-04.01` (dual license), `CSL-05.01` (CSL-specific
governance), `CSL-06.01` (README discoverability).

## What you must supply

1. **Scope prose.** Write what the Working Group standardizes and what it
   excludes, grounded in the repository's actual documents — never generic
   filler, never the bracketed template text. This is a legal boundary, so a
   human must review it before any PR.
2. **Code of Conduct — org-first.** If the project already has a Code of
   Conduct (its own `CODE_OF_CONDUCT` file, the org's community or `.github`
   repo, or a foundation CoC such as CNCF, LF, or JDF), point at it:
   `coc_policy='org'` plus `coc_reference` — one markdown sentence linking
   that document. The notices then name no individuals; the linked CoC
   defines the reporting procedure. The remediate tool refuses individual
   contacts when the repo itself already ships a CoC file. Only when no such
   CoC exists, supply two named individuals with an email or handle each —
   never a mailing list.
3. **Source-code license** for sample/reference code (e.g. `Apache-2.0`, `MIT`).
4. **Governance mode**: `csl` (ship the full CSL policy) or `umbrella`
   (reference existing governance, e.g. a CNCF project charter).

## Path 1 — one-command driver (recommended)

From the darnit repo root:

```bash
# 1. Baseline audit; also writes a scope template for you to fill in
uv run python scripts/csl_onboard.py --repo <owner>/<repo> --audit-only

# 2a. Project already has a Code of Conduct (org-first):
uv run python scripts/csl_onboard.py --repo <owner>/<repo> \
    --scope-file scopes/<repo>.md \
    --coc-policy org \
    --coc-reference "X is a [CNCF](https://www.cncf.io/) project and follows the [X Code of Conduct](<url>)." \
    --code-license Apache-2.0 --spec-name "<Spec Name>"

# 2b. No existing CoC anywhere — named-individuals fallback:
uv run python scripts/csl_onboard.py --repo <owner>/<repo> \
    --scope-file scopes/<repo>.md \
    --contacts "Name One <a@x.org>, Name Two <b@y.org>" \
    --code-license Apache-2.0 --spec-name "<Spec Name>"
```

The driver clones, branches, audits, remediates from your scope file, scans
every generated file for placeholder text, re-audits, and prints the fork/PR
commands. Nothing is written without `--scope-file`.

## Path 2 — agentic, via MCP (`darnit serve`)

Register the server with your MCP client (Claude Code, etc.):

```json
{ "mcpServers": { "darnit-csl": {
    "command": "uv",
    "args": ["run", "darnit", "serve", "--framework", "community-spec"] } } }
```

The client gets three tools: `audit_community_spec`,
`list_community_spec_controls`, and `remediate_community_spec`. The intended
loop: audit → the agent drafts the Scope **from the repository's own
specification documents** and **checks for an existing Code of Conduct**
(repo file, org community/.github repo, foundation CoC) → you review → the
agent calls `remediate_community_spec(local_path, scope=..., coc_policy=...,
coc_reference=... / coc_contacts=...)` → inline re-audit. The tool enforces
org-first itself: if the repo carries its own CoC file, individual contacts
are rejected with a pointer to org mode. Under `serve`, content-quality
checks run through the LLM first; under plain `darnit audit` they fall back
to deterministic checks.

`remediate_community_spec` parameters (`scope`, `code_license`,
`governance_mode`, `coc_policy`, and the rest) are the person's decisions
and have no defaults. An omitted one is taken from context the person
confirmed (the server also exposes `confirm_project_data` for the `csl_*`
keys); otherwise the tool writes nothing and reports `confirmation
required: <key>`.

## Path 3 — local checkout, minimal

`scripts/csl_manual_remediate.py` runs remediation + re-audit against a repo
you have already cloned: edit its `ANSWERS` dict (scope, contacts or
`csl_coc_policy='org'` + `csl_coc_reference`, licenses, mode — this edit
stays local, don't commit it), then:

```bash
uv run python scripts/csl_manual_remediate.py <path-to-repo>
```

## Reviewing and opening the PR

- `git status` in the target repo must show **only** `governance/*` changes
  (plus README links on first run). Never commit `.project/` — that is
  darnit's per-repo state.
- Read `02-scope.md` and `03-notices.md` yourself; the audit checks form,
  humans check meaning.
- Commit, push to your fork, open a **draft** PR, and note in the description
  that the spec is CSL-licensed and code is under the chosen license.

## Re-running after review

`02-scope.md` and `03-notices.md` are regenerated on every run
(`overwrite = true`). Verbatim legal files (`00`, `01`, `04`, `05`) are
protected (`overwrite = false`): to regenerate one — e.g. after a template
fix — delete the file first, then re-run.

## Known upstream quirk

The upstream CSL repo renamed its files to the `NN-name.md` convention but
never updated its own CLA boilerplate, which still cites old `N._Name.md`
names. The `csl_cla` template links to the files that actually exist; if a
reviewer flags "broken filenames," point them upstream.

## Real examples of the org-first rule

- **in-toto** (CNCF): points at the [in-toto Community Code of Conduct](https://github.com/in-toto/community/blob/main/CODE-OF-CONDUCT.md), which abides by the CNCF CoC.
- **TUF** (CNCF): points at the [TUF Community Code of Conduct](https://github.com/theupdateframework/community/blob/main/CODE-OF-CONDUCT.md).
- **Uptane** (LF/JDF): points at the [JDF Code of Conduct](https://jointdevelopment.org/policies/code-of-conduct/).
- **DSSE** (no org-level CoC): named individuals — the fallback case.
