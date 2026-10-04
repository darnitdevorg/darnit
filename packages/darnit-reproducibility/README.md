# darnit-reproducibility

Scientific reproducibility checks plugin for darnit.

Provides five controls across three maturity levels:
- RE-01.01 (L1) DependenciesPinned — checks for lock files
- RE-01.02 (L1) BuildEnvDeclared — checks for Dockerfile, Nix flake, etc.
- RE-02.01 (L2) HermeticBuild — scans CI workflows for live network fetches
- RE-02.02 (L2) ProvenanceExists — checks for sigstore/cosign or SLSA provenance
- RE-03.01 (L3) BitForBitReproducible — checks for SOURCE_DATE_EPOCH and reprotest
## What the checks can conclude

Each check reads text and file-presence signals: lock files, environment
files, CI workflow contents. A signal can show that a requirement is unmet,
but a mention cannot show that it is met. A workflow that names
`cosign sign` in a comment produces no provenance.

So every check here registers the ceiling `{fail}` (feature 044, FR-010):

- A FAIL concludes the control, and only where the signal proves the
  requirement is unmet (for example, a dependency manifest with no lock file,
  or an unpinned requirement).
- A PASS the check reports is evidence only. The control continues to its
  later steps (model judgment, human review), which receive the signals. With
  no later step concluding, the control ends WARN: not compliant.
- A control concludes PASS automatically only when its step declares a
  `promotion` backed by a corpus measurement (framework-design 3.0.1, 5.5).
  None ships today.
