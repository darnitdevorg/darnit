# darnit-reproducibility

Scientific reproducibility checks plugin for darnit.

Provides five controls across three maturity levels:
- RE-01.01 (L1) DependenciesPinned — checks for lock files
- RE-01.02 (L1) BuildEnvDeclared — checks for Dockerfile, Nix flake, etc.
- RE-02.01 (L2) HermeticBuild — scans CI workflows for live network fetches
- RE-02.02 (L2) ProvenanceExists — checks for sigstore/cosign or SLSA provenance
- RE-03.01 (L3) BitForBitReproducible — checks for SOURCE_DATE_EPOCH and reprotest