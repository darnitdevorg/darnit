# CNCF Project Metadata

darnit reads standard CNCF `.project/` fields and keeps its own data (context values, confirmation records, and not-applicable claims) in a separate extension file, so the CNCF file stays conformant to its upstream definition. The authoritative rules are in `docs/architecture/framework-design.md` section 7 (Context Detection).

## Files

### `.project/project.yaml` (CNCF format)

The project's own file. darnit reads CNCF fields from it, for example:

```yaml
security:
  contact: security@realcorp.io
```

darnit never writes a context value or a confirmation into this file. Only an applied remediation's `project_update` changes it, and then only the dotted fields that update targets, preserving comments, ordering, and fields darnit does not own. If the file is present but invalid, darnit writes nothing and reports the validation errors; it never replaces the file with a scaffold.

### `.project/darnit.yaml` (darnit extension)

darnit-only keys and confirmation records:

```yaml
context:
  security_contact: security@realcorp.io
confirmations:
  security_contact:
    value_digest: "sha256:..."
    confirmed_by: "alice"
    confirmed_at: "2026-09-29T15:00:00Z"
    last_validated: "2026-09-29T15:00:00Z"
```

`darnit.config.context_writes` is the only writer of context values and confirmation records, and it writes only this file. It preserves sections and comments it does not change, including `controls:` claims.

## Standing of a stored value

A value read from either file counts only when a confirmation record matches it (same value digest, not lapsed). A value without one, such as a value written by an earlier darnit version or edited by hand, is an unconfirmed candidate (origin `stored_unconfirmed`, with the file and field it came from) and nothing consumes it. Review such values with `confirm_project_data(confirm_stored=[...], reject_stored=[...])`; a rejected `darnit.yaml` value is deleted, and a rejected `project.yaml` value is reported with its field for the person to edit.

When the operator does not trust the repository, a confirmation is recorded in the operator-side store instead, and nothing is written into the repository.

## Supported Keys

CNCF fields mapped from `project.yaml` (read):
- `security_contact` <- `security.contact`

Other keys (for example `ci_provider`, `has_releases`, `maintainers`) live under `context:` in `darnit.yaml`. Each key has one canonical name and vocabulary; legacy spellings (for example `ci_provider: github_actions`) are read as the canonical form (`github`).
