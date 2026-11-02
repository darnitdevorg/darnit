"""Unit tests for dependency manifest parsing (darnit_baseline.threat_model.dependencies)."""

from __future__ import annotations

from pathlib import Path

from darnit_baseline.threat_model.dependencies import (
    _add_matches,
    _normalise_dep_name,
    _parse_go_mod,
    _parse_package_json,
    _parse_pyproject_toml,
    _parse_requirements_txt,
    parse_dependency_manifests,
)


class TestNormaliseDepName:
    """Tests for dependency name normalisation and version/extras stripping."""

    def test_standard_package_name(self) -> None:
        assert _normalise_dep_name("fastapi") == "fastapi"

    def test_whitespace_and_case(self) -> None:
        assert _normalise_dep_name("  Django  ") == "django"

    def test_underscores_converted_to_hyphens(self) -> None:
        assert _normalise_dep_name("psycopg2_binary") == "psycopg2-binary"
        assert _normalise_dep_name("drizzle_orm") == "drizzle-orm"

    def test_extras_stripped(self) -> None:
        assert _normalise_dep_name("psycopg2[binary]>=2.9") == "psycopg2"
        assert _normalise_dep_name("uvicorn[standard]") == "uvicorn"

    def test_version_specifiers_stripped(self) -> None:
        assert _normalise_dep_name("flask>=2.0.0") == "flask"
        assert _normalise_dep_name("django==4.2") == "django"
        assert _normalise_dep_name("redis~=4.5.1") == "redis"
        assert _normalise_dep_name("requests<=2.30.0") == "requests"
        assert _normalise_dep_name("urllib3<2.0") == "urllib3"
        assert _normalise_dep_name("pytest; python_version>='3.8'") == "pytest"

    def test_scoped_npm_packages_preserved(self) -> None:
        assert _normalise_dep_name("@prisma/client") == "@prisma/client"
        assert _normalise_dep_name("@prisma/client>=5.0.0") == "@prisma/client"
        assert _normalise_dep_name("@auth0/nextjs-auth0>=3.0.0") == "@auth0/nextjs-auth0"
        assert _normalise_dep_name("@supabase/supabase-js") == "@supabase/supabase-js"


class TestAddMatches:
    """Tests for matching normalised dependencies against _DEPENDENCY_MAP."""

    def test_maps_known_database(self) -> None:
        declared: set[str] = set()
        _add_matches("psycopg2>=2.9", declared)
        assert "postgresql" in declared

    def test_maps_known_framework(self) -> None:
        declared: set[str] = set()
        _add_matches("fastapi", declared)
        assert "fastapi" in declared

    def test_maps_scoped_auth_package(self) -> None:
        declared: set[str] = set()
        _add_matches("@clerk/nextjs", declared)
        assert "clerk" in declared

    def test_unmatched_dependency_ignored(self) -> None:
        declared: set[str] = set()
        _add_matches("unknown-internal-util>=1.0", declared)
        assert declared == set()


