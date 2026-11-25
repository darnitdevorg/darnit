# End-to-end verification

Unit tests show the code does what its author meant. They do not show that darnit still
audits, asks, and remediates correctly on a real repository. A PR that changes what darnit
does is not merged until it has been run end to end on real repositories, and the run is
recorded in the PR.

## Which run a PR needs

| Change | Required |
|---|---|
| Docs, CI, packaging only | None |
| Refactor or removal that claims no behavior change | Compare, phases 1-2 |
| Change to checks, results, context, or remediation | Replay (runs in CI) and Compare, phases 1, 2 and 4 |
| Change to a skill or to tool descriptions an agent reads | Compare, phases 2 and 4 |
| Change to anything that calls the platform API (platform settings, branch protection, rulesets, PR tools, `gh_api` reads of settings) | The runs above, plus a run on a platform copy (proposed, see Fresh copies) |
| Release candidate | All of the above, plus the interactive checklist |

## Shared setup

Every run follows the same rules.

- **Build darnit at a ref.** Base is `upstream/main`. Head is the PR merged into base,
  which is what would land, not the PR branch alone. Each ref gets its own worktree and
  venv. Never test from the checkout you develop in.
- **Isolate state.** Each darnit process gets its own `HOME`, so no operator
  configuration, confirmation, audit cache, or run manifest leaks between runs or into
  yours. Setting the `XDG_*` variables is not enough: on macOS darnit keeps data and cache
  under `~/Library` and ignores them.
- **Reference repositories at pinned commits**, listed in `scripts/comply_replay.toml`
  with the answers a person gave for each. Today: wtf-frontend at 939e838, a commit from
  before its compliance work.
- **A fresh copy for every phase and every side.** Remediation writes files, and the audit
  cache and confirmations are per repository, so a phase never reuses a copy another phase
  touched. See Fresh copies below.
- **No writes to a real repository.** Local copies have no remote, and the throwaway
  operator configuration sets platform remediation to `manual`. The replay also names a
  repository that does not exist and passes no token; the compare script gives darnit no
  token except for the phase 1 reads. File changes stay in the copy. A test that has to
  change platform state does it only on a platform copy.
- **No guessed confirmations.** Only the recorded answers are confirmed.
  `confirm_pass_candidate` is never called: the model never confirms its own PASS.

## Fresh copies

Some darnit commands only read and write files; others call the platform API (reading
settings, changing branch protection or rulesets, opening a PR). Files can be tested on a
local copy. Platform changes need a repository of their own, because a test must never
change a repository someone uses.

### Local copy (file changes only)

This is what `comply_replay.py` and `e2e_compare.py` do for every phase. By hand, for
wtf-frontend at 939e838:

```
RUN=~/.local/share/darnit-e2e-runs/manual-$(date +%Y%m%dT%H%M%S)
CACHE=~/.local/share/darnit-e2e-runs/cache/whiskeytastingfoundation__wtf-frontend
[ -d "$CACHE" ] || git clone -q https://github.com/whiskeytastingfoundation/wtf-frontend.git "$CACHE"
git clone -q "$CACHE" "$RUN/repo"
git -C "$RUN/repo" checkout -q -b e2e 939e838
git -C "$RUN/repo" remote remove origin

# A throwaway HOME for darnit: trusts the copy's identity, no platform writes.
mkdir -p "$RUN/home/.config/darnit"
printf '%s\n' 'schema_version = 1' '' '[trust]' \
  'repos = ["github.com/whiskeytastingfoundation/wtf-frontend"]' '' \
  '[remediation]' 'platform = "manual"' 'high_impact = "manual"' \
  > "$RUN/home/.config/darnit/config.toml"
env -u GH_TOKEN -u GITHUB_TOKEN HOME="$RUN/home" darnit audit "$RUN/repo" \
  -f openssf-baseline --repo github.com/whiskeytastingfoundation/wtf-frontend
```

- The clone comes from the local cache, so only the first copy reaches GitHub.
- The copy has no remote, so nothing can be pushed from it, and darnit gets the
  repository identity from `--repo` (or `owner` and `repo` in an MCP call).
