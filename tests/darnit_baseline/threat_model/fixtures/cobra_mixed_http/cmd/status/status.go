// Subcommand: status — prints a one-line status string. No HTTP, no syscalls,
// no crypto. Exists to give the document a non-fallback companion family so the
// CLI section has two entries instead of one (otherwise the omit-empty logic
// for US3 has less surface to exercise).
package status

import (
	"fmt"

	"github.com/spf13/cobra"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Print the current status",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Println("idle")
			return nil
		},
	}
	return cmd
}
