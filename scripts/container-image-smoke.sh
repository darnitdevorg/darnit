#!/usr/bin/env bash
#
# container-image-smoke.sh - Check a darnit container image the way a user runs it
#
# Usage: scripts/container-image-smoke.sh IMAGE [checkout-dir]
#
# Fails unless the image:
#   (a) answers --version;
#   (b) loads every shipped framework in `darnit list`;
#   (c) has zizmor, gittuf, gpg, ssh-keygen, gh and git, through the
#       entrypoint's escape hatch;
#   (d) audits the checkout (default: .) mounted at /repo as the default
#       container user, and finds its repository identity. The checkout belongs
#       to the caller, not to the container's uid 10001, which is the case
#       #586 broke. Pass GH_TOKEN in the environment to run the platform
#       checks too; without it only the identity is asserted;
#   (e) completes an MCP stdio handshake (`mcp` mode: initialize, then
#       tools/list) and lists tools.
#
# Every check runs; the script lists the failures at the end.
#
# The checkout needs a GitHub `origin` remote. In a git worktree, the shared
# git directory is also mounted, read-only at its own path, so git can follow it.
#
# Requirements: docker, git, python3.

set -euo pipefail

failures=()
fail() { echo "FAIL: $*" >&2; failures+=("$*"); }
step() { echo; echo "== $*"; }

# run_logged FILE CMD...: run CMD with its output in FILE and print FILE.
# Returns CMD's exit status.
run_logged() {
  local out="$1" status=0
  shift
  "$@" >"$out" 2>&1 || status=$?
  cat "$out"
  return "$status"
}

[ $# -ge 1 ] || { echo "usage: $0 IMAGE [checkout-dir]" >&2; exit 64; }
image="$1"
checkout="$(cd "${2:-.}" && pwd)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

step "(a) --version"
run_logged "$work/version.txt" docker run --rm "$image" --version || fail "--version exited with status $?"
grep -q -E '^darnit [0-9]' "$work/version.txt" || fail "--version printed no darnit version"

step "(b) darnit list loads every framework"
run_logged "$work/list.txt" docker run --rm "$image" darnit list || fail "darnit list exited with status $?"
for framework in openssf-baseline gittuf reproducibility community-spec community-spec-optional; do
  grep -q -x -E "(INFO: )?  • $framework" "$work/list.txt" || fail "darnit list did not load $framework"
done

step "(c) bundled tools"
for tool in zizmor gittuf gpg ssh-keygen gh git; do
  case "$tool" in
    gittuf) version=(gittuf version) ;;
    ssh-keygen) version=(ssh -V) ;;  # ssh-keygen has no version flag
    *) version=("$tool" --version) ;;
  esac
  # shellcheck disable=SC2016  # expanded in the container
  run_logged "$work/$tool.txt" docker run --rm "$image" sh -c 'command -v "$0" && "$@"' "$tool" "${version[@]}" \
    || fail "$tool is missing from the image or did not print its version"
done

step "(d) audit of the mounted checkout as the container user"
mounts=(-v "$checkout:/repo")
common_dir="$(git -C "$checkout" rev-parse --path-format=absolute --git-common-dir)"
if [ "$common_dir" != "$checkout/.git" ]; then
  mounts+=(-v "$common_dir:$common_dir:ro")
fi
token=()
if [ -n "${GH_TOKEN:-}" ]; then
  token=(-e GH_TOKEN)
fi
run_logged "$work/audit.txt" docker run --rm "${mounts[@]}" ${token[@]+"${token[@]}"} "$image" audit --no-fail \
  || fail "darnit audit exited with status $?"
if grep -q -E 'Traceback' "$work/audit.txt"; then
  fail "the audit crashed"
fi
if grep -q -E 'Command not found' "$work/audit.txt"; then
  fail "a control's tool is missing from the image: $(grep -o -E 'Command not found: [^ ]+' "$work/audit.txt" | sort -u | paste -sd, -)"
fi
if grep -q -E 'no repository identity|/repos//' "$work/audit.txt"; then
  fail "the audit lost the repository identity (#586)"
fi
grep -q -E '^Trust: github\.com/[^/ ]+/[^/ ]+ ' "$work/audit.txt" || fail "the audit reported no GitHub repository identity"

step "(e) MCP stdio handshake"
python3 - "$image" "darnit-smoke-mcp-$$" <<'EOF' || fail "the MCP stdio handshake failed"
import json
import subprocess
import sys
import threading

image, name = sys.argv[1], sys.argv[2]
proc = subprocess.Popen(
    ["docker", "run", "--rm", "-i", "--name", name, image, "mcp"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
)


def stop():
    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


timer = threading.Timer(180, stop)
timer.start()


def send(message):
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def receive(request_id):
    for line in proc.stdout:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == request_id:
            return message
    sys.exit(f"the MCP server closed stdout without answering request {request_id}")


try:
    send({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "container-image-smoke", "version": "0"},
        },
    })
    init = receive(1)
    if "result" not in init:
        sys.exit(f"initialize returned {init}")
    print("server:", init["result"].get("serverInfo"))
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = receive(2).get("result", {}).get("tools", [])
    if not tools:
        sys.exit("tools/list returned no tools")
    print(f"tools/list: {len(tools)} tools")
finally:
    timer.cancel()
    try:
        proc.stdin.close()
    except BrokenPipeError:
        pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        stop()
        proc.wait()
EOF

echo
if [ "${#failures[@]}" -gt 0 ]; then
  echo "FAILED: $image failed ${#failures[@]} container smoke check(s):" >&2
  printf '  - %s\n' "${failures[@]}" >&2
  exit 1
fi
echo "OK: $image passed the container smoke checks"
