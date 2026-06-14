// Mixed cobra + net/http fixture for feature 014-cobra-threat-model (US3 / T031).
//
// Tiny entry-point shim: the root cobra command lives in cmd/root/ (matching the
// gittuf / cosign pattern), so main.go itself contains no cobra literal and
// won't be discovered. See README.md for the expected discovery shape.
package main

import (
	"os"

	"example.com/cobra_mixed_http/cmd/root"
)

func main() {
	if err := root.New().Execute(); err != nil {
		os.Exit(1)
	}
}
