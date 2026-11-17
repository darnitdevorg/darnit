# Security

Report vulnerabilities through GitHub private vulnerability reporting.

## Supported versions

We support the two most recent minor releases. The support scope covers
security fixes and critical bug fixes, and the support period for each minor
release is twelve months from its release date.

When a minor release reaches end of life, it no longer receives security
updates. We announce each end-of-life date in the release notes at least three
months in advance.

## Verifying a release

Every release is signed with Sigstore by our release workflow. To verify that a
release was produced by that workflow, check the signature and signer identity:

    cosign verify-blob tinyq-1.4.0.tar.gz \
      --bundle tinyq-1.4.0.tar.gz.sigstore.json \
      --certificate-identity https://github.com/corpus/tinyq/.github/workflows/release.yml@refs/tags/v1.4.0 \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com
