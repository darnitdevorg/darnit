// Multi-family cobra fixture exercising US2 reviewer-refinable output.
//
// See README.md for the expected discovery shape.
package main

import (
	"os"

	"github.com/spf13/cobra"

	"example.com/cobra_subcommand/cmd/cache"
	"example.com/cobra_subcommand/cmd/sign"
	"example.com/cobra_subcommand/cmd/verify"
)

func main() {
	root := &cobra.Command{
		Use:   "demo",
		Short: "Demo CLI with cache, sign, verify families",
	}
	root.AddCommand(cache.New(), sign.New(), verify.New())
	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
}
