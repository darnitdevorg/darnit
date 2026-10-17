# syntax=docker/dockerfile:1.7
#
# darnit container image, built from the checkout (the tagged commit for a
# release, main for :edge) with the versions uv.lock pins. Nothing about darnit
# comes from PyPI. Contract:
# specs/012-packaging-distribution/contracts/container-image-contract.md
#
#   docker build -f packaging/container/Dockerfile .
#
# Build arg IMAGE_VERSION only sets the org.opencontainers.image.version label
# (the workflows pass the release version or the commit sha). The installed
# package versions come from the source.
#
# The Python base is pinned to its tag, not a digest: a digest pin churns on
# every Debian point release. Everything else is pinned by version, and each
# download by sha256 as well.

# uv 0.5.0, the version CI and the release workflow use (UV_VERSION).
FROM ghcr.io/astral-sh/uv:0.5.0@sha256:0e0fb77970aceaa106c1fee7103ec3e4885f6c4289e32a596123af06d2e9db9d AS uv

# ---- darnit: the workspace packages, installed from uv.lock -----------------
FROM python:3.12-slim-bookworm AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages

# The root package (darnit-mcp) brings darnit-core, darnit-baseline,
# darnit-gittuf and darnit-reproducibility; the second sync adds darnit-csl.
# --no-dev leaves out the dev group (darnit-hello, darnit-testchecks, pytest,
# ruff). --inexact keeps the first sync's packages.
RUN uv sync --frozen --no-dev --no-editable \
 && uv sync --frozen --no-dev --no-editable --inexact --package darnit-csl

# Fail the build if a development-only distribution reached the venv.
RUN /opt/venv/bin/python - <<'EOF'
import importlib.metadata as md
names = {d.metadata["Name"].lower() for d in md.distributions()}
required = {"darnit-mcp", "darnit-core", "darnit-baseline", "darnit-gittuf", "darnit-reproducibility", "darnit-csl"}
forbidden = {"darnit-hello", "darnit-testchecks", "pytest", "ruff"}
missing, present = required - names, forbidden & names
if missing or present:
    raise SystemExit(f"venv: missing {sorted(missing)}, unexpected {sorted(present)}")
EOF

# ---- External tools the controls run ----------------------------------------
FROM python:3.12-slim-bookworm AS tools

ARG TARGETARCH
# zizmor (OSPS-AC-04.02, OSPS-BR-01.01). Hashes: PyPI's JSON API for
# zizmor 1.31.1, the manylinux x86_64 and aarch64 wheels.
ARG ZIZMOR_VERSION=1.31.1
ARG ZIZMOR_SHA256_AMD64=58e878eb2dbd2c6183c105e1ac28c14f7dd1eca44a783f1fe2a69647d012c410
ARG ZIZMOR_SHA256_ARM64=d9b36840c560a8abe39d9ef3d077239aabf6d572c5c2b629c970592a617dbf6f
# gittuf (GT-01.02 runs `gittuf verify-ref`). Hashes: checksums.txt of the
# gittuf v0.16.0 GitHub release (its Sigstore bundle verifies against the
# gittuf/gittuf release workflow).
ARG GITTUF_VERSION=0.16.0
ARG GITTUF_SHA256_AMD64=31ca79426f8c282149df7dd39e30c215684fbd8a18e0557762f54a3ab7f71b91
ARG GITTUF_SHA256_ARM64=9daddda936a3fc86b4da8e69dd8ce17b24055d5cc443567b7d34c147be87dd45
# GitHub CLI (platform checks). Hashes: gh_2.102.0_checksums.txt of the cli/cli
# v2.102.0 GitHub release (the tarballs carry GitHub attestations from cli/cli).
ARG GH_VERSION=2.102.0
ARG GH_SHA256_AMD64=bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386
ARG GH_SHA256_ARM64=7862c86c72f43df3a2d93ddde6f473285b4e2af61b494849846827e513ef6484

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64) zizmor_sha="$ZIZMOR_SHA256_AMD64"; gittuf_sha="$GITTUF_SHA256_AMD64"; gh_sha="$GH_SHA256_AMD64" ;; \
      arm64) zizmor_sha="$ZIZMOR_SHA256_ARM64"; gittuf_sha="$GITTUF_SHA256_ARM64"; gh_sha="$GH_SHA256_ARM64" ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    mkdir -p /out; \
    echo "zizmor==${ZIZMOR_VERSION} --hash=sha256:${zizmor_sha}" > /tmp/zizmor.txt; \
    pip install --no-cache-dir --disable-pip-version-check --require-hashes --no-deps \
        --only-binary=:all: --target /tmp/zizmor -r /tmp/zizmor.txt; \
    install -m 0755 /tmp/zizmor/bin/zizmor /out/zizmor; \
    curl -fsSLo /tmp/gittuf \
        "https://github.com/gittuf/gittuf/releases/download/v${GITTUF_VERSION}/gittuf_${GITTUF_VERSION}_linux_${arch}"; \
    echo "${gittuf_sha}  /tmp/gittuf" | sha256sum -c -; \
    install -m 0755 /tmp/gittuf /out/gittuf; \
    curl -fsSLo /tmp/gh.tar.gz \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz"; \
    echo "${gh_sha}  /tmp/gh.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/gh.tar.gz -C /tmp; \
    install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${arch}/bin/gh" /out/gh

# ---- Runtime ----------------------------------------------------------------
FROM python:3.12-slim-bookworm

ARG IMAGE_VERSION=dev
# Debian bookworm packages, pinned. A pin that leaves the archive fails the
# build; bump it to the current bookworm version.
ARG GIT_DEB_VERSION=1:2.39.5-0+deb12u3
ARG GNUPG_DEB_VERSION=2.2.40-1.1+deb12u2
ARG OPENSSH_DEB_VERSION=1:9.2p1-2+deb12u10

LABEL org.opencontainers.image.title="darnit" \
      org.opencontainers.image.description="AI-powered compliance auditing framework" \
      org.opencontainers.image.source="https://github.com/darnitdevorg/darnit" \
      org.opencontainers.image.url="https://github.com/darnitdevorg/darnit" \
      org.opencontainers.image.documentation="https://github.com/darnitdevorg/darnit/blob/main/docs/install/container.md" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${IMAGE_VERSION}"

# git for repository inspection, gnupg and openssh-client for signature checks
# (GT-02.01 reads `git log %G?`).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        "git=${GIT_DEB_VERSION}" \
        "gnupg=${GNUPG_DEB_VERSION}" \
        "openssh-client=${OPENSSH_DEB_VERSION}" \
    ; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/* /root/.cache

# The mounted repository belongs to the host user, not uid 10001, and git
# refuses it ("dubious ownership"), which loses the repository identity (#586).
# A planted .git/config is no more dangerous here than in a native run (#617).
RUN git config --system --add safe.directory /repo

COPY --from=tools /out/ /usr/local/bin/
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system --gid 10001 darnit \
    && useradd --system --uid 10001 --gid darnit --home /home/darnit --create-home darnit

COPY packaging/container/entrypoint.sh /usr/local/bin/darnit-entrypoint
RUN chmod 0755 /usr/local/bin/darnit-entrypoint

USER darnit
WORKDIR /repo

ENTRYPOINT ["/usr/local/bin/darnit-entrypoint"]
CMD ["audit", "--help"]
