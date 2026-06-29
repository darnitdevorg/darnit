# cobra_mixed_http — US3 / FR-014 mixed-shape fixture

A Go program containing **both** a cobra command tree **and** a `net/http`
route registration. Used by T031 and downstream tests (T035–T037) to verify
that both `### HTTP Entry Points` and `### CLI Entry Points` subsections
render under one `## Entry Points` parent when both shapes are present, and
that neither subsection swallows the other's findings.

## File layout

```
main.go                       — tiny shim, no cobra literal: calls root.New().Execute()
cmd/root/root.go              — root cobra command (Use: "mixed"), AddCommand(serve, status, version)
cmd/serve/serve.go            — Use: "serve". RunE registers an HTTP route AND ListenAndServe
cmd/status/status.go          — Use: "status". Pure cobra command, no HTTP / crypto / syscalls
cmd/version/version.go        — Use: "version". Pure cobra command, no signals
```

Four siblings beneath `cmd/` is comfortably above `infer_command_root`'s
`_COMMAND_ROOT_MIN_CHILDREN = 3` threshold, so `cmd/` is recognised as the
command organiser. Putting the root command under `cmd/root/` rather than
at the repo root matches the gittuf / cosign pattern and dodges the
"root-above-command_root" edge case in `family_key_for_path`.

## Expected discovery

### CLI families (under `### CLI Entry Points`)

- `command_root` resolves to `cmd/` (4 cobra-bearing immediate children).
- 4 families, ordered by `len(members)` desc then `family_key` asc — since each
  has 1 member, the tiebreak (alphabetical family_key) dominates:
  - `root`    — 1 member, STRIDE fallback `Tampering` (the parent literal itself).
  - `serve`   — 1 member, STRIDE `Spoofing, Information Disclosure` (net/http rule).
  - `status`  — 1 member, STRIDE fallback `Tampering`.
  - `version` — 1 member, STRIDE fallback `Tampering`.

### HTTP routes (under `### HTTP Entry Points`)

- 1 HTTP_ROUTE: `/healthz` at `cmd/serve/serve.go` (registered inside the
  cobra `RunE` closure). The route registration MUST be picked up by the
  pre-existing `_extract_go_entry_points` HTTP path — additive cobra discovery
  must not regress it.

### Document structure

```
## Entry Points
### HTTP Entry Points
…1 row for /healthz…
### CLI Entry Points
#### Family: mixed   (1 member, STRIDE Tampering — root literal)
#### Family: serve   (1 member, STRIDE Spoofing/Information Disclosure)
#### Family: status  (1 member, STRIDE Tampering)
#### Family: version (1 member, STRIDE Tampering)
```

The `root` family's display_name is `"mixed"` (the parent literal's `Use:`
text from `cmd/root/root.go`), but its `family_key` is `"root"`.

The omit-empty case (T032/T036) is exercised against `cobra_minimal` (cobra
only, no HTTP) and `go_http_handler` (HTTP only, no cobra) instead — this
fixture is deliberately mixed.
