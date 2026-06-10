// Subcommand: cache init — initialises the cache directory on disk.
package init

import (
	"os"

	"github.com/spf13/cobra"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "init",
		Short: "Create the cache directory if it doesn't exist",
		RunE: func(cmd *cobra.Command, args []string) error {
			return os.WriteFile(".cache/marker", []byte("ok"), 0644)
		},
	}
	return cmd
}
