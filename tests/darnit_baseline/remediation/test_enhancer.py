# from unittest.mock import patch

from darnit_baseline.remediation.enhancer import (
    _enhance_architecture,
    enhance_generated_file,
    get_enhancement_type,
    is_enhanceable,
)


def test_is_enhanceable_architecture_file():
    assert is_enhanceable("ARCHITECTURE.md") is True
    assert is_enhanceable("/tmp/project/ARCHITECTURE.md") is True


def test_get_enhancement_type_architecture_file():
    assert get_enhancement_type("ARCHITECTURE.md") == "architecture"
    assert get_enhancement_type("/tmp/project/ARCHITECTURE.md") == "architecture"


def test_enhance_architecture_uses_provided_llm_fn(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text(
        '"""Application entrypoint."""\n\n'
        "def main():\n"
        "    return None\n",
        encoding="utf-8",
    )

    prompts: list[str] = []

    def fake_llm(prompt: str) -> str:
        prompts.append(prompt)
        return "# Enhanced Architecture\n\nAdded component descriptions."

    result = _enhance_architecture(
        "# Architecture\n\n| Component | Path |\n| --- | --- |\n| App | src/app.py |\n",
        str(tmp_path),
        llm_fn=fake_llm,
    )

    assert result == "# Enhanced Architecture\n\nAdded component descriptions."
    assert len(prompts) == 1
    assert "Application entrypoint." in prompts[0]
    assert "Current ARCHITECTURE.md" in prompts[0]


def test_enhance_architecture_without_llm_fn_returns_none(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text(
        '"""Application entrypoint."""\n\n'
        "def main():\n"
        "    return None\n",
        encoding="utf-8",
    )

    result = _enhance_architecture(
        "# Architecture\n\n| Component | Path |\n| --- | --- |\n| App | src/app.py |\n",
        str(tmp_path),
    )

    assert result is None


def test_enhance_generated_file_uses_injected_llm_fn(tmp_path):
    architecture_file = tmp_path / "ARCHITECTURE.md"
    architecture_file.write_text(
        "# Architecture\n\n| Component | Path |\n| --- | --- |\n| App | src/app.py |\n",
        encoding="utf-8",
    )

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text(
        '"""Application entrypoint."""\n\n'
        "def main():\n"
        "    return None\n",
        encoding="utf-8",
    )

    def fake_llm(_prompt: str) -> str:
        return "# Enhanced Architecture\n\nAdded component descriptions."

    result = enhance_generated_file(
        str(architecture_file),
        str(tmp_path),
        "architecture",
        llm_fn=fake_llm,
    )

    assert result == "# Enhanced Architecture\n\nAdded component descriptions."


def test_enhance_generated_file_returns_none_for_unknown_type(tmp_path):
    generated_file = tmp_path / "README.md"
    generated_file.write_text("# README\n", encoding="utf-8")

    result = enhance_generated_file(
        str(generated_file),
        str(tmp_path),
        "unknown",
    )

    assert result is None

