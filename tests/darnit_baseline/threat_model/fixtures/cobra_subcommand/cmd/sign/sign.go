// sign family — uses crypto primitives so the STRIDE heuristic emits Repudiation.
package sign

import (
	"crypto/ed25519"

	"github.com/spf13/cobra"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "sign",
		Short: "Sign an artefact with an ed25519 key",
		RunE: func(cmd *cobra.Command, args []string) error {
			_, _, _ = ed25519.GenerateKey(nil)
			return nil
		},
	}
	return cmd
}
