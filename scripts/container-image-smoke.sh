#!/usr/bin/env bash
#
# container-image-smoke.sh - Check a darnit container image the way a user runs it
#
# Usage: scripts/container-image-smoke.sh IMAGE [checkout-dir]
#
# The image's entrypoint is the darnit CLI and it has no shell. Fails unless:
#   (a) `--version` answers;
#   (b) `list` loads every shipped framework;
#   (c) each bundled tool (zizmor, gittuf, gh, uv, git, grep, gpg,
#       ssh-keygen) runs when started directly with --entrypoint, and git
#       reaches an https remote;
#   (d) the default command (`harness /repo`) without ANTHROPIC_API_KEY stops
#       with the harness's setup error, exit 2;
#   (e) `audit /repo`, the deterministic testing path, runs as the default
#       container user on the mounted checkout (default: .) and finds its
#       repository identity. The checkout belongs to the caller, not to the
#       container user, which is the case #586 broke. Pass GH_TOKEN in the
#       environment to run the platform checks too; without it only the
#       identity is asserted;
#   (f) `serve` completes an MCP stdio handshake (initialize, then
#       tools/list) and lists tools.
#
# Every check runs; the script lists the failures at the end.
#
# The checkout needs a GitHub `origin` remote. In a git worktree, the shared
# git directory is also mounted, read-only at its own path, so git can follow it.
#
# Requirements: docker, git, python3; network access to github.com for (c).

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

mounts=(-v "$checkout:/repo")
common_dir="$(git -C "$checkout" rev-parse --path-format=absolute --git-common-dir)"
if [ "$common_dir" != "$checkout/.git" ]; then
  mounts+=(-v "$common_dir:$common_dir:ro")
fi

step "(a) --version"
run_logged "$work/version.txt" docker run --rm "$image" --version || fail "--version exited with status $?"
grep -q -E '^darnit [0-9]' "$work/version.txt" || fail "--version printed no darnit version"

step "(b) list loads every framework"
run_logged "$work/list.txt" docker run --rm "$image" list || fail "list exited with status $?"
for framework in openssf-baseline gittuf reproducibility community-spec community-spec-optional; do
  grep -q -x -E "(INFO: )?  • $framework" "$work/list.txt" || fail "list did not load $framework"
done

step "(c) bundled tools"
check_tool() {
  local tool="$1"
  shift
  run_logged "$work/tool.txt" docker run --rm --entrypoint "$tool" "$image" "$@" \
    || fail "$tool $* exited with status $?"
}
check_tool zizmor --version
check_tool gittuf version
check_tool gh --version
check_tool uv --version
check_tool git --version
check_tool grep --version
check_tool gpg --version
# ssh-keygen has no version flag: make a key, which also exercises libcrypto.
check_tool ssh-keygen -q -t ed25519 -N '' -C smoke -f /tmp/smoke-key
# git-remote-https, its libraries and the CA bundle.
check_tool git ls-remote https://github.com/darnitdevorg/darnit HEAD

step "(d) default command: harness without ANTHROPIC_API_KEY"
status=0
run_logged "$work/harness.txt" docker run --rm "${mounts[@]}" "$image" || status=$?
[ "$status" -eq 2 ] || fail "harness without ANTHROPIC_API_KEY exited with status $status, not 2 (setup error)"
grep -q -F 'setup_error, missing ANTHROPIC_API_KEY environment variable' "$work/harness.txt" \
  || fail "harness without ANTHROPIC_API_KEY did not report the missing key"

step "(e) audit /repo (testing path) as the container user"
token=()
if [ -n "${GH_TOKEN:-}" ]; then
  token=(-e GH_TOKEN)
fi
run_logged "$work/audit.txt" docker run --rm "${mounts[@]}" ${token[@]+"${token[@]}"} "$image" audit --no-fail /repo \
  || fail "audit exited with status $?"
if grep -q -E 'Traceback' "$work/audit.txt"; then
  fail "the audit crashed"
fi
not_found="$(grep -o -E 'Command not found: [^ ]+' "$work/audit.txt" | sed 's/^Command not found: //' | sort -u || true)"
for command in $not_found; do
  fail "a control's tool is missing from the image: $command"
done
if grep -q -E 'no repository identity|/repos//' "$work/audit.txt"; then
  fail "the audit lost the repository identity (#586)"
fi
grep -q -E '^Trust: github\.com/[^/ ]+/[^/ ]+ ' "$work/audit.txt" || fail "the audit reported no GitHub repository identity"

step "(f) serve: MCP stdio handshake"
python3 - "$image" "darnit-smoke-mcp-$$" <<'EOF' || fail "the MCP stdio handshake failed"
import json
import subprocess
import sys
import threading

image, name = sys.argv[1], sys.argv[2]
proc = subprocess.Popen(
    ["docker", "run", "--rm", "-i", "--name", name, image, "serve"],
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