- Unset the token variables; never set them to `""` (#752).
- `darnit audit` exits 1 when a control fails; add `--no-fail` to get 0.
- One copy per run, phase, and side. Delete the run directory when done; nothing outside
  it was written.

### Platform copy (proposed)

For anything that reads or changes platform state, the test gets its own GitHub repository,
created from the reference for one run and deleted afterwards:
`<test-org>/wtf-frontend-<run id>`, for example `darnit-e2e/wtf-frontend-20261117t0912-a3f9`.

- **Where.** A dedicated test organization, never darnitdevorg and never the reference's
  real owner. The token (a fine-grained token or a GitHub App installation) has rights on
  that organization only, so a mistake cannot reach any other repository.
- **Name.** The reference name plus a run id (UTC time and a short random suffix). A name
  is never reused, so two runs never share platform state, and a repository a failed run
  left behind does not affect the next one.
- **Create.**
  1. `gh repo create <test-org>/wtf-frontend-<run id> --public` (branch protection and
     rulesets on a private repository need a paid plan), with the topic `darnit-e2e`.
  2. Turn GitHub Actions off before pushing, so the reference's workflows do not run:
     `gh api -X PUT repos/<test-org>/wtf-frontend-<run id>/actions/permissions -F enabled=false`.
  3. Push the pinned commit as the default branch from a local copy:
     `git -C "$RUN/repo" push -q https://github.com/<test-org>/wtf-frontend-<run id>.git e2e:main`.
  4. Set the starting platform state the test needs (a new repository has no branch
     protection or rulesets).
  5. Add the new repository as the copy's `origin`, so darnit's identity is the platform
     copy, and trust that identity in the throwaway operator configuration.
- **Run.** darnit gets the test-org token only. Before the first write, the run checks that
  the identity's owner is the test organization and stops otherwise. Platform changes are
  approved by digest as usual (`[remediation] platform = "prompt"`).
- **Check.** Read the result back with `gh api`, not through darnit: darnit does not grade
  its own platform changes.
- **Delete.** `gh repo delete <test-org>/wtf-frontend-<run id> --yes` when the run ends,
  also when it fails (a shell `trap`). A sweeper deletes any repository with the
  `darnit-e2e` topic older than a few hours.

## Replay with no model (CI, every PR)

`scripts/comply_replay.py` clones each reference at its pinned commit, audits, confirms the
recorded answers, plans and applies remediation, audits again, and compares the result with
`scripts/comply_replay_expected.json`. Any difference fails, a better result as much as a
worse one; an intended difference is recorded with `--record` and committed with the change,
so it shows in the diff. No model runs and no platform token is passed.

```
uv run python scripts/comply_replay.py
```

## Compare base and head (locally, before merge)

`scripts/e2e_compare.py` builds base and head, runs each phase on a fresh copy of a
reference for each side, and writes `compare.md` for the PR's Testing section. Exit 0 means
no differences, 1 differences, 2 a step failed.

```
uv run python scripts/e2e_compare.py compare BASE HEAD [--phases 1,2,4]
uv run python scripts/e2e_compare.py compare upstream/main pr/NUMBER --phases 1,2
```

1. **Deterministic audit.** Level, status and `concluded_by` for every control. Platform
   reads use `GH_TOKEN` or `gh auth token`, for reads only, unless `--no-platform`.
2. **MCP tool surface.** The tools of every framework registered on either side: names,
   descriptions and input schemas. A change here is one an agent sees.
4. **Comply in one step.** Headless `claude -p "/darnit:darnit-comply ..."` through the
   local Claude Code login, with only the darnit MCP server from the build and its skills.
   The agent gets the reference's recorded answers, approves every file change and no
   platform change, and cannot call `confirm_pass_candidate`, `create_remediation_pr`,
   `enable_branch_protection` or `create_test_repository`. The darnit server gets its own
   `HOME` and no token. Compares the final audit, remediation outcomes and files written;
   lists tool errors and permission denials. Costs model usage for two runs.

Not built yet:

3. **Harness.** `darnit harness <copy> --framework openssf-baseline --format json` (needs
   `ANTHROPIC_API_KEY`). Compare the per-control results and the exit code.
5. **Audit, then data, then comply.** `/darnit:darnit-audit`, then `/darnit:darnit-data`,
   then `/darnit:darnit-comply` in one session.

What counts as a regression:

- Phases 1 and 3: any change in a control's status that the PR does not explain.
- Phase 2: any tool, parameter or description change the PR does not list.
- Phases 4 and 5: a tool error, a permission denial, a step the skill says to take but the
  agent could not, or a deterministic result that changed. A model judgment that differs
  between runs is listed, not treated as a regression; the model's verdicts vary.

## Interactive checklist (before a release)

Run by a person, on a fresh copy of each reference repository, with the release candidate
installed as a user would install it.

1. `darnit harness <copy> --framework openssf-baseline`. Note the exit code and the
   summary.
2. In `claude` in a fresh copy: `/darnit-comply openssf-baseline`. Answer every question
   yourself. Check that every question names the repository, that nothing is applied
   without your approval, and that the final audit matches what was fixed.
3. In `claude` in another fresh copy: `/darnit-audit openssf-baseline`, then `/darnit-data`,
   then `/darnit-comply`. Check that the answers from `/darnit-data` are used by
   `/darnit-comply` and not asked again.

Record the PASS counts before and after, and anything that surprised you.

## Recording a run in the PR

In the PR's Testing section:

- base and head SHAs, and the reference repositories with their commits;
- which phases ran, and for each: same, or the differences with the PR's explanation;
- anything that was not run, and why.

## Open questions

- Phases 3 and 5.
- Platform copies: the test organization, its token, a script that creates, checks and
  deletes them, and the sweeper.
- More references: pre-compliance commits and answers for darnit and cosign-installer.
- Fixture repositories with acceptance criteria per module (starting states and practices
  the references do not cover, and platform state in a dedicated test organization) are a
  feature of their own, to specify with Spec Kit before building.
