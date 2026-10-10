#!/usr/bin/env bash
#
# quickstart.sh - Install darnit from source and run a first audit
#
# Usage:
#   ./scripts/quickstart.sh [options] [path/to/repo]
#
# Requirements: git, and curl or wget if uv has to be installed.
# Nothing in the audited repository is modified.

set -euo pipefail

REPO_URL="https://github.com/darnitdevorg/darnit.git"
# The uv release installed when uv is missing. The script was tested with it.
UV_VERSION="0.13.0"
UV_INSTALLER="https://astral.sh/uv/${UV_VERSION}/install.sh"
ORIGINAL_PATH="$PATH"
DARNIT_HOME="${DARNIT_HOME:-$HOME/.local/share/darnit}"
ASSUME_YES=0
ALL_LEVELS=0
WANT_MCP=1
TARGET=""

if [ -t 1 ]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; NC=""
fi

info() { printf '%s==>%s %s\n' "$GREEN" "$NC" "$*"; }
warn() { printf '%swarning:%s %s\n' "$YELLOW" "$NC" "$*" >&2; }
die() { printf '%serror:%s %s\n' "$RED" "$NC" "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Install darnit from source and run a first OpenSSF Baseline audit.

Usage: quickstart.sh [options] [path/to/repo]

  1. Checks for git; offers to install uv and zizmor if they are missing
  2. Uses the darnit checkout this script lives in, or clones one
  3. Installs darnit into the checkout's virtual environment, using the
     pinned versions in uv.lock, and links it into ~/.local/bin
  4. Audits the given repository (default: the current directory, if it
     is a git repository) against OpenSSF Baseline level 1
  5. Offers to register the darnit MCP server with Claude Code

Options:
  -y, --yes       Answer yes to every prompt
  --all-levels    Audit all Baseline levels, not just level 1
  --no-mcp        Do not offer to register the MCP server
  --dir DIR       Where to clone darnit (default: ~/.local/share/darnit,
                  or $DARNIT_HOME)
  -h, --help      Show this help
USAGE
}