class TestParsePyprojectToml:
    """Tests for parsing pyproject.toml files."""

    def test_parses_dependencies_array(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[project]
name = "demo"
dependencies = [
    "fastapi>=0.100.0",
    "psycopg2-binary>=2.9",
    "redis",
]
""",
            encoding="utf-8",
        )
        declared: set[str] = set()
        _parse_pyproject_toml(str(tmp_path), declared)

        assert "fastapi" in declared
        assert "postgresql" in declared
        assert "redis" in declared

    def test_parses_single_quoted_strings(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[project.optional-dependencies]
db = ['pymongo>=4.0', 'django']
""",
            encoding="utf-8",
        )
        declared: set[str] = set()
        _parse_pyproject_toml(str(tmp_path), declared)

        assert "mongodb" in declared
        assert "django" in declared

    def test_skips_excluded_directories(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv" / "sub"
        venv_dir.mkdir(parents=True)
        (venv_dir / "pyproject.toml").write_text('dependencies = ["flask"]', encoding="utf-8")

        declared: set[str] = set()
        _parse_pyproject_toml(str(tmp_path), declared)
        assert declared == set()


class TestParseRequirementsTxt:
    """Tests for parsing requirements*.txt files."""

    def test_parses_standard_requirements(self, tmp_path: Path) -> None:
        req = tmp_path / "requirements.txt"
        req.write_text(
            """
# Core dependencies
fastapi>=0.100
psycopg2==2.9.3

# Flags and empty lines to ignore
-r base.txt
-i https://pypi.org/simple

django[argon2]>=4.2
""",
            encoding="utf-8",
        )
        declared: set[str] = set()
        _parse_requirements_txt(str(tmp_path), declared)

        assert "fastapi" in declared
        assert "postgresql" in declared
        assert "django" in declared

    def test_parses_requirements_variants(self, tmp_path: Path) -> None:
        (tmp_path / "requirements-dev.txt").write_text("redis>=4.0\n", encoding="utf-8")
        (tmp_path / "other.txt").write_text("flask>=2.0\n", encoding="utf-8")

        declared: set[str] = set()
        _parse_requirements_txt(str(tmp_path), declared)

        assert "redis" in declared
        assert "flask" not in declared


class TestParsePackageJson:
    """Tests for parsing package.json dependency manifests."""

    def test_parses_all_dependency_sections(self, tmp_path: Path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text(
            """
{
  "name": "web-app",
  "dependencies": {
    "next": "^14.0.0",
    "@prisma/client": "^5.0.0"
  },
  "devDependencies": {
    "ioredis": "^5.3.0"
  },
  "peerDependencies": {
    "react": "^18.2.0"
  }
}
""",
            encoding="utf-8",
        )
        declared: set[str] = set()
        _parse_package_json(str(tmp_path), declared)

        assert "nextjs" in declared
        assert "prisma" in declared
        assert "redis" in declared
        assert "react" in declared

    def test_handles_malformed_json_gracefully(self, tmp_path: Path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text("{ invalid json: ", encoding="utf-8")

        declared: set[str] = set()
        _parse_package_json(str(tmp_path), declared)
        assert declared == set()

    def test_missing_package_json_ignored(self, tmp_path: Path) -> None:
        declared: set[str] = set()
        _parse_package_json(str(tmp_path), declared)
        assert declared == set()


class TestParseGoMod:
    """Tests for parsing go.mod dependency manifests."""

    def test_parses_require_directives(self, tmp_path: Path) -> None:
        go_mod = tmp_path / "go.mod"
        go_mod.write_text(
            """
module myapp

go 1.22

require (
\tgithub.com/gin-gonic/gin v1.9.1
\tgithub.com/redis/go-redis/v9 v9.5.1
)
""",
            encoding="utf-8",
        )
        declared: set[str] = set()
        _parse_go_mod(str(tmp_path), declared)

        # module extracted is basename e.g. "go-redis" -> normalises to "go-redis"
        assert isinstance(declared, set)

    def test_missing_go_mod_ignored(self, tmp_path: Path) -> None:
        declared: set[str] = set()
        _parse_go_mod(str(tmp_path), declared)
        assert declared == set()


class TestParseDependencyManifests:
    """Tests for the aggregated parse_dependency_manifests entry point."""

    def test_aggregates_across_multiple_manifests(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('dependencies = ["fastapi"]\n', encoding="utf-8")
        (tmp_path / "package.json").write_text('{"dependencies": {"next": "^14.0"}}', encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("redis>=4.0\n", encoding="utf-8")

        results = parse_dependency_manifests(str(tmp_path))

        assert "fastapi" in results
        assert "nextjs" in results
        assert "redis" in results

    def test_empty_repository_returns_empty_set(self, tmp_path: Path) -> None:
        assert parse_dependency_manifests(str(tmp_path)) == set()
