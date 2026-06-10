// Subcommand: cache delete — removes the cache directory contents.
package delete

import (
	"os"

	"github.com/spf13/cobra"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "delete",
		Short: "Delete the cache directory and its contents",
		RunE: func(cmd *cobra.Command, args []string) error {
			return os.RemoveAll(".cache")
		},
	}
	return cmd
}
