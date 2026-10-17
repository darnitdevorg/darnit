# syntax=docker/dockerfile:1.7
#
# darnit container image, built from the checkout (the tagged commit for a
# release, main for :edge) with the versions uv.lock pins. Nothing about darnit
# comes from PyPI. Contract:
# specs/012-packaging-distribution/contracts/container-image-contract.md
#
#   docker build -f packaging/container/Dockerfile .
#
# The runtime is distroless (glibc, CA certificates, the nonroot user; no shell,
# no package manager). Python is uv's python-build-standalone build. git, grep,
# gpg and ssh-keygen come from Debian 12, the release distroless is built from,
# with exactly the shared libraries they load that distroless lacks.
#
# Build arg IMAGE_VERSION only sets the org.opencontainers.image.version label
# (the workflows pass the release version or the commit sha). The installed
# package versions come from the source. Base images are pinned by digest;
# downloads by version and sha256. Debian packages are not pinned to a version,
# so a rebuild picks up security updates.

# For a debugging build with a busybox shell at /busybox/sh:
#   --build-arg RUNTIME_BASE=gcr.io/distroless/cc-debian12:debug-nonroot
ARG RUNTIME_BASE=gcr.io/distroless/cc-debian12:nonroot@sha256:9dac0a79194e45a7da0158a9c6da57b217585af0786db3845d1f0ec1a0dd182f

FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv
FROM ${RUNTIME_BASE} AS distroless
FROM debian:12-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS debian

# ---- Python and darnit: the workspace packages, installed from uv.lock ------
FROM debian AS builder

COPY --from=uv /uv /usr/local/bin/uv

# uv checks the python-build-standalone download against the checksum it ships.
ARG PYTHON_VERSION=3.12.15
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON=${PYTHON_VERSION} \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1
RUN uv python install --no-bin "${PYTHON_VERSION}"

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

# Drop what darnit never loads from the interpreter install: the embedding
# library (bin/python3.12 links libpython statically), the base install's pip,
# Tcl/Tk with tkinter and IDLE, ensurepip, headers, and the deprecated crypt
# module (the one thing that needs libcrypt).
RUN set -eux; \
    cd /opt/python/cpython-*; \
    rm -rf include lib/pkgconfig lib/libpython3* lib/libtcl* lib/itcl* lib/tcl9* lib/thread* lib/tk9* \
        bin/pip* bin/idle* bin/2to3* bin/python3*-config \
        lib/python3.12/site-packages/pip lib/python3.12/site-packages/pip-*.dist-info \
        lib/python3.12/tkinter lib/python3.12/idlelib lib/python3.12/turtledemo lib/python3.12/ensurepip \
        lib/python3.12/lib-dynload/_tkinter.* lib/python3.12/lib-dynload/_crypt.*; \
    /opt/venv/bin/python -c "import darnit.cli, ssl, sqlite3, ctypes, readline, zlib, lzma, bz2"

# ---- Downloaded tools: copied in as they are ---------------------------------
# (From the builder for its uv and Python, which install the zizmor wheel.)
FROM builder AS tools

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
    apt-get install -y --no-install-recommends ca-certificates curl; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64) zizmor_sha="$ZIZMOR_SHA256_AMD64"; gittuf_sha="$GITTUF_SHA256_AMD64"; gh_sha="$GH_SHA256_AMD64" ;; \
      arm64) zizmor_sha="$ZIZMOR_SHA256_ARM64"; gittuf_sha="$GITTUF_SHA256_ARM64"; gh_sha="$GH_SHA256_ARM64" ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    mkdir -p /out; \
    echo "zizmor==${ZIZMOR_VERSION} --hash=sha256:${zizmor_sha}" > /tmp/zizmor.txt; \
    uv pip install --require-hashes --no-deps --only-binary :all: --target /tmp/zizmor -r /tmp/zizmor.txt; \
    install -m 0755 /tmp/zizmor/bin/zizmor /out/zizmor; \
    curl -fsSLo /tmp/gittuf \
        "https://github.com/gittuf/gittuf/releases/download/v${GITTUF_VERSION}/gittuf_${GITTUF_VERSION}_linux_${arch}"; \
    echo "${gittuf_sha}  /tmp/gittuf" | sha256sum -c -; \
    install -m 0755 /tmp/gittuf /out/gittuf; \
    curl -fsSLo /tmp/gh.tar.gz \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz"; \
    echo "${gh_sha}  /tmp/gh.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/gh.tar.gz -C /tmp; \
    install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${arch}/bin/gh" /out/gh; \
    install -m 0755 /usr/local/bin/uv /out/uv

