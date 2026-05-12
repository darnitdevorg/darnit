#!/usr/bin/env bash
#
# packaging/binary/build-binary.sh
#
# Build a single platform's darnit standalone binary using shiv.
#
# Inputs (env vars):
#   VERSION  — darnit-mcp version to bundle (required; from --build-arg/tag)
#   OS       — macos | linux
#   ARCH     — arm64 | amd64
#   OUT_DIR  — directory to write the binary into (default: dist/binary)
#   INDEX    — PyPI index to install from (default: PyPI; set to TestPyPI for rc tags)
#   EXTRA_INDEX — fallback index for transitive deps (default: PyPI)
#
# Output:
#   $OUT_DIR/darnit-$VERSION-$OS-$ARCH  (an executable shiv zipapp)
#
# Implementation note: shiv has no native config-file format — its config is
# CLI args. We could not deliver a real `shiv.toml`; this script captures the
# canonical invocation instead.
#
# The zipapp is platform-specific because darnit-baseline pulls in tree-sitter,
# which has C extensions and ships per-platform wheels. shiv must therefore
# run on (or be cross-targeted at) the matching platform — the release
# workflow invokes this script from a native runner per matrix entry.

set -euo pipefail

: "${VERSION:?VERSION env var is required}"
: "${OS:?OS env var is required (macos|linux)}"
: "${ARCH:?ARCH env var is required (arm64|amd64)}"

OUT_DIR="${OUT_DIR:-dist/binary}"
INDEX="${INDEX:-https://pypi.org/simple/}"
EXTRA_INDEX="${EXTRA_INDEX:-https://pypi.org/simple/}"

case "$OS" in
    macos|linux) ;;
    *) echo "::error::OS must be macos or linux, got: $OS" >&2; exit 1 ;;
esac
case "$ARCH" in
    arm64|amd64) ;;
    *) echo "::error::ARCH must be arm64 or amd64, got: $ARCH" >&2; exit 1 ;;
esac

mkdir -p "$OUT_DIR"
OUT_FILE="$OUT_DIR/darnit-${VERSION}-${OS}-${ARCH}"

echo "Building $OUT_FILE"
echo "  VERSION=$VERSION"
echo "  Index=$INDEX (fallback: $EXTRA_INDEX)"
echo "  Host Python: $(python3 --version 2>&1)"

# shiv args:
#   --console-script darnit
#       The zipapp will execute the `darnit` console script (from the
#       darnit package). This is what makes `./darnit-<...>` work directly
#       instead of needing `python <...>`.
#   --python "/usr/bin/env python3.11"
#       Shebang line in the produced zipapp. We require Python 3.11+
#       at the user's host at first run.
#   --compressed
#       Compress the bundled site-packages. Smaller distributable.
#   --output-file
#       The produced file path.
#   darnit-mcp==<version>
#       The package to bundle. shiv resolves it (and all transitive deps)
#       from the configured indexes and embeds the wheels into the zipapp.
shiv \
    --console-script darnit \
    --python "/usr/bin/env python3.11" \
    --compressed \
    --output-file "$OUT_FILE" \
    --extra-pip-args "--index-url $INDEX --extra-index-url $EXTRA_INDEX --pre" \
    "darnit-mcp==${VERSION}"

chmod +x "$OUT_FILE"
ls -la "$OUT_FILE"

echo "✓ Built $OUT_FILE"
