#!/usr/bin/env bash
#
# non-dev-install-smoke.sh - Install built wheels the way a user does, then run one audit
#
# Usage: scripts/non-dev-install-smoke.sh [dist-dir [package ...]]
#
# Installs the darnit wheels from dist-dir (default: dist) into a new virtual
# environment with pip: a fresh dependency resolve, no lockfile, no development
# dependencies. Then audits a throwaway repository and fails if the audit
# crashes, reports a dependency as "not installed", or passes no control.
#
# `uv sync` hides both kinds of breakage this catches: a dependency darnit
# imports without declaring it (the dev group supplies it), and a newly
# published release of a dependency that uv.lock pins away. See #573.
#
# With no package names it installs everything darnit-mcp pulls in. Pass a
# smaller set (darnit-core darnit-baseline) as well: a sibling package can
# declare a dependency that core forgot, which hides the gap in a full install.
#
# Requirements: python3 (with venv and pip), git, network access to PyPI.

set -euo pipefail

dist="${1:-dist}"
if [ $# -gt 1 ]; then
  shift
  packages=("$@")
else
  packages=(darnit-mcp darnit-core darnit-baseline darnit-gittuf darnit-reproducibility)
fi

fail() { echo "FAIL: $*" >&2; exit 1; }

wheels=()
for name in "${packages[@]}"; do
  matches=("$dist"/"${name//-/_}"-*.whl)
  if [ ! -e "${matches[0]}" ]; then
    fail "no $name wheel in $dist"
  fi
  wheels+=("${matches[0]}")
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

python3 -m venv "$work/venv"
"$work/venv/bin/pip" install --quiet --disable-pip-version-check "${wheels[@]}"

mkdir "$work/repo"
git -C "$work/repo" init -q
echo "# fixture" > "$work/repo/README.md"

out="$work/audit.txt"
status=0
"$work/venv/bin/darnit" -q audit --no-fail --framework openssf-baseline --tags level=1 "$work/repo" >"$out" 2>&1 || status=$?
cat "$out"

if [ "$status" -ne 0 ]; then
  fail "darnit audit exited with status $status"
fi
if grep -q -E 'Traceback|not installed' "$out"; then
  fail "the audit reported a crash or a dependency as not installed"
fi
if ! grep -q -E '^Total: .*\| Pass: [1-9]' "$out"; then
  fail "no control passed; the expression-based controls should pass on a near-empty repository"
fi

echo "OK: the wheels install without dev dependencies and the audit runs"
