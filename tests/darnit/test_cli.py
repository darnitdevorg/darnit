import json

from darnit.cli import main


def test_install_claude_creates_settings(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    exit_code = main(["install"])

    assert exit_code == 0

    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.exists()

    data = json.loads(settings_path.read_text())
    assert "mcpServers" in data
    assert "darnit" in data["mcpServers"]
    assert data["mcpServers"]["darnit"]["command"] == "uvx"
    assert data["mcpServers"]["darnit"]["args"] == ["--from", "darnit", "darnit", "serve"]

    captured = capsys.readouterr()
    assert "Installed darnit MCP server config" in captured.out


def test_install_cursor_creates_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    exit_code = main(["install", "--client", "cursor"])

    assert exit_code == 0

    settings_path = tmp_path / ".cursor" / "mcp.json"
    assert settings_path.exists()

    data = json.loads(settings_path.read_text())
    assert "darnit" in data["mcpServers"]


def test_install_preserves_existing_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcpServers": {
                    "other": {
                        "command": "example",
                        "args": ["serve"],
                    }
                },
            }
        )
    )

    exit_code = main(["install", "--force"])

    assert exit_code == 0

    data = json.loads(settings_path.read_text())
    assert data["theme"] == "dark"
    assert "other" in data["mcpServers"]
    assert "darnit" in data["mcpServers"]
