"""The environment lock (packages, unresolved files) and the Dockerfile it renders."""

from __future__ import annotations

from darnit_amber import environment


def test_a_lock_names_packages_and_keeps_only_unknown_files(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "_dpkg_query", lambda *a: [])  # no system packages
    venv = tmp_path.resolve() / "venv"
    site = venv / "lib/python3.12/site-packages"
    (site / "foo-1.0.dist-info").mkdir(parents=True)
    (site / "foo-1.0.dist-info/METADATA").write_text("Name: foo\nVersion: 1.0\n")
    (site / "foo-1.0.dist-info/RECORD").write_text("foo/__init__.py,,\n")
    (venv / "pyvenv.cfg").write_text("home = /opt/py/bin\nversion_info = 3.12.4\n")

    opened = [str(venv / "pyvenv.cfg"), str(site / "foo/__init__.py"), "/usr/share/zoneinfo/UTC"]
    trace = {"processes": [{"openedfiles": {path: {"sha256": "x"} for path in opened}}]}
    lock = environment.build_lock(trace, tmp_path / "checkout", set(), {})

    assert [(s["resolver"], s["name"], s["version"]) for s in lock["sources"]] == [
        ("python", "python", "3.12.4"),
        ("pypi", "foo", "1.0"),
    ]
    assert list(lock["unresolved"]) == ["/usr/share/zoneinfo/UTC"]


def test_a_dockerfile_installs_the_locked_versions():
    lock = {
        "platform": {"os": "linux", "arch": "amd64"},
        "os_release": {"id": "debian", "version_id": "12"},
        "env": {},
        "sources": [
            {"resolver": "dpkg", "name": "libc6", "version": "2.36"},
            {"resolver": "python", "name": "python", "version": "3.12.4", "venv": "/v", "system": False},
            {"resolver": "pypi", "name": "numpy", "version": "1.26.4", "site": "/v/lib/python3.12/site-packages"},
        ],
    }
    text = environment.dockerfile(lock)
    assert "FROM docker.io/library/debian:12" in text
    assert "libc6=2.36" in text and "-p 3.12.4" in text and "numpy==1.26.4" in text
