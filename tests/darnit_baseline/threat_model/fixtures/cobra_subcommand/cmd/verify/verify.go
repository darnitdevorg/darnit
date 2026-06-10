// verify family — uses crypto primitives so the STRIDE heuristic emits Repudiation.
package verify

import (
	"crypto/sha256"

	"github.com/spf13/cobra"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "verify",
		Short: "Verify the signature on an artefact",
		RunE: func(cmd *cobra.Command, args []string) error {
			_ = sha256.Sum256([]byte("data"))
			return nil
		},
	}
	return cmd
}
