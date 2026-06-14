// Root cobra command for the mixed cobra + net/http fixture. Lives under
// cmd/root/ rather than at the repo root so that `cmd/` is a clean command
// organiser (4 immediate children: root, serve, status, version) above the
// _COMMAND_ROOT_MIN_CHILDREN threshold, and so the root-above-command_root
// edge case in family_key_for_path does not surface.
package root

import (
	"github.com/spf13/cobra"

	"example.com/cobra_mixed_http/cmd/serve"
	"example.com/cobra_mixed_http/cmd/status"
	"example.com/cobra_mixed_http/cmd/version"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "mixed",
		Short: "Demo CLI that also runs an HTTP server",
	}
	cmd.AddCommand(serve.New(), status.New(), version.New())
	return cmd
}
