#!/usr/bin/env bash
#
# packaging/claude-plugin/build.sh
#
# Assemble the Claude Code plugin bundle for a darnit release and zip it.
#
# Inputs (env vars):
#   VERSION   — exact darnit version this plugin targets (required;
#               written into plugin.json AND used to pin the MCP server
#               install via DARNIT_MCP_VERSION)
#   OUT_DIR   — directory to write the zip into (default: dist/claude-plugin)
#
# Output:
#   $OUT_DIR/darnit-claude-plugin-$VERSION.zip
#
# Bundle layout (see contracts/claude-plugin-contract.md):
#
#   .claude-plugin/plugin.json
#   README.md
#   bin/darnit-mcp-runner
#   skills/{audit,comply,data,remediate}/SKILL.md
#
# The repo's source skills live at packages/darnit/src/darnit/skills/
# under prefixed names (darnit-audit, darnit-comply, darnit-data,
# darnit-remediate). The bundle strips the `darnit-` prefix so the
# plugin-namespaced slash commands read as /darnit:audit, /darnit:comply,
# /darnit:data, /darnit:remediate (rather than /darnit:darnit-audit).

set -euo pipefail

: "${VERSION:?VERSION env var is required}"

OUT_DIR="${OUT_DIR:-dist/claude-plugin}"

# Resolve repo root from this script's location so the script works from
# any cwd.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

TEMPLATES_DIR="$SCRIPT_DIR/templates"
SRC_SKILLS_DIR="$REPO_ROOT/packages/darnit/src/darnit/skills"

mkdir -p "$OUT_DIR"

# Build the bundle in a scratch directory so the zip layout is exactly
# what users see — no stray host paths.
BUILD_ROOT="$(mktemp -d)"
trap 'rm -rf "$BUILD_ROOT"' EXIT
BUNDLE="$BUILD_ROOT/darnit"
mkdir -p "$BUNDLE/.claude-plugin" "$BUNDLE/bin" "$BUNDLE/skills"

# --- plugin.json (substitute __VERSION__) -----------------------------------
sed "s|__VERSION__|${VERSION}|g" \
    "$TEMPLATES_DIR/plugin.json" \
    > "$BUNDLE/.claude-plugin/plugin.json"

# Sanity check the substitution worked — no leftover sentinels.
if grep -q '__VERSION__' "$BUNDLE/.claude-plugin/plugin.json"; then
    echo "::error::plugin.json still contains __VERSION__ after substitution" >&2
    exit 1
fi

# --- bin/darnit-mcp-runner --------------------------------------------------
cp "$TEMPLATES_DIR/darnit-mcp-runner" "$BUNDLE/bin/darnit-mcp-runner"
chmod 0755 "$BUNDLE/bin/darnit-mcp-runner"

# --- skills/ (rename darnit-X → X) ------------------------------------------
# Expected source skills:
EXPECTED_SKILLS=(darnit-audit darnit-comply darnit-data darnit-remediate)

for src_name in "${EXPECTED_SKILLS[@]}"; do
    src_dir="$SRC_SKILLS_DIR/$src_name"
    if [ ! -f "$src_dir/SKILL.md" ]; then
        echo "::error::Expected skill not found: $src_dir/SKILL.md" >&2
        exit 1
    fi
    # Strip "darnit-" prefix for the bundle.
    bundle_name="${src_name#darnit-}"
    cp -R "$src_dir" "$BUNDLE/skills/$bundle_name"
done

# Sanity check the bundled skill set matches the contract exactly.
bundled_skills=$(ls "$BUNDLE/skills" | sort | tr '\n' ' ')
expected_bundled="audit comply data remediate "
if [ "$bundled_skills" != "$expected_bundled" ]; then
    echo "::error::Bundled skills mismatch contract:" >&2
    echo "  expected: $expected_bundled" >&2
    echo "  found:    $bundled_skills" >&2
    exit 1
fi

# --- README ---------------------------------------------------------------
# Render the plugin README from the static template, substituting VERSION.
sed "s|__VERSION__|${VERSION}|g" \
    "$SCRIPT_DIR/README.md" \
    > "$BUNDLE/README.md"

# --- Zip ----------------------------------------------------------------
ZIP_NAME="darnit-claude-plugin-${VERSION}.zip"
ZIP_PATH="$OUT_DIR/$ZIP_NAME"
rm -f "$ZIP_PATH"

# `cd` into the build root so the zip's top-level dir is `darnit/` rather
# than the host tempdir path.
(
    cd "$BUILD_ROOT"
    # -X strips extra file attributes for reproducibility; -y preserves
    # symlinks (none here, but defensive).
    zip -r -X -y "$ZIP_PATH" darnit/ > /dev/null
)

# Sanity check the zip is non-trivial and contains the expected entries.
zip_size=$(wc -c < "$ZIP_PATH" | tr -d ' ')
echo "Built $ZIP_PATH (${zip_size} bytes)"
echo "Contents:"
unzip -l "$ZIP_PATH"
