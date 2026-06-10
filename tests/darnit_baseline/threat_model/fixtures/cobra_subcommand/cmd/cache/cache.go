// Parent command for the cache family.
package cache

import (
	"github.com/spf13/cobra"
)

// New returns the parent cobra.Command for the cache family.
func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "cache",
		Short: "Manage the local cache",
		Long:  "Commands for inspecting, initialising, and clearing the local cache directory.",
	}
	return cmd
}
