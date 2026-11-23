# darnit-csl

Community Specification License (CSL 1.0) compliance for
[darnit](https://github.com/kusari-oss/darnit).

It audits — and remediates — the file set the Linux Foundation / Joint
Development Foundation asks for in a repository that develops a specification
under the **Community Specification License 1.0**:

| File (in `governance/`, `license/`, or repo root) | Control | What it is |
|---|---|---|
| `00-contributor-license-agreement.md` | `CSL-01.01` | Contributor License Agreement (static) |
| `01-community-specification-license-v1.md` | `CSL-01.02` | CSL 1.0 license text (static) |
| `02-scope.md` | `CSL-02.01` | Working Group **Scope** — per-project; can be LLM-drafted |
| `03-notices.md` | `CSL-03.01` | **Notices** + Code of Conduct contact(s) |
| `04-license.md` | `CSL-04.01` | Dual license: CSL for the spec, MIT/Apache for code |
| `05-governance.md` | `CSL-05.01` | Governance — full CSL policy **or** a reference to an umbrella project's governance |
| README links | `CSL-06.01` | Scope and Notices are discoverable from the README |

## How each control works (the 7-step pattern)

1. Look in `.project/` for confirmed context.
2. Does the file exist (`governance/`, `license/`, or repo root)?
3. Is the content valid — i.e. no leftover template placeholder? If yes, **PASS**, done.
4. If not, collect data and ask the user (`requires_context` prompts).
5. Persist the answers to `.project/`.
6. Generate the file from a template (`file_create`).
7. Refine the generated file from project context via the LLM (`llm_enhance`).

The two content-validated files (`02-scope.md`, `03-notices.md`) only pass when
the template placeholder is gone — a deterministic check that runs in
`darnit audit` without an LLM, with an `llm_eval` nuance pass for the MCP server.

## Governance & Code of Conduct: reference vs. subsume

Projects that already follow an umbrella governance / CoC (e.g. CNCF) do **not**
need to adopt the CSL versions wholesale:

- `csl_governance_mode = "umbrella"` generates a short `05-governance.md` that
  **references** the existing governance (it is not superseded) and documents the
  Community Specification roles and decision-making on top of it.
- `csl_coc_policy = "umbrella"` makes `03-notices.md` cite an existing Code of
  Conduct (e.g. the CNCF CoC) instead of shipping the CSL one, and still list
  named contacts.
- `csl_coc_policy = "org"`, for a project that already has its own Code of
  Conduct, makes `03-notices.md` link it (`csl_coc_reference`, one markdown
  sentence) and name no individuals; the linked CoC defines the reporting
  procedure.

The defaults adopt the full CSL governance and ship CSL contacts; the umbrella
modes are opt-in.

## Try it

```bash
# Audit a spec repo against CSL 1.0
uv run darnit audit --framework packages/darnit-csl/src/darnit_csl/community-spec.toml /path/to/spec-repo

# Audit just the required-files profile
uv run darnit audit --framework packages/darnit-csl/src/darnit_csl/community-spec.toml --profile required_files /path/to/spec-repo

# Show the execution plan
uv run darnit plan --framework packages/darnit-csl/src/darnit_csl/community-spec.toml /path/to/spec-repo
```

Once installed (`pip install darnit-csl`), it is discovered by name:
`darnit audit --framework community-spec /path/to/spec-repo`.

## License

Apache-2.0. The bundled CSL templates are reproduced from the
[Community Specification 1.0](https://github.com/CommunitySpecification/1.0)
repository.
