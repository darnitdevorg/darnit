// Plain Go program with NO cobra import.
//
// Expected discovery (feature 014-cobra-threat-model):
// - Zero CLI_COMMAND entry points (FR-009: no false positives on non-cobra Go projects).
// - Anything that looks structurally similar to a cobra command but isn't
//   in a cobra-importing file MUST NOT be emitted as a cobra finding.
package main

import (
	"fmt"
)

// Intentional decoy: a struct that LOOKS like cobra.Command but isn't.
// Has a Use field, has a RunE-like field name. The file does not import
// github.com/spf13/cobra, so is_cobra_file() returns False and the cobra
// extractor must skip this file entirely.
type Command struct {
	Use  string
	RunE func() error
}

func main() {
	cmd := &Command{
		Use: "decoy",
		RunE: func() error {
			fmt.Println("not a cobra command")
			return nil
		},
	}
	_ = cmd.RunE()
}
