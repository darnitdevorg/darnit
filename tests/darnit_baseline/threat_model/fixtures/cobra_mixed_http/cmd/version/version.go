// Subcommand: version — prints a static version string. Pure cobra command,
// no HTTP / crypto / syscalls — STRIDE falls back to Tampering.
//
// Exists so that cmd/ has ≥3 cobra-bearing immediate children, which lets
// infer_command_root() recognise cmd/ as the organising directory and
// partition `serve`, `status`, and `version` into separate families instead
// of collapsing them into a single degenerate `cmd` family.
package version

import (
	"fmt"

	"github.com/spf13/cobra"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "version",
		Short: "Print the build version",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Println("dev")
			return nil
		},
	}
	return cmd
}
