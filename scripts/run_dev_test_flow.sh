#!/usr/bin/env bash
#
# run_dev_test_flow.sh - Run end-to-end developer testing and regression tracking
#
# Usage: ./scripts/run_dev_test_flow.sh [--dest PATH] [--report-file PATH] [--clean] [--mode audit|harness] [--verbose]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

exec uv run --directory "$REPO_ROOT" python "$SCRIPT_DIR/run_dev_test_flow.py" "$@"

