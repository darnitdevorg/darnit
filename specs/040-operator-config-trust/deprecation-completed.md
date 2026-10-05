# Addendum: .baseline.toml deprecation completed

**Date**: 2026-10-04
**Completes**: FR-023 (research R8; plan "Before switching `BASELINE_TOML_DEPRECATION_ACTIVE` off")
**Spec**: `docs/architecture/framework-design.md` 14.4 and Appendix C

## What changed

darnit no longer reads a repository's `.baseline.toml` for anything. The
deprecation release read its per-control `status`/`reason` as claims and its
`extends` by registered name; both stop. No key in the file affects an audit,
even for a repository the operator trusts.

Removed with it:

- The `BASELINE_TOML_DEPRECATION_ACTIVE` switch and the per-setting
  deprecation warnings.
- `load_user_config` (with its `trusted` path) and
  `load_user_config_with_report`, the untrusted-file restriction,
  `validate_user_config`, and `deep_merge`.
- `.baseline.toml` claims in `darnit.trust.assertions`.
- `darnit.config.user_schema` (`UserConfig`, `UserSettings`,
  `ControlOverride`, `ControlGroup`, `CustomControl`, `ControlStatus`,
  `create_user_config*`). Operator configuration and `config migrate` used
  none of it.
- The user-configuration side of the merge: `merge_configs` and
  `merge_control` take no user configuration; `EffectiveControl` loses
  `status`, `status_reason`, `from_user`, and `is_applicable()`;
  `EffectiveConfig` loses the `.baseline.toml` settings and
  `get_excluded_controls()`; `load_effective_config*` and the control loaders
  take no repository path.
- `darnit.tools.audit` `load_effective_audit_config`,
  `get_excluded_control_ids`, and `get_adapter_for_control`, which read the
  repository's file. `run_checks`/`run_sieve_audit` `apply_user_config` is
  renamed `evaluate_claims`; it still gates `.project/` claim evaluation.

## The notice

When the file is present, every audit records one notice, logged at WARNING
and listed in the report's `warnings`: the file is ignored, and
`darnit config migrate` moves its claims to `.project/darnit.yaml` and
prints an operator configuration fragment for its tool settings. The file's
keys are no longer listed in `ignored_repository_settings`.

## Unchanged

- `darnit config migrate [REPO] [--force]` reads the file itself and does
  what it did: claims to `.project/darnit.yaml`, a printed (never written)
  operator configuration fragment, and the file left in place.
- Claims from `.project/darnit.yaml` and from `.project/` context values
  follow FR-013a to FR-020 as before.
- The framework comes from `--framework` or a tool's framework argument,
  else the default. `darnit run` gains `--framework` (#507), the remaining
  prerequisite in plan.md.

## Rationale

The audited repository is untrusted input. One release of warnings gave
existing users the migration path (FR-021, SC-005); keeping a reader for the
file afterwards only kept a second, weaker claims path and a way for
repository content to select the framework.

## Not done here

The parity corpus still marks its fixture directories with a
`.baseline.toml` (now only a marker, which the audit ignores). Switching
discovery to `parity.toml` needs a parity-only change, because the parity
guard (`tests/darnit/parity/tier1/test_no_product_changes.py`) forbids
mixing parity-harness and product changes in one pull request.
