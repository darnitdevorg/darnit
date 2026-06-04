# syntax=docker/dockerfile:1.7
#
# darnit official container image.
#
# Built and signed by .github/workflows/release.yml on each release tag.
# See specs/012-packaging-distribution/contracts/container-image-contract.md
# for the full contract (tags, signing identity, SBOM attestations, size
# budget).
#
# Built as a multi-stage image so the runtime layer contains only the
# venv + the runtime CLIs darnit's controls need (git, gh) — no build
# toolchain, no apt cache, no pip cache.
#
# Build arg: VERSION — the exact darnit-mcp release version to install.
# The release workflow passes the tagged version; for local testing,
# override with --build-arg VERSION=<version>.

# Base image is pinned to the major-minor tag rather than a digest. Pinning
# to a digest is stronger but requires per-release digest churn; we accept
# the looser pin for v1 in exchange for a less churny Dockerfile, and
# revisit if vuln scanning surfaces drift.
#
# ---- Stage 1: builder ------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ARG VERSION

# Refuse to build without a pinned version. Prevents accidentally
# producing "latest" images that float across releases.
RUN test -n "$VERSION" || (echo "ERROR: --build-arg VERSION is required" >&2 && exit 1)

# Build-time deps: nothing extra — pip-installable wheels for the public
# darnit packages are pure Python or arrive with prebuilt wheels.

WORKDIR /opt

# Install darnit-mcp from PyPI at the pinned version into a venv. The
# venv gets copied wholesale into the runtime stage.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir "darnit-mcp==${VERSION}"

# ---- Stage 2: runtime ------------------------------------------------------
FROM python:3.12-slim-bookworm

ARG VERSION

LABEL org.opencontainers.image.title="darnit"
LABEL org.opencontainers.image.description="AI-powered compliance auditing framework"
LABEL org.opencontainers.image.source="https://github.com/kusari-oss/darnit"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.vendor="Kusari"
LABEL org.opencontainers.image.url="https://github.com/kusari-oss/darnit"
LABEL org.opencontainers.image.documentation="https://github.com/kusari-oss/darnit/blob/main/docs/install/container.md"

# Install runtime CLIs the audit controls invoke (git for repo inspection;
# gh for GitHub API calls). Pin to apt's stable channel; the GitHub CLI
# install path is the official one from cli.github.com.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
    ; \
    # GitHub CLI from the official repo
    mkdir -p -m 755 /etc/apt/keyrings; \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | gpg --dearmor -o /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends gh; \
    # Trim caches and unneeded build-time tooling (gnupg / curl could be
    # kept but gnupg in particular is a meaningful footprint reducer when
    # removed)
    apt-get purge -y --auto-remove gnupg; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/* /root/.cache

# Copy the prebuilt venv from the builder stage. No pip in the runtime
# image — installs from inside the running container are not supported.
COPY --from=builder /opt/venv /opt/venv

# Put the venv on PATH so `darnit` and `darnit-mcp` resolve as plain
# command names. PYTHONUNBUFFERED keeps logs flowing in stdio MCP mode.
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Non-root user. Maps to host UIDs in CI mounts cleanly.
RUN groupadd --system --gid 10001 darnit \
    && useradd --system --uid 10001 --gid darnit --home /home/darnit --create-home darnit

# Install the entrypoint (as root — needs /usr/local/bin write).
COPY packaging/container/entrypoint.sh /usr/local/bin/darnit-entrypoint
RUN chmod 0755 /usr/local/bin/darnit-entrypoint

# Record the version in an image label so cosign verify-attestations and
# users can read it without booting the container.
LABEL org.opencontainers.image.version="${VERSION}"

# Drop to the non-root user for the runtime.
USER darnit
WORKDIR /repo

ENTRYPOINT ["/usr/local/bin/darnit-entrypoint"]
CMD ["audit", "--help"]
