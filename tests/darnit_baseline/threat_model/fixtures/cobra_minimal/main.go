// Minimal cobra-based Go CLI fixture for feature 014-cobra-threat-model.
//
// Expected discovery:
// - One CLI_COMMAND entry point named "hello" from the composite literal.
// - One CLI_COMMAND entry point from the func New() *cobra.Command declaration
//   (deduplicated against the literal by (file, line) — the literal wins).
// - Family display name: "hello" (taken from Use:).
package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "hello",
		Short: "Print a greeting",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Println("hello, world")
			return nil
		},
	}
	return cmd
}

func main() {
	if err := New().Execute(); err != nil {
		os.Exit(1)
	}
}
