"""Console script ``darnit-amber``: run, verify, rerun."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .environment import docker_run
from .rerun import rerun, verify
from .run import run
from .utils import DEFAULT_BUNDLE, PUBLIC_KEY_FILE, TSA_URL, RunError, newest_run, read_run


def _consent(yes: bool) -> Callable[[str, str | None], bool]:
    def ask(command: str, recipe: str | None) -> bool:
        # In an image: say which one (its Dockerfile is saved with the rerun) and go.
        if recipe:
            base = next((line.split()[-1] for line in recipe.splitlines() if line.startswith("FROM ")), "")
            print(f"amber: rerunning in an image of the run's environment ({base.split('/')[-1]})", file=sys.stderr)
            return True

        # On this machine: the command runs as you, outside any container, so ask first.
        print(f"amber: `{command}` will run on this machine outside any container", file=sys.stderr)
        if yes:
            return True
        if not sys.stdin.isatty():
            print("amber: pass --yes to confirm (stdin is not a terminal)", file=sys.stderr)
            return False
        print("run it? [y/N] ", end="", file=sys.stderr, flush=True)
        return sys.stdin.readline().strip().lower() in ("y", "yes")

    return ask


def _expected_signer(a: argparse.Namespace, run_id: str) -> dict[str, Any]:
    """
    Who must have signed the run, for verify: what the verifier passed, else (with a warning) whom the run
    names. A run checked against its own claim shows it was not changed, not who made it.
    """
    signing = read_run(a.bundle, run_id)[0]["predicate"]["signing"]

    if signing.get("method") == "sigstore":
        if not a.identity or not a.issuer:
            print(
                f"amber: checking the signature against the signer the run names, {signing.get('identity')}"
                " (pass --identity <the researcher's email> to be sure)",
                file=sys.stderr,
            )
        return {"identity": a.identity or signing.get("identity"), "issuer": a.issuer or signing.get("issuer")}

    if a.pubkey is None:
        print(
            "amber: checking signatures against the bundle's own key.pub (pass --pubkey <researcher's key> to be sure)",
            file=sys.stderr,
        )
    return {"pubkey": a.pubkey or a.bundle / PUBLIC_KEY_FILE}


def main(argv: list[str] | None = None) -> int:
    # Define CLI arguments and options for commands and subcommand
    p = argparse.ArgumentParser(prog="darnit-amber", description="record, verify and rerun experiments")

    sub = p.add_subparsers(dest="cmd", required=True)

    run_args = sub.add_parser(
        "run", help="run an experiment under Witness and record it: darnit-amber run [source] -- command"
    )
    run_args.add_argument(
        "source", nargs="?", default=".", help="the experiment: a clean git checkout or URL (default: .)"
    )
    run_args.add_argument(
        "--results",
        action="append",
        metavar="PATH",
        help="a file or directory the command writes that holds its results: recorded, copied, compared (repeatable)",
    )
    run_args.add_argument("--output", type=Path, help="the bundle to record into (default: <source>/.amber)")
    run_args.add_argument("--no-trace", action="store_true", help="do not trace, so record no environment lock")
    run_args.add_argument(
        "--record-failure", action="store_true", help="record the run even if the command fails (exits non-zero)"
    )

    verify_args = sub.add_parser("verify", help="check a recorded run: id, signatures, timestamps, results, lock")

    rerun_args = sub.add_parser(
        "rerun", help="verify a recorded run, run it again in its rebuilt environment, open a shell there"
    )
    rerun_args.add_argument("--yes", action="store_true", help="with --host-environment: run without asking")
    rerun_args.add_argument(
        "--sign", action="store_true", help="record the rerun as a signed run (keyless, or with --key)"
    )
    rerun_args.add_argument("--no-shell", action="store_true", help="do not open a shell afterwards")
    rerun_args.add_argument("--host-environment", action="store_true", help="run in this machine's environment, traced")
    rerun_args.add_argument("--source", help="the experiment's source (default: the folder the bundle is in)")

    for q in (verify_args, rerun_args):
        q.add_argument("run_id", nargs="?", help="the run (default: the bundle's newest)")
        q.add_argument("--bundle", type=Path, default=Path(DEFAULT_BUNDLE), help="the bundle (default: ./.amber)")
        q.add_argument(
            "--identity", help="keyless runs: who must have signed it, e.g. an email (default: who it names)"
        )
        q.add_argument("--issuer", help="keyless runs: the login's issuer, e.g. https://github.com/login/oauth")
        q.add_argument("--pubkey", type=Path, help="runs signed with a key: its public key (default: the bundle's)")

    for q in (run_args, rerun_args):
        q.add_argument(
            "--key", type=Path, help="sign with this key (PEM) instead of keyless, as you sign in to Sigstore"
        )  # on rerun, only with --sign
        q.add_argument("--no-timestamp", action="store_true", help="do not timestamp (verify then fails)")

    argv = sys.argv[1:] if argv is None else list(argv)
    command = argv[argv.index("--") + 1 :] if "--" in argv else []
    a = p.parse_args(argv[: len(argv) - len(command) - 1] if command else argv)
    tsa = None if getattr(a, "no_timestamp", False) else TSA_URL

    # Run, Verify, or Rerun
    result = {}
    try:
        if a.cmd == "run":
            if not command:
                raise RunError("nothing to run: give the command after --")
            local = not a.source.startswith(("https://", "http://", "ssh://", "git@"))
            bundle = a.output or (Path(a.source) / DEFAULT_BUNDLE if local else Path(DEFAULT_BUNDLE))
            recorded = run(
                a.source,
                a.key,
                shlex.join(command),
                bundle,
                results=a.results,
                tsa=tsa,
                trace=False if a.no_trace else None,
                record_failure=a.record_failure,
            )
            outputs = recorded["statement"]["predicate"]["outputs"]

            if outputs:
                results = f"{len(outputs)} result file(s)"
            else:
                results = "bundle contains no result files. use --results to add files"

            print(f"amber: saved run {recorded['id'][:12]} in {bundle}/ ({results})", file=sys.stderr)

            return 0

        # verify and rerun: the newest run by default, checked against the signer it names unless told otherwise.
        run_id = a.run_id or newest_run(a.bundle)
        signer = _expected_signer(a, run_id)

        if a.cmd == "verify":
            report = verify(a.bundle, run_id, **signer)
            print(json.dumps(report, indent=2))
            return 0 if report["verified"] else 2

        if a.cmd == "rerun":
            source = a.source or (str(a.bundle.resolve().parent) if a.bundle.name == DEFAULT_BUNDLE else None)
            result = rerun(
                a.bundle,
                run_id,
                _consent(a.yes),
                key=a.key,
                **signer,
                source=source,
                tsa=tsa,
                host_environment=a.host_environment,
                sign=a.sign,
            )
    except (RunError, OSError, KeyError, ValueError) as e:
        print(f"darnit-amber: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\namber: interrupted; nothing recorded", file=sys.stderr)
        return 130

    # Rerun: whether its results match the first run's, and where its state is kept.
    image, checkout = result.pop("image"), result.pop("checkout")
    diff = result["diff"] or {}
    differences = [
        f"{len(diff.get('versions', {}))} package version(s)" if diff.get("versions") else "",
        f"{len(diff.get('files', {}))} file(s)" if diff.get("files") else "",
    ]
    environment = {
        "same_environment": ", in the same environment",
        "different_environment": f", in an environment that differs by {' and '.join(filter(None, differences))}"
        " (see result.json)",
    }.get(result["grade"], "")
    if result["changed"]:
        outcome = f"results changed: {', '.join(result['changed'])}"
    else:
        outcome = "results identical to the first run" + environment
    signed = f"signed as run {result['id'][:12]}" if result["id"] else "not signed: --sign records it as a run"
    print(f"amber: {outcome}", file=sys.stderr)
    print(f"amber: rerun saved in {os.path.relpath(result['dir'])}/ ({signed})", file=sys.stderr)

    if not a.no_shell and sys.stdin.isatty():
        # A shell where the rerun ran, to look around or try things; its prompt says where you are.
        where = f"the rerun's container, in /{checkout.name}" if image else f"the rerun's checkout, {checkout}"
        print(f"\namber: opening a shell in {where}. Type `exit` to leave.\n", file=sys.stderr)
        prompt = f"[amber rerun {run_id[:12]}] \\w # "
        if image:
            flags = ("-t", "--hostname", f"amber-rerun-{run_id[:12]}", "-e", f"PS1={prompt}")
            # --norc: the image's .bashrc would set its own prompt.
            subprocess.run(
                docker_run(image, checkout, *flags)
                + ["sh", "-c", "command -v bash >/dev/null && exec bash --norc || exec sh"]
            )
        else:
            subprocess.run([os.environ.get("SHELL", "sh")], cwd=checkout, env={**os.environ, "PS1": prompt})

    return 2 if result["changed"] else 0


if __name__ == "__main__":
    sys.exit(main())
