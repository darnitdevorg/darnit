import subprocess
from pathlib import Path


def detect_forge(local_path: str) -> str:
    """
    Figures out where the code is hosted by reading the git remote URL.
    Returns: "github", "gitlab", "bitbucket", or "unknown"
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=local_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        url = result.stdout.strip().lower()

        if "github.com" in url:
            return "github"
        elif "gitlab.com" in url:
            return "gitlab"
        elif "bitbucket.org" in url:
            return "bitbucket"
        else:
            return "unknown"

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return "unknown"


def detect_build_system(local_path: str) -> str:
    """
    Figures out what language/build tool the project uses by checking for
    well-known config files. Returns the first one found, or "unknown".
    """
    path = Path(local_path)

    checks = [
        (path / "Cargo.toml", "cargo"),        # Rust
        (path / "go.mod", "go"),               # Go
        (path / "pom.xml", "maven"),           # Java/Maven
        (path / "build.gradle", "gradle"),     # Java/Gradle
        (path / "pyproject.toml", "python"),   # Python (modern)
        (path / "setup.py", "python"),         # Python (legacy)
        (path / "package.json", "npm"),        # Node.js
        (path / "Makefile", "make"),           # Generic Make
    ]

    for file_path, build_name in checks:
        if file_path.exists():
            return build_name

    return "unknown"
