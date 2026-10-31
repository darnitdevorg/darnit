#!/usr/bin/env bash
#
# clean_and_install_dev.sh - Clean build artifacts and install development environment
#
# Usage: ./scripts/clean_and_install_dev.sh [--recreate-venv] [--skip-sync]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

exec uv run --directory "$REPO_ROOT" python "$SCRIPT_DIR/clean_and_install_dev.py" "$@"
