# go_no_cobra — FR-009 regression fixture

Used by the cobra extractor's false-positive regression test (feature
[`014-cobra-threat-model`](../../../../../specs/014-cobra-threat-model/)).
This Go program intentionally contains a struct named `Command` with
fields `Use` and `RunE` — structurally similar to `cobra.Command{...}`
— but **does not import `github.com/spf13/cobra`**.

The cobra extractor MUST treat the absence of the cobra import as a hard
gate (per `is_cobra_file()` / FR-009) and emit zero `CLI_COMMAND` entry
points for this fixture. Look-alike struct literals in unrelated packages
are not findings.
