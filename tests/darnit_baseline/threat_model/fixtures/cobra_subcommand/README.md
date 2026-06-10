# cobra_subcommand — US2 reviewer-refinable fixture

Multi-family cobra program. Models gittuf's pattern:

```
main.go                              — root command + AddCommand(cache, sign, verify)
cmd/cache/cache.go                   — Use: "cache" (parent)
cmd/cache/init/init.go               — Use: "init", imports os.WriteFile  → Tampering
cmd/cache/delete/delete.go           — Use: "delete", imports os.RemoveAll → Tampering
cmd/sign/sign.go                     — Use: "sign", imports crypto/ed25519 → Repudiation
cmd/verify/verify.go                 — Use: "verify", imports crypto/sha256 → Repudiation
```

Expected discovery (feature [`014-cobra-threat-model`](../../../../../specs/014-cobra-threat-model/)):

- **`command_root`** resolves to `cmd/` (≥3 cobra-bearing immediate children).
- **3 families**:
  - `cache` (3 members: cache + init + delete)
  - `sign` (1 member)
  - `verify` (1 member)
- **Display names** taken from each family's parent literal `Use:` text where present (cache from `cache.go`); for sign/verify the parent literal IS the only member so its `Use:` is used directly.
- **STRIDE categories**:
  - cache: `Tampering` (os.WriteFile / os.RemoveAll)
  - sign / verify: `Repudiation` (crypto/*)
- **Notes column** populated from each command's `Short:` text where available.

The root command in `main.go` is also a cobra literal — its family will land in
a degenerate family (file at the inferred command_root level, not under a family
subdirectory). That's expected behaviour for "root-level" commands.
