// Vendored third-party cobra definition. Lives under `vendor/` which is in
// BASELINE_EXCLUDED_DIRS — discovery MUST NOT pick up this file's cobra
// literals (T038a). If discovery surfaces "vendored-fake" or "vendored-sub"
// the exclusion has regressed.
package cobrathirdparty

import (
	"github.com/spf13/cobra"
)

func VendoredRoot() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "vendored-fake",
		Short: "Should never appear in discovery output",
	}
	cmd.AddCommand(&cobra.Command{
		Use:   "vendored-sub",
		Short: "Subcommand inside vendor/ — also excluded",
	})
	return cmd
}
