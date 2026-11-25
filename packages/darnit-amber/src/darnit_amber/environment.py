"""What an experiment's environment was, as installable package identities, and the image that rebuilds it.

Witness's trace lists every file each process opened and every program it ran, with sha256.
``build_lock`` turns that into a lock:

  1. files inside the checkout are kept as they are (``checkout``);
  2. every other file is offered to each resolver in RESOLVERS, which names the packages it can
     (dpkg: ``libc6 2.36``; python: the interpreter, and pypi distributions) and claims their files;
  3. files that no resolver claims are kept with their digest (``unresolved``).

``dockerfile`` renders a lock as a plain Dockerfile; ``build_image`` builds it and checks what the
image holds against the lock. Supporting another ecosystem is one resolver plus one install step.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .utils import RunError, call, sha256

UV_IMAGE = "ghcr.io/astral-sh/uv:0.7.4"  # mounted into the build step that needs it, never copied into the image

_IGNORED = ("/proc/", "/sys/", "/dev/", "/run/")
_SITE = re.compile(r"^(?P<site>.*/(?:site|dist)-packages)/(?P<rel>.+)$")
_STDLIB = re.compile(r"/lib/python(?P<ver>\d+\.\d+)/")


def traced_files(command_run: dict[str, Any], checkout: Path | None = None) -> dict[str, str]:
    """Path -> sha256 of every file a traced process opened or ran (running a program is not opening it)."""
    files: dict[str, str] = {}
    for process in command_run.get("processes") or []:
        opened = list((process.get("openedfiles") or {}).items())
        program = (process.get("program"), process.get("programdigest"))

        for path, digest in [*opened, program]:
            if not path or not (digest or {}).get("sha256"):
                continue
            if checkout is not None and not path.startswith("/"):
                path = str(checkout / path)
            files.setdefault(os.path.normpath(path), digest["sha256"])
    return files


# Resolvers. Each takes the paths not yet accounted for (symlinks resolved), and returns
# (the packages it found, the paths those packages account for). Later ones see only what is left.


def _dpkg_query(*args: str) -> list[str]:
    if not shutil.which("dpkg-query"):
        return []
    return subprocess.run(["dpkg-query", *args], capture_output=True, text=True).stdout.splitlines()


def _resolve_dpkg(paths: list[str]) -> tuple[list[dict[str, Any]], set[str]]:
    """The dpkg package that installed each path, with its version."""
    # With merged /usr, dpkg may list /lib/x as /usr/lib/x: ask for both spellings.
    asked = {spelling: path for path in paths for spelling in (path, "/usr" + path)}

    # `dpkg-query -S` prints "package[:arch][, other]: /path" for each path a package owns.
    owner: dict[str, str] = {}
    for line in _dpkg_query("-S", *asked) if asked else []:
        package, sep, path = line.partition(": ")
        if sep and path in asked and not line.startswith("diversion "):
            owner.setdefault(asked[path], package.split(",")[0].split(":")[0])

    packages = sorted(set(owner.values()))
    listing = _dpkg_query("-W", "-f", "${Package}\t${Version}\n", *packages) if packages else []
    versions = dict(line.split("\t", 1) for line in listing if "\t" in line)

    found = [{"resolver": "dpkg", "name": name, "version": versions.get(name)} for name in packages]
    return found, set(owner)


def _resolve_python(paths: list[str]) -> tuple[list[dict[str, Any]], set[str]]:
    """The Python interpreter (version, venv, standard library) and each distribution whose RECORD lists a path."""
    interpreter = {"resolver": "python", "name": "python", "version": None, "venv": None, "system": True}
    interpreter_files: tuple[str, ...] = ()  # the install root of an interpreter that no distro package installed
    claimed: set[str] = set()

    # A venv's pyvenv.cfg names its interpreter: the version, and `home`, the directory it runs from.
    for path in paths:
        if not (path.endswith("/pyvenv.cfg") and Path(path).is_file()):
            continue
        cfg = Path(path).read_text(errors="replace")
        version = re.search(r"^version(?:_info)?\s*=\s*([0-9][0-9.]*)", cfg, re.M)
        home = re.search(r"^home\s*=\s*(.+)$", cfg, re.M)
        root = str(Path(home[1].strip()).parent) if home else "/usr"

        # A distribution's interpreter is installed by its package (dpkg); any other one by uv, from the version.
        system = root in ("/usr", "/usr/local", "/")
        interpreter |= {"version": version[1] if version else None, "venv": str(Path(path).parent), "system": system}
        interpreter_files = () if system else (root + "/",)
        claimed.add(path)

    # Sort the rest: files under a site-packages directory, and files of the interpreter itself.
    sites: dict[str, dict[str, str]] = {}  # site-packages dir -> {path relative to it: path}
    for path in paths:
        if m := _SITE.match(path):
            sites.setdefault(m["site"], {})[m["rel"]] = path
        elif (m := _STDLIB.search(path)) or path.startswith(interpreter_files):
            interpreter["version"] = interpreter["version"] or (m["ver"] if m else None)
            claimed.add(path)

    # In each site-packages, a distribution's dist-info/RECORD lists the files it installed. One installed from
    # a path, a URL or git (it has direct_url.json, e.g. an editable install) is not on an index: not named.
    found: list[dict[str, Any]] = []
    for site, files in sorted(sites.items()):
        owner: dict[str, tuple[str, str]] = {}  # path relative to site -> (name, version)
        for info in Path(site).glob("*.dist-info"):
            if (info / "direct_url.json").exists():
                continue
            try:
                metadata = (info / "METADATA").read_text(errors="replace")
                record = (info / "RECORD").read_text(errors="replace")
            except OSError:
                continue
            name = re.search(r"^Name: *(.+)$", metadata, re.M)
            version = re.search(r"^Version: *(.+)$", metadata, re.M)
            if name and version:
                for line in record.splitlines():
                    owner[line.split(",", 1)[0]] = (name[1].strip(), version[1].strip())

        claimed |= {path for rel, path in files.items() if rel in owner or rel.startswith("_virtualenv")}
        for dist_name, dist_version in sorted({owner[rel] for rel in files if rel in owner}):
            found.append({"resolver": "pypi", "name": dist_name, "version": dist_version, "site": site})

    if interpreter["version"] or found:
        found.insert(0, interpreter)
    return found, claimed


RESOLVERS = (_resolve_dpkg, _resolve_python)


# The lock.


def build_lock(command_run: dict[str, Any], checkout: Path, exclude: set[str], env: dict[str, str]) -> dict[str, Any]:
    """The lock of a traced run. ``exclude``: checkout paths that are outputs; ``env``: variables to set again.

    Must run on the machine that ran the experiment, right after: resolvers read its package databases.
    """
    checkout = checkout.resolve()

    # Split the traced files: the checkout's own, and everything outside it.
    outside: dict[str, str] = {}
    inside: dict[str, str] = {}
    for path, digest in traced_files(command_run, checkout).items():
        if path.startswith(_IGNORED) or path.endswith(".pyc"):  # bytecode embeds timestamps
            continue
        if not Path(path).is_relative_to(checkout):
            outside[path] = digest
            continue
        rel = Path(path).relative_to(checkout).as_posix()
        if rel not in exclude and not rel.startswith(".git/"):
            inside[rel] = digest

    # Offer the outside files to each resolver, by their real path: a venv's bin/python is the interpreter.
    left: dict[str, list[str]] = {}  # real path -> the traced paths that lead to it
    for path in sorted(outside):
        left.setdefault(os.path.realpath(path), []).append(path)
    sources = []
    for resolver in RESOLVERS:
        found, claimed = resolver(sorted(left))
        sources += found
        left = {real: traced for real, traced in left.items() if real not in claimed}

    # The distribution and platform, so a Dockerfile can start from the same base image.
    try:
        release = dict(re.findall(r'^(ID|VERSION_ID)="?([^"\n]*)"?$', Path("/etc/os-release").read_text(), re.M))
    except OSError:
        release = {}
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())

    return {
        "platform": {"os": sys.platform, "arch": arch},
        "os_release": {k.lower(): v for k, v in release.items()} or None,
        "container": Path("/.dockerenv").exists() or Path("/run/.containerenv").exists(),
        "env": env,
        "sources": sources,
        "unresolved": {path: outside[path] for traced in left.values() for path in traced},
        "checkout": inside,
    }


def lock_matches_trace(lock: dict[str, Any], command_run: dict[str, Any]) -> list[str]:
    """Lock entries whose digest the trace does not record at that path (empty: the lock is the trace's)."""
    traced = traced_files(command_run)
    problems = [path for path, digest in (lock.get("unresolved") or {}).items() if traced.get(path) != digest]

    # The trace has the checkout's files under the absolute path it ran in, or relative to it.
    for rel, digest in (lock.get("checkout") or {}).items():
        if not any(d == digest and (t == rel or t.endswith("/" + rel)) for t, d in traced.items()):
            problems.append(f"checkout: {rel}")
    return problems


def diff_locks(first: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Package versions that differ, and the first lock's unresolved files ``other`` has differently (None: absent)."""
    versions_a, versions_b = (
        {f"{s['resolver']}:{s['name']}": s["version"] for s in lock.get("sources") or []} for lock in (first, other)
    )
    files_a, files_b = first.get("unresolved") or {}, other.get("unresolved") or {}

    versions = {
        name: [versions_a.get(name), versions_b.get(name)]
        for name in sorted(set(versions_a) | set(versions_b))
        if versions_a.get(name) != versions_b.get(name)
    }
    files = {
        path: [digest, files_b.get(path)] for path, digest in sorted(files_a.items()) if files_b.get(path) != digest
    }
    return {"versions": versions, "files": files, "identical": not versions and not files}


# The image.


def dockerfile(lock: dict[str, Any]) -> str:
    """The lock as a Dockerfile: its distribution's base image for its platform, its packages, its variables."""
    plat, release = lock.get("platform") or {}, lock.get("os_release") or {}
    if plat.get("os") != "linux" or lock.get("container"):
        raise RunError("only a Linux run outside a container unpacks into an image")
    if not release.get("id") or not release.get("version_id"):
        raise RunError("the lock does not record the run's distribution (/etc/os-release)")

    by_resolver = {r: [s for s in lock["sources"] if s["resolver"] == r] for r in ("dpkg", "python", "pypi")}
    # The platform is not in FROM: build_image passes it to `docker build --platform`, which BuildKit prefers.
    lines = [
        f"# platform: linux/{plat['arch']} (docker build --platform linux/{plat['arch']})",
        f"FROM docker.io/library/{release['id']}:{release['version_id']}",
    ]

    # dpkg packages at their versions. One the archive no longer has: the current version; rerun reports the change.
    if by_resolver["dpkg"]:
        install = "apt-get install -yq --no-install-recommends"
        pinned = shlex.join(f"{s['name']}={s['version']}" for s in by_resolver["dpkg"])
        names = shlex.join(s["name"] for s in by_resolver["dpkg"])
        lines.append(
            "RUN export DEBIAN_FRONTEND=noninteractive && apt-get update -q && "
            f"({install} --allow-downgrades {pinned} || {install} {names}) "
            "&& rm -rf /var/lib/apt/lists/*"
        )

    # Python with uv: the venv at its path and interpreter version, then each distribution into its site-packages.
    python: dict[str, Any] = next(iter(by_resolver["python"]), {})
    venv = python.get("venv")
    interpreter = (["-p", python["version"]] if python.get("version") else []) + ["--python-preference"]
    interpreter.append("only-system" if python.get("system", True) else "only-managed")
    uv = ["env", "UV_PYTHON_INSTALL_DIR=/opt/uv-python", "uv"]  # readable by any user, unlike /root

    python_steps = [[*uv, "venv", "-q", "--no-config", *interpreter, venv]] if venv else []
    pins_by_site: dict[str, list[str]] = {}
    for s in by_resolver["pypi"]:
        pins_by_site.setdefault(s["site"], []).append(f"{s['name']}=={s['version']}")
    for site, pins in sorted(pins_by_site.items()):
        target = ["-p", venv] if venv and site.startswith(venv + "/") else [*interpreter, "--target", site]
        python_steps.append([*uv, "pip", "install", "-q", "--no-config", "--no-build", "--no-deps", *target, *pins])
    if python_steps:
        mount = f"--mount=type=bind,from={UV_IMAGE},source=/uv,target=/usr/local/bin/uv"
        lines.append(f"RUN {mount} " + " && ".join(shlex.join(step) for step in python_steps))

    # The recorded variables, and the venv on PATH.
    env = dict(lock.get("env") or {})
    if venv:
        env |= {"PATH": f"{venv}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "VIRTUAL_ENV": venv}
    lines += [f"ENV {k}={json.dumps(v)}" for k, v in sorted(env.items())]
    return "\n".join(lines) + "\n"


def build_image(lock: dict[str, Any], log: Path | None = None) -> dict[str, Any]:
    """
    Build `dockerfile(lock)` unless this machine has it already, then diff what the image holds against the lock.
    """

    runtime = next((r for r in ("podman", "docker") if shutil.which(r)), None)
    if runtime is None:
        raise RunError("rebuilding the environment needs podman or docker")

    # The tag is the Dockerfile's digest, so an unchanged lock reuses the image.
    text, plat = dockerfile(lock), f"linux/{lock['platform']['arch']}"
    tag = "amber-env:" + sha256(text.encode())[:16]
    if call([runtime, "image", "inspect", tag], log, check=False).returncode != 0:
        with tempfile.TemporaryDirectory(prefix="amber-build-") as context:
            (Path(context) / "Dockerfile").write_text(text)
            # RUN --mount needs BuildKit, which older docker uses only when asked; podman ignores this.
            env = {**os.environ, "DOCKER_BUILDKIT": "1"}
            call([runtime, "build", "--platform", plat, "-t", tag, context], log, env=env)  # its output: in `log`
    image = {"runtime": runtime, "image": tag, "platform": plat, "dockerfile": text}
    in_image = docker_run(image)

    # The dpkg versions the image has.
    names = [s["name"] for s in lock["sources"] if s["resolver"] == "dpkg"]
    listing = ""
    if names:
        listing = call([*in_image, "dpkg-query", "-W", "-f", "${Package}\\t${Version}\\n", *names], log).stdout
    installed = dict(line.split("\t", 1) for line in listing.splitlines())
    sources = [s | {"version": installed.get(s["name"])} if s["resolver"] == "dpkg" else s for s in lock["sources"]]

    # The digests of the unresolved files at the same paths (a missing file prints no line).
    paths = "\0".join(lock.get("unresolved") or {})
    listing = call([*in_image, "xargs", "-0", "-r", "sha256sum", "--"], log, check=False, input=paths).stdout
    unresolved = {path: digest for digest, _, path in (line.partition("  ") for line in listing.splitlines())}

    return image | {"diff": diff_locks(lock, {"sources": sources, "unresolved": unresolved})}


def docker_run(image: dict[str, Any], checkout: Path | None = None, *flags: str) -> list[str]:
    """``<runtime> run`` in the image, with ``checkout`` mounted as the working directory, at ``/<its name>``."""
    mount = ["-v", f"{checkout}:/{checkout.name}", "-w", f"/{checkout.name}"] if checkout else []
    return [image["runtime"], "run", "--rm", "-i", *flags, "--platform", image["platform"], *mount, image["image"]]
