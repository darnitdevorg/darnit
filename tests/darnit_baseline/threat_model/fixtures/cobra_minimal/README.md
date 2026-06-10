# cobra_minimal — US1 MVP fixture

Smallest viable cobra program for feature
[`014-cobra-threat-model`](../../../../../specs/014-cobra-threat-model/).
Single file, one command literal, one `func New() *cobra.Command`
constructor.

The cobra extractor MUST detect one `CLI_COMMAND` entry point with:
- `name` = `"hello"`
- `framework` = `"cobra"`
- `language` = `"go"`
- `location` = `main.go:18` (the composite literal)
- `source_query` = `"go.entry.cobra_command_literal"`

The duplicate signal from `func New() *cobra.Command` (line 16) is
deduplicated by `(file, line)` against the literal — the literal wins
because it carries the `Use:` string.

A reviewer running the threat-model generator against this fixture
should see a non-empty `### CLI Entry Points` section with one family
finding, marked as needing reviewer attention.