# ---- Debian tools and the shared libraries distroless lacks ------------------
# git (with git-remote-http for https remotes), grep (an exec step), gpg (git
# runs it for `%G?` on OpenPGP signatures) and ssh-keygen (SSH signatures).
# Every ELF file the image will run is checked with ldd: a library distroless
# already has is used from distroless, any other is copied from this stage
# (same Debian release, so the ABI matches), and a library nothing provides
# fails the build. The dpkg status of each package a file came from is copied
# too, so image scanners still see those packages.
FROM debian AS osdeps

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends git gpg openssh-client; \
    rm -rf /var/lib/apt/lists/*

COPY --from=distroless / /distroless
COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/venv /opt/venv
COPY --from=tools /out /opt/tools

RUN <<'EOF'
set -eu
triplet="$(uname -m)-linux-gnu"
root=/rootfs
libdir="$root/usr/lib/$triplet"
mkdir -p "$libdir" "$root/var/lib/dpkg/status.d" "$root/usr/bin" "$root/usr/lib/git-core" "$root/usr/share/git-core" "$root/etc"

bins="/usr/bin/git /usr/lib/git-core/git-remote-http /usr/bin/grep /usr/bin/gpg /usr/bin/ssh-keygen"
for bin in $bins; do
  cp -a "$bin" "$root$bin"
done
ln -s git-remote-http "$root/usr/lib/git-core/git-remote-https"
cp -a /usr/share/git-core/templates "$root/usr/share/git-core/"

# The mounted repository belongs to the host user, not the container user, and
# git refuses it ("dubious ownership"), which loses the repository identity
# (#586). A planted .git/config is no more dangerous here than in a native run
# (#617).
printf '[safe]\n\tdirectory = /repo\n' > "$root/etc/gitconfig"

# owner FILE: the Debian package that installed FILE (usrmerge: try both paths).
owner() {
  real="$(readlink -f "$1")"
  for candidate in "$1" "$real" "${real#/usr}" "/usr$real"; do
    found="$(dpkg -S "$candidate" 2>/dev/null | head -n 1)" || continue
    [ -n "$found" ] && { printf '%s\n' "${found%%:*}" | cut -d, -f1; return 0; }
  done
  echo "no package owns $1" >&2
  return 1
}

packages=""
for bin in $bins; do
  packages="$packages $(owner "$bin")"
done

missing=""
for file in $bins $(find /opt -type f \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \)); do
  out="$(ldd "$file" 2>/dev/null)" || continue
  for line in $(printf '%s\n' "$out" | awk '/=> not found/ {print "MISSING:" $1; next} /=> \// {print $1 "=" $3}'); do
    case "$line" in
      MISSING:*) missing="$missing $file:${line#MISSING:}"; continue ;;
    esac
    soname="${line%%=*}"; path="${line#*=}"
    case "$path" in /opt/*) continue ;; esac
    if [ -e "/distroless/lib/$triplet/$soname" ] || [ -e "/distroless/usr/lib/$triplet/$soname" ]; then
      continue
    fi
    if [ ! -e "$libdir/$soname" ]; then
      cp -L "$path" "$libdir/$soname"
      packages="$packages $(owner "$path")"
    fi
  done
done
if [ -n "$missing" ]; then
  echo "unresolved shared libraries:$missing" >&2
  exit 1
fi

for package in $(printf '%s\n' $packages | sort -u); do
  [ -e "/distroless/var/lib/dpkg/status.d/$package" ] && continue
  dpkg-query -s "$package" > "$root/var/lib/dpkg/status.d/$package"
done

echo "copied libraries: $(ls "$libdir" | wc -l) files, $(du -sb "$libdir" | cut -f1) bytes"
ls -l "$libdir"
echo "packages: $(ls "$root/var/lib/dpkg/status.d" | tr '\n' ' ')"
EOF

# ---- Runtime ----------------------------------------------------------------
FROM distroless

ARG IMAGE_VERSION=dev

LABEL org.opencontainers.image.title="darnit" \
      org.opencontainers.image.description="AI-powered compliance auditing framework" \
      org.opencontainers.image.source="https://github.com/darnitdevorg/darnit" \
      org.opencontainers.image.url="https://github.com/darnitdevorg/darnit" \
      org.opencontainers.image.documentation="https://github.com/darnitdevorg/darnit/blob/main/docs/install/container.md" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${IMAGE_VERSION}"

COPY --from=osdeps /rootfs/ /
COPY --from=tools /out/ /usr/local/bin/
COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/venv /opt/venv

# UV_PYTHON_INSTALL_DIR lets the bundled uv (a remediation runs `uv lock`) find
# the bundled Python.
ENV PATH="/opt/venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_INSTALL_DIR=/opt/python

USER nonroot
WORKDIR /repo

ENTRYPOINT ["darnit"]
CMD ["harness", "/repo"]
