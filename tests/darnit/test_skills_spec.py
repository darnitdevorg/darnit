"""Tests that skill definitions conform to the Agent Skills specification.

Uses the skills-ref reference library to validate SKILL.md frontmatter,
directory structure, and naming conventions.

See: https://agentskills.io/specification
"""

from pathlib import Path

import pytest
from skills_ref import read_properties, validate

SKILLS_DIR = Path(__file__).parent.parent.parent / "packages" / "darnit" / "src" / "darnit" / "skills"

EXPECTED_SKILLS = ["darnit-audit", "darnit-context", "darnit-comply", "darnit-remediate"]


def _skill_path(name: str) -> Path:
    return SKILLS_DIR / name


class TestSkillsSpecCompliance:
    """Validate all skills against the Agent Skills specification."""

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_directory_exists(self, skill_name: str) -> None:
        """Each skill must be a directory with a SKILL.md file."""
        path = _skill_path(skill_name)
        assert path.is_dir(), f"Skill directory missing: {path}"
        assert (path / "SKILL.md").is_file(), f"SKILL.md missing in {path}"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_validates(self, skill_name: str) -> None:
        """Each skill must pass skills-ref validation (frontmatter, naming, structure)."""
        problems = validate(_skill_path(skill_name))
        assert problems == [], f"Skill '{skill_name}' has validation errors: {problems}"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_name_matches_directory(self, skill_name: str) -> None:
        """The frontmatter 'name' field must match the directory name."""
        props = read_properties(_skill_path(skill_name))
        assert props.name == skill_name, (
            f"Skill name mismatch: directory is '{skill_name}' "
            f"but frontmatter name is '{props.name}'"
        )

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_has_description(self, skill_name: str) -> None:
        """Each skill must have a non-empty description."""
        props = read_properties(_skill_path(skill_name))
        assert props.description, f"Skill '{skill_name}' has empty description"
        assert len(props.description) >= 20, (
            f"Skill '{skill_name}' description too short ({len(props.description)} chars)"
        )

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
    def test_skill_under_size_limit(self, skill_name: str) -> None:
        """SKILL.md should be under 500 lines per spec recommendation."""
        skill_md = _skill_path(skill_name) / "SKILL.md"
        line_count = len(skill_md.read_text().splitlines())
        assert line_count <= 500, (
            f"Skill '{skill_name}' SKILL.md is {line_count} lines "
            f"(spec recommends under 500)"
        )
