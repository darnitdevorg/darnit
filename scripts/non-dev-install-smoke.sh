#!/usr/bin/env bash
#
# non-dev-install-smoke.sh - Install built wheels the way a user does, then run one audit
#
# Usage: scripts/non-dev-install-smoke.sh [dist-dir [package ...]]
#
# Installs the darnit wheels from dist-dir (default: dist) into a new virtual
# environment with pip: a fresh dependency resolve, no lockfile, no development
# dependencies. Then audits a throwaway repository and fails if the audit
# crashes, if any control failed to evaluate (a missing dependency shows up
# as error class "evaluation"), or if the expression-based control
# OSPS-QA-05.01 does not pass.
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
  packages=(darnit-mcp darnit-core darnit-baseline darnit-gittuf darnit-amber)
fi

fail() { echo "FAIL: $*" >&2; exit 1; }

wheels=()
for name in "${packages[@]}"; do
  matches=("$dist"/"${name//-/_}"-*.whl)
  if [ ! -e "${matches[0]}" ]; then
    fail "no $name wheel in $dist"
  fi
  if [ "${#matches[@]}" -ne 1 ]; then
    fail "more than one $name wheel in $dist (a stale build?): ${matches[*]}"
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

out="$work/audit.json"
log="$work/audit.log"
status=0
"$work/venv/bin/darnit" -q audit --no-fail --output json --framework openssf-baseline --tags level=1 "$work/repo" >"$out" 2>"$log" || status=$?
cat "$log"

if [ "$status" -ne 0 ]; then
  fail "darnit audit exited with status $status"
fi
if grep -q Traceback "$log"; then
  fail "the audit crashed"
fi

# Read the results instead of the text report, so a reworded message cannot
# make the check pass. A dependency that is installed but cannot be imported
# shows up as error class "evaluation" on every control that needs it.
"$work/venv/bin/python" - "$out" <<'PY'
import json
import sys

results = json.load(open(sys.argv[1]))["results"]
by_id = {r["id"]: r for r in results}
broken = sorted(r["id"] for r in results if r.get("error_class") == "evaluation")
if broken:
    sys.exit(f"FAIL: controls that could not be evaluated: {', '.join(broken)}")
qa = by_id.get("OSPS-QA-05.01")
if qa is None or qa["status"] != "PASS":
    sys.exit(f"FAIL: OSPS-QA-05.01 should pass on a near-empty repository, got {qa and qa['status']}")
print(f"{len(results)} controls ran, none failed to evaluate, OSPS-QA-05.01 passed")
PY

echo "OK: the wheels install without dev dependencies and the audit runs"
