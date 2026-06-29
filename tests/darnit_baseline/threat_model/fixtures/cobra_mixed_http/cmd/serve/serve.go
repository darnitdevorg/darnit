// Subcommand: serve — starts an HTTP server.
//
// Exercises the mixed-shape requirement (FR-014): this file is BOTH a cobra
// command literal and a net/http route registration site, so it must show up
// under "### CLI Entry Points" (as part of the serve family) AND under
// "### HTTP Entry Points" (as a route).
package serve

import (
	"fmt"
	"net/http"

	"github.com/spf13/cobra"
)

func New() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "serve",
		Short: "Start the HTTP server on :8080",
		RunE: func(cmd *cobra.Command, args []string) error {
			http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
				fmt.Fprintln(w, "ok")
			})
			return http.ListenAndServe(":8080", nil)
		},
	}
	return cmd
}
