#!/usr/bin/env bash
#
# setup_dev_projects.sh - Create reproducible local test repositories for Darnit
#
# Usage: ./scripts/setup_dev_projects.sh [--dest PATH] [--clean] [--projects all|failing|partial|passing]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

exec uv run --directory "$REPO_ROOT" python "$SCRIPT_DIR/setup_dev_projects.py" "$@"