confirm() {
  # confirm QUESTION [DEFAULT]; DEFAULT is y or n and is what Enter means.
  local reply="" default="${2:-y}" hint="[Y/n]"
  if [ "$default" = "n" ]; then
    hint="[y/N]"
  fi
  if [ "$ASSUME_YES" -eq 1 ]; then
    return 0
  fi
  if [ -t 0 ]; then
    read -r -p "$1 $hint " reply || true
  elif { : </dev/tty; } 2>/dev/null; then
    read -r -p "$1 $hint " reply </dev/tty || true
  else
    warn "no terminal to ask on; assuming no. Re-run with --yes to accept."
    return 1
  fi
  if [ -z "$reply" ]; then
    reply="$default"
  fi
  case "$reply" in
    y | Y | yes | YES) return 0 ;;
    *) return 1 ;;
  esac
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      -y | --yes) ASSUME_YES=1 ;;
      --all-levels) ALL_LEVELS=1 ;;
      --no-mcp) WANT_MCP=0 ;;
      --dir)
        if [ $# -lt 2 ]; then die "--dir needs a path"; fi
        DARNIT_HOME="$2"
        shift
        ;;
      -h | --help) usage; exit 0 ;;
      -*) die "unknown option: $1 (try --help)" ;;
      *)
        if [ -n "$TARGET" ]; then die "only one repository path is accepted"; fi
        TARGET="$1"
        ;;
    esac
    shift
  done

  # 1. Prerequisites
  if ! command -v git >/dev/null 2>&1; then
    die "git is required. Install it with your package manager and re-run."
  fi
  if ! command -v uv >/dev/null 2>&1; then
    export PATH="$HOME/.local/bin:$PATH"
  fi
  if ! command -v uv >/dev/null 2>&1; then
    info "uv is not installed. darnit uses it to manage Python and dependencies."
    if ! confirm "Install uv $UV_VERSION from astral.sh into ~/.local/bin? Your shell profile is not changed." n; then
      die "uv is required. See https://docs.astral.sh/uv/getting-started/installation/"
    fi
    if command -v curl >/dev/null 2>&1; then
      curl -LsSf "$UV_INSTALLER" | env UV_NO_MODIFY_PATH=1 sh
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- "$UV_INSTALLER" | env UV_NO_MODIFY_PATH=1 sh
    else
      die "curl or wget is needed to install uv."
    fi
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
      die "uv was installed but is not on PATH. Open a new shell and re-run."
    fi
  fi

  # 2. Locate or clone the darnit source
  local src="" self="${BASH_SOURCE[0]:-}" cand=""
  if [ -n "$self" ] && [ -f "$self" ]; then
    cand="$(cd "$(dirname "$self")/.." && pwd)"
    if [ -d "$cand/packages/darnit" ]; then
      src="$cand"
    fi
  fi
  if [ -z "$src" ]; then
    if [ -d "$DARNIT_HOME/packages/darnit" ]; then
      info "Using the existing darnit checkout at $DARNIT_HOME"
    else
      info "Cloning darnit into $DARNIT_HOME"
      git clone --depth 1 "$REPO_URL" "$DARNIT_HOME"
    fi
    src="$DARNIT_HOME"
  fi

  # 3. Install from the lockfile, so users get the tested dependency versions
  info "Installing darnit from $src (the first run can take a minute)"
  # --inexact: leave packages from other extras or groups in place, so a
  # contributor's checkout synced with --all-extras is not stripped.
  uv sync --frozen --inexact --quiet --project "$src"

  local darnit="$src/.venv/bin/darnit"
  if [ ! -x "$darnit" ]; then
    die "the darnit executable was not found at $darnit"
  fi
  info "Installed $("$darnit" --version 2>&1 | tail -1)"

  # Put darnit on PATH, without replacing anything that is not this link
  local bindir="${XDG_BIN_HOME:-$HOME/.local/bin}" link
  link="$bindir/darnit"
  if [ ! -e "$link" ] && [ ! -L "$link" ]; then
    mkdir -p "$bindir"
    ln -s "$darnit" "$link"
  fi
  if [ "$(readlink "$link" 2>/dev/null || true)" != "$darnit" ]; then
    warn "$link already exists and was left alone. Run $darnit directly, or remove it and re-run."
  else
    case ":$ORIGINAL_PATH:" in
      *":$bindir:"*) ;;
      *) warn "$bindir is not on your PATH. Add it (export PATH=\"$bindir:\$PATH\"), or run $darnit directly." ;;
    esac
  fi

  # Optional tools that some checks shell out to
  if ! command -v zizmor >/dev/null 2>&1; then
    if confirm "Install zizmor (used by the GitHub Actions workflow checks) with uv?" n; then
      uv tool install --quiet zizmor || warn "zizmor could not be installed."
    fi
  fi
  if ! command -v zizmor >/dev/null 2>&1; then
    warn "zizmor not found. The checks that use it will show as ERROR."
  fi
  if ! command -v gh >/dev/null 2>&1; then
    warn "GitHub CLI (gh) not found. Checks that query GitHub will show as ERROR. Install it from https://cli.github.com/ and run 'gh auth login'."
  elif ! gh auth token >/dev/null 2>&1; then
    warn "GitHub CLI (gh) is not logged in. Checks that query GitHub will show as ERROR. Run 'gh auth login'."
  fi

  # 4. First audit
  if [ -z "$TARGET" ] && [ -e "$PWD/.git" ] && [ "$(pwd -P)" != "$(cd "$src" && pwd -P)" ]; then
    TARGET="$PWD"
  fi
  if [ -n "$TARGET" ]; then
    if [ ! -d "$TARGET" ]; then die "not a directory: $TARGET"; fi
    TARGET="$(cd "$TARGET" && pwd)"
    local audit_args=(-q audit --no-fail --framework openssf-baseline)
    if [ "$ALL_LEVELS" -eq 0 ]; then
      audit_args+=(--tags level=1)
    fi
    if ! git -C "$TARGET" remote get-url origin >/dev/null 2>&1; then
      warn "$TARGET has no 'origin' remote. Checks that query GitHub will show as ERROR until it is pushed."
    fi
    info "Auditing $TARGET"
    "$darnit" "${audit_args[@]}" "$TARGET"
  else
    info "No repository given, so no audit was run."
  fi

  # 5. MCP registration (enables remediation through Claude Code)
  if [ "$WANT_MCP" -eq 1 ]; then
    if command -v claude >/dev/null 2>&1; then
      if confirm "Register darnit in Claude Code? This replaces any darnit entry in ~/.claude.json and reinstalls the darnit skills in ~/.claude/skills/." n; then
        if ! "$darnit" install --client claude-code --from-source --force; then
          warn "registration failed. Retry with: darnit install --client claude-code --from-source"
        fi
      fi
    else
      info "Claude Code was not found, so the MCP server was not registered."
      info "After installing it, run: darnit install --client claude-code --from-source"
    fi
  fi

  printf '\n'
  info "Done. Next steps:"
  printf '  Audit a repo:   darnit audit --framework openssf-baseline --tags level=1 /path/to/repo\n'
  printf '  Fix findings:   cd /path/to/repo && claude, then ask:\n'
  printf '                  "Audit this repo against the OpenSSF Baseline level 1, then show me\n'
  printf '                   the remediation plan as a dry run. Do not apply anything."\n'
}

main "$@"
